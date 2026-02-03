"""
真心话大冒险游戏模块
群组内的掷骰子游戏，最大点数者为提问方，最小点数者为回答方
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dynaconf import Dynaconf
from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from kmua.database import (
    get_dealer_mode_config,
    upsert_dealer_mode_config,
    clear_late_players,
    add_late_player,
    add_question_reference,
    get_question_count,
    get_random_question,
    get_top_questions,
    increment_question_used_count,
)

# 加载配置
_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)

# 定时任务初始化标记
_scheduler_initialized = False
_scheduler_lock = asyncio.Lock()

# 默认配置
DEFAULT_TIMEOUT_SECONDS = 60
MIN_TIMEOUT = 10
MAX_TIMEOUT = 600
AUTO_DELETE_DELAY = 10  # 提示消息自动删除延迟（秒）


@dataclass
class PendingQuestion:
    """待提问信息"""
    chat_id: int
    thread_id: Optional[int]
    winner_id: int
    loser_ids: List[int]
    winner_mentions: List[str]  # 提问方提及列表
    loser_mentions: List[str]   # 回答方提及列表
    timestamp: float


@dataclass
class PlayerRecord:
    """玩家记录"""
    user_id: int
    username: Optional[str]
    first_name: str
    rolls: list[int] = field(default_factory=list)

    @property
    def min_roll(self) -> int:
        """有效点数（取最小值）"""
        return min(self.rolls) if self.rolls else 0

    @property
    def mention(self) -> str:
        """用户提及字符串"""
        if self.username:
            return f"@{self.username}"
        return f"[{self.first_name}](tg://user?id={self.user_id})"


@dataclass
class GameSession:
    """游戏会话"""
    chat_id: int
    initiator_id: int
    initiator_mention: str
    timeout_seconds: int
    start_time: float
    message_thread_id: Optional[int] = None  # 话题 ID（用于话题群组）
    players: Dict[int, PlayerRecord] = field(default_factory=dict)
    is_active: bool = True
    timer_task: Optional[asyncio.Task] = None

    @property
    def game_key(self) -> tuple:
        """游戏唯一标识（chat_id, message_thread_id）"""
        return (self.chat_id, self.message_thread_id)


def get_game_key(chat_id: int, message_thread_id: Optional[int]) -> tuple:
    """获取游戏键"""
    return (chat_id, message_thread_id)


# 全局状态 - 键改为 (chat_id, message_thread_id) 元组
_active_games: Dict[tuple, GameSession] = {}
_games_lock = asyncio.Lock()

# 待提问数据 - 键为提问方 user_id
_pending_questions: Dict[int, PendingQuestion] = {}
_questions_lock = asyncio.Lock()


async def _init_scheduler_once(client: Client) -> None:
    """一次性初始化定时任务"""
    global _scheduler_initialized

    async with _scheduler_lock:
        if _scheduler_initialized:
            return

        try:
            from .dealer_scheduler import init_scheduler
            await init_scheduler(client)
            _scheduler_initialized = True
            logger.info("✅ 荷官模式定时任务已初始化")
        except Exception as e:
            logger.exception(f"❌ 荷官模式定时任务初始化失败: {e}")


async def is_chat_admin(client: Client, chat_id: int, user_id: int) -> bool:
    """检查用户是否为群组管理员"""
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception as e:
        logger.warning(f"检查管理员权限失败: {e}")
        return False


async def auto_delete_message(message: Message, delay: int = AUTO_DELETE_DELAY) -> None:
    """自动删除消息"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.debug(f"自动删除消息失败: {e}")


def format_player_rolls(player: PlayerRecord) -> str:
    """格式化玩家投掷记录"""
    if len(player.rolls) == 1:
        return f"{player.rolls[0]}"
    rolls_str = ", ".join(str(r) for r in player.rolls)
    return f"{rolls_str} → {player.min_roll}"


def escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符"""
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


def safe_mention(player: PlayerRecord) -> str:
    """生成安全的用户提及字符串（HTML格式）"""
    safe_name = player.first_name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
    return f'<a href="tg://user?id={player.user_id}">{safe_name}</a>'


async def end_game(client: Client, game_key: tuple, reason: str) -> None:
    """结束游戏并公布结果"""
    async with _games_lock:
        game = _active_games.pop(game_key, None)

    if not game:
        return

    game.is_active = False
    chat_id = game.chat_id
    thread_id = game.message_thread_id

    # 取消定时器
    if game.timer_task and not game.timer_task.done():
        game.timer_task.cancel()
        try:
            await game.timer_task
        except asyncio.CancelledError:
            pass

    # 检查荷官模式并获取迟到玩家
    dealer_config = await get_dealer_mode_config(chat_id)
    late_player_records = {}
    if dealer_config and dealer_config.enabled and dealer_config.late_players:
        # 将迟到玩家添加到游戏中
        for user_id_str, player_info in dealer_config.late_players.items():
            user_id = int(user_id_str)
            if user_id not in game.players:
                # 迟到玩家默认点数为 0（最小）
                late_player_records[user_id] = PlayerRecord(
                    user_id=user_id,
                    username=player_info.get("username"),
                    first_name=player_info["first_name"],
                    rolls=[0],  # 迟到玩家默认0点
                )

        # 清空迟到玩家列表（准备记录下一轮的迟到）
        await clear_late_players(chat_id)

    # 合并迟到玩家到游戏玩家中
    all_players = {**game.players, **late_player_records}
    player_count = len(all_players)

    try:
        if player_count == 0:
            await client.send_message(
                chat_id,
                "🎲 <b>游戏结束</b> 🎲\n\n"
                f"原因: {reason}\n\n"
                "😢 没有人参与游戏...",
                parse_mode=ParseMode.HTML,
                message_thread_id=thread_id,
            )
            logger.info(f"游戏结束 (chat_id={chat_id}, thread={thread_id}): 无人参与")
            return

        if player_count == 1:
            player = list(all_players.values())[0]
            await client.send_message(
                chat_id,
                "🎲 <b>游戏结束</b> 🎲\n\n"
                f"原因: {reason}\n"
                f"参与人数: {player_count}\n\n"
                f"⚠️ 只有一个人参与\n"
                f"参与者: {safe_mention(player)}",
                parse_mode=ParseMode.HTML,
                message_thread_id=thread_id,
            )
            logger.info(f"游戏结束 (chat_id={chat_id}, thread={thread_id}): 只有1人")
            return

        # 计算结果
        players_sorted = sorted(all_players.values(), key=lambda p: p.min_roll)
        loser = players_sorted[0]  # 最小点数 - 回答方
        winner = players_sorted[-1]  # 最大点数 - 提问方

        # 处理平局情况
        min_roll = loser.min_roll
        max_roll = winner.min_roll
        losers = [p for p in players_sorted if p.min_roll == min_roll]
        winners = [p for p in players_sorted if p.min_roll == max_roll]

        # 标记迟到玩家
        late_loser_mentions = []
        normal_loser_mentions = []
        for loser_player in losers:
            mention = safe_mention(loser_player)
            if loser_player.user_id in late_player_records:
                late_loser_mentions.append(f"{mention} ⏰")
            else:
                normal_loser_mentions.append(mention)

        # 构建提问方和回答方文本
        if len(winners) > 1:
            winner_text = "、".join(safe_mention(w) for w in winners)
            winner_section = f"👑 <b>提问方</b> (点数 {max_roll}, 平局):\n{winner_text}"
            has_single_winner = False
        else:
            winner_section = f"👑 <b>提问方</b> (点数 {max_roll}):\n{safe_mention(winner)}"
            has_single_winner = True

        # 构建回答方文本（区分迟到玩家）
        all_loser_mentions = normal_loser_mentions + late_loser_mentions
        if len(losers) > 1:
            loser_text = "、".join(all_loser_mentions)
            loser_section = f"🎯 <b>回答方</b> (点数 {min_roll}, 平局):\n{loser_text}"
        else:
            loser_text = all_loser_mentions[0]
            loser_section = f"🎯 <b>回答方</b> (点数 {min_roll}):\n{loser_text}"

        # 添加迟到提示
        late_hint = ""
        if late_loser_mentions:
            late_hint = "\n\n⏰ 标记 <b>⏰</b> 的玩家为迟到者（在游戏间隙投掷骰子）"

        result_message = (
            "🎲 <b>游戏结束</b> 🎲\n\n"
            f"{winner_section}\n\n"
            f"{loser_section}"
            f"{late_hint}"
        )

        # 如果只有一个提问方，生成提问按钮
        keyboard = None
        if has_single_winner:
            # 获取 bot 用户名
            bot_me = await client.get_me()
            bot_username = bot_me.username

            # 保存待提问数据
            async with _questions_lock:
                _pending_questions[winner.user_id] = PendingQuestion(
                    chat_id=chat_id,
                    thread_id=thread_id,
                    winner_id=winner.user_id,
                    loser_ids=[l.user_id for l in losers],
                    winner_mentions=[safe_mention(winner)],
                    loser_mentions=[safe_mention(l) for l in losers],
                    timestamp=time.time(),
                )

            # 生成深度链接按钮
            deep_link = f"https://t.me/{bot_username}?start=ask_{winner.user_id}_{int(time.time())}"

            # 构建按钮布局
            buttons = [
                [InlineKeyboardButton("💬 开始提问", url=deep_link)],
            ]

            # 检查是否有历史提问，如果有则添加参考按钮
            question_count = await get_question_count(chat_id)
            if question_count > 0:
                buttons.append([
                    InlineKeyboardButton("🎲 随机提问", callback_data=f"random_q_{chat_id}"),
                    InlineKeyboardButton("📚 提问参考", callback_data=f"top_q_{chat_id}"),
                ])

            keyboard = InlineKeyboardMarkup(buttons)

        await client.send_message(
            chat_id,
            result_message,
            parse_mode=ParseMode.HTML,
            message_thread_id=thread_id,
            reply_markup=keyboard,
        )

        logger.info(
            f"游戏结束 (chat_id={chat_id}, thread={thread_id}): "
            f"提问方={winner.first_name}({max_roll}), "
            f"回答方={loser.first_name}({min_roll}), "
            f"参与人数={player_count}"
        )
    except Exception as e:
        logger.exception(f"发送游戏结果消息失败 (chat_id={chat_id}, thread={thread_id}): {e}")
        # 尝试发送纯文本消息
        try:
            await client.send_message(
                chat_id,
                f"🎲 游戏结束 🎲\n\n(消息格式化失败，请查看日志)",
                message_thread_id=thread_id,
            )
        except Exception as e2:
            logger.error(f"发送纯文本消息也失败 (chat_id={chat_id}, thread={thread_id}): {e2}")


async def game_timeout_handler(client: Client, game_key: tuple) -> None:
    """游戏超时处理"""
    try:
        async with _games_lock:
            game = _active_games.get(game_key)
            if not game or not game.is_active:
                return

        await end_game(client, game_key, "⏰ 时间到")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception(f"游戏超时处理出错: {e}")


# ==================== 命令处理 ====================


@Client.on_message(filters.command("dice") & filters.group, group=0)
async def start_dice_command(client: Client, message: Message):
    """处理 /dice 发起游戏指令"""
    # 初始化定时任务（仅第一次）
    asyncio.create_task(_init_scheduler_once(client))

    chat_id = message.chat.id
    thread_id = message.message_thread_id  # 获取话题 ID
    game_key = get_game_key(chat_id, thread_id)
    user = message.from_user

    if not user:
        return

    # 检查是否已有游戏在进行
    async with _games_lock:
        if game_key in _active_games:
            warning_msg = await message.reply_text(
                "⚠️ 当前已有游戏在进行中\n\n"
                "请等待游戏结束或使用 /dice_end 停止当前游戏",
            )
            asyncio.create_task(auto_delete_message(warning_msg))
            return

    # 解析参数（只支持时间参数）
    parts = message.text.split()
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    try:
        if len(parts) >= 2:
            timeout_seconds = int(parts[1])
            if not MIN_TIMEOUT <= timeout_seconds <= MAX_TIMEOUT:
                warning_msg = await message.reply_text(
                    f"⚠️ 时间必须在 {MIN_TIMEOUT}-{MAX_TIMEOUT} 秒之间",
                )
                asyncio.create_task(auto_delete_message(warning_msg))
                return
    except ValueError:
        await message.reply_text(
            "🎲 <b>真心话大冒险</b>\n\n"
            "<b>用法:</b> <code>/dice [秒数]</code>\n"
            "<b>示例:</b>\n"
            "• <code>/dice</code> - 60秒\n"
            "• <code>/dice 90</code> - 90秒\n"
            "• <code>/dice 120</code> - 120秒",
            parse_mode=ParseMode.HTML,
        )
        return

    # 获取发起人提及字符串 (HTML格式)
    safe_first_name = user.first_name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
    initiator_mention = f'<a href="tg://user?id={user.id}">{safe_first_name}</a>'

    # 创建游戏会话
    game = GameSession(
        chat_id=chat_id,
        initiator_id=user.id,
        initiator_mention=initiator_mention,
        timeout_seconds=timeout_seconds,
        start_time=time.time(),
        message_thread_id=thread_id,
    )

    async with _games_lock:
        _active_games[game_key] = game

    # 发送开始消息
    await message.reply_text(
        "🎲 <b>真心话大冒险</b> 🎲\n\n"
        f"发起人: {initiator_mention}\n"
        f"时间限制: {timeout_seconds} 秒\n\n"
        "📢 请在群内发送骰子参与游戏！\n"
        "💡 提示: 点击输入框旁的骰子图标发送\n\n"
        "<b>规则:</b>\n"
        "• 最大点数者 → 提问方\n"
        "• 最小点数者 → 回答方\n"
        "• 同一玩家多次投掷取最小值",
        parse_mode=ParseMode.HTML,
    )

    # 启动超时定时器
    game.timer_task = asyncio.create_task(
        asyncio.sleep(timeout_seconds)
    )

    # 创建超时回调任务
    async def timeout_callback():
        try:
            await game.timer_task
            await game_timeout_handler(client, game_key)
        except asyncio.CancelledError:
            pass

    asyncio.create_task(timeout_callback())

    logger.info(
        f"游戏开始 (chat_id={chat_id}, thread={thread_id}): "
        f"发起人={user.first_name}, "
        f"超时={timeout_seconds}s"
    )


@Client.on_message(filters.command("dice_end") & filters.group, group=0)
async def stop_dice_command(client: Client, message: Message):
    """处理 /dice_end 停止游戏指令"""
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    game_key = get_game_key(chat_id, thread_id)
    user = message.from_user

    if not user:
        return

    async with _games_lock:
        game = _active_games.get(game_key)

    if not game:
        warning_msg = await message.reply_text(
            "⚠️ 当前没有进行中的游戏",
        )
        asyncio.create_task(auto_delete_message(warning_msg))
        return

    # 检查权限：管理员或发起人
    is_admin = await is_chat_admin(client, chat_id, user.id)
    is_initiator = user.id == game.initiator_id

    if not (is_admin or is_initiator):
        warning_msg = await message.reply_text(
            "⚠️ 只有管理员或游戏发起人才能停止游戏",
        )
        asyncio.create_task(auto_delete_message(warning_msg))
        return

    await end_game(client, game_key, "🛑 手动停止")

    logger.info(f"游戏被手动停止 (chat_id={chat_id}, thread={thread_id}): 操作者={user.first_name}")


@Client.on_message(filters.command("dice_status") & filters.group, group=0)
async def dice_status_command(client: Client, message: Message):
    """处理 /dice_status 查看游戏状态指令"""
    chat_id = message.chat.id
    thread_id = message.message_thread_id
    game_key = get_game_key(chat_id, thread_id)

    async with _games_lock:
        game = _active_games.get(game_key)

    if not game:
        await message.reply_text(
            "❌ 当前没有进行中的游戏\n\n"
            "使用 <code>/dice</code> 发起新游戏",
            parse_mode=ParseMode.HTML,
        )
        return

    # 计算剩余时间
    elapsed = time.time() - game.start_time
    remaining = max(0, game.timeout_seconds - elapsed)

    # 构建玩家列表
    if game.players:
        player_lines = []
        for player in game.players.values():
            player_lines.append(f"• {safe_mention(player)}: {format_player_rolls(player)}")
        players_text = "\n".join(player_lines)
    else:
        players_text = "暂无玩家参与"

    await message.reply_text(
        "🎲 <b>游戏状态</b> 🎲\n\n"
        f"发起人: {game.initiator_mention}\n"
        f"当前人数: {len(game.players)} 人\n"
        f"剩余时间: {int(remaining)} 秒\n\n"
        f"<b>参与玩家:</b>\n{players_text}",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(filters.command("dealer") & filters.group, group=0)
async def dealer_mode_command(client: Client, message: Message):
    """处理 /dealer 荷官模式管理指令"""
    chat_id = message.chat.id
    user = message.from_user

    if not user:
        return

    # 检查管理员权限
    is_admin = await is_chat_admin(client, chat_id, user.id)
    if not is_admin:
        warning_msg = await message.reply_text(
            "⚠️ 只有管理员才能管理荷官模式",
        )
        asyncio.create_task(auto_delete_message(warning_msg))
        return

    # 解析参数
    parts = message.text.split()

    if len(parts) < 2:
        # 显示帮助
        await message.reply_text(
            "🎰 <b>荷官模式管理</b>\n\n"
            "<b>用法:</b>\n"
            "• <code>/dealer on</code> - 开启荷官模式\n"
            "• <code>/dealer off</code> - 关闭荷官模式\n"
            "• <code>/dealer status</code> - 查看状态\n"
            "• <code>/dealer config HH:MM HH:MM</code> - 设置定时（如 20:00 22:00）\n\n"
            "<b>荷官模式说明:</b>\n"
            "开启后，在游戏间隙投掷骰子的玩家将被记录为\"迟到者\"，\n"
            "在下一轮游戏结束时自动加入回答方。",
            parse_mode=ParseMode.HTML,
        )
        return

    action = parts[1].lower()

    if action == "on":
        # 开启荷官模式
        await upsert_dealer_mode_config(
            chat_id=chat_id,
            enabled=True,
        )
        await message.reply_text(
            "✅ 荷官模式已开启\n\n"
            "现在游戏间隙投掷骰子的玩家将被记录为迟到者。",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"荷官模式已开启 (chat_id={chat_id}): 操作者={user.first_name}")

    elif action == "off":
        # 关闭荷官模式
        await upsert_dealer_mode_config(
            chat_id=chat_id,
            enabled=False,
        )
        # 清空迟到记录
        await clear_late_players(chat_id)
        await message.reply_text(
            "✅ 荷官模式已关闭\n\n"
            "迟到记录已清空。",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"荷官模式已关闭 (chat_id={chat_id}): 操作者={user.first_name}")

    elif action == "status":
        # 查看状态
        config = await get_dealer_mode_config(chat_id)
        if not config:
            await message.reply_text(
                "🎰 <b>荷官模式状态</b>\n\n"
                "状态: ❌ 未启用\n"
                "定时: 未设置",
                parse_mode=ParseMode.HTML,
            )
            return

        status_emoji = "✅" if config.enabled else "❌"
        late_count = len(config.late_players)
        late_info = f"当前迟到人数: {late_count} 人" if late_count > 0 else "暂无迟到者"

        await message.reply_text(
            f"🎰 <b>荷官模式状态</b>\n\n"
            f"状态: {status_emoji} {'已启用' if config.enabled else '未启用'}\n"
            f"定时: {config.start_time} - {config.end_time}\n"
            f"{late_info}",
            parse_mode=ParseMode.HTML,
        )

    elif action == "config":
        # 配置定时
        if len(parts) < 4:
            await message.reply_text(
                "⚠️ 格式错误\n\n"
                "用法: <code>/dealer config HH:MM HH:MM</code>\n"
                "示例: <code>/dealer config 20:00 22:00</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        start_time = parts[2]
        end_time = parts[3]

        # 验证时间格式
        import re
        time_pattern = r'^([01]\d|2[0-3]):([0-5]\d)$'
        if not re.match(time_pattern, start_time) or not re.match(time_pattern, end_time):
            await message.reply_text(
                "⚠️ 时间格式错误\n\n"
                "请使用 HH:MM 格式（如 20:00）",
                parse_mode=ParseMode.HTML,
            )
            return

        await upsert_dealer_mode_config(
            chat_id=chat_id,
            start_time=start_time,
            end_time=end_time,
        )
        await message.reply_text(
            f"✅ 定时配置已更新\n\n"
            f"每天 {start_time} - {end_time} 自动启用荷官模式\n"
            f"（定时功能将在下次启动时生效）",
            parse_mode=ParseMode.HTML,
        )
        logger.info(
            f"荷官模式定时已配置 (chat_id={chat_id}): "
            f"{start_time}-{end_time}, 操作者={user.first_name}"
        )

    else:
        await message.reply_text(
            "⚠️ 未知的操作\n\n"
            "请使用 <code>/dealer</code> 查看帮助",
            parse_mode=ParseMode.HTML,
        )


@Client.on_message(filters.command("dice_stats") & filters.group, group=0)
async def question_stats_command(client: Client, message: Message):
    """处理 /dice_stats 查看提问统计指令"""
    chat_id = message.chat.id

    try:
        # 获取提问总数
        total_count = await get_question_count(chat_id)

        if total_count == 0:
            await message.reply_text(
                "📚 <b>提问统计</b>\n\n"
                "暂无提问记录。\n\n"
                "提示: 每次游戏的提问都会自动保存到数据库。",
                parse_mode=ParseMode.HTML,
            )
            return

        await message.reply_text(
            f"📚 <b>提问统计</b>\n\n"
            f"📊 历史提问总数: <b>{total_count}</b> 条\n\n"
            f"💡 这些提问可以作为游戏参考！",
            parse_mode=ParseMode.HTML,
        )

        logger.info(f"查看提问统计: chat_id={chat_id}, 总数={total_count}")

    except Exception as e:
        logger.exception(f"查看提问统计失败: {e}")
        await message.reply_text(
            "❌ 查询失败，请稍后重试。",
            parse_mode=ParseMode.HTML,
        )


# ==================== 骰子监听 ====================


@Client.on_message(filters.dice & filters.group, group=1)
async def dice_message_handler(client: Client, message: Message):
    """监听群组内的骰子消息"""
    # 只处理 🎲 骰子
    if not message.dice or message.dice.emoji != "🎲":
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    game_key = get_game_key(chat_id, thread_id)
    user = message.from_user

    if not user:
        return

    async with _games_lock:
        game = _active_games.get(game_key)

    if not game or not game.is_active:
        # 没有游戏进行中，检查是否需要记录迟到
        dealer_config = await get_dealer_mode_config(chat_id)
        if dealer_config and dealer_config.enabled:
            # 记录迟到玩家
            await add_late_player(
                chat_id=chat_id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
            )
            logger.info(
                f"记录迟到玩家 (chat_id={chat_id}, thread={thread_id}): "
                f"{user.first_name}(id={user.id})"
            )
        return

    dice_value = message.dice.value

    # 记录玩家投掷
    async with _games_lock:
        game = _active_games.get(game_key)
        if not game or not game.is_active:
            return

        if user.id in game.players:
            # 老玩家，追加投掷记录
            game.players[user.id].rolls.append(dice_value)
            logger.debug(
                f"玩家追加投掷 (chat_id={chat_id}, thread={thread_id}): "
                f"{user.first_name}(id={user.id}) 投出 {dice_value}"
            )
        else:
            # 新玩家
            game.players[user.id] = PlayerRecord(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                rolls=[dice_value],
            )
            logger.info(
                f"新玩家加入 (chat_id={chat_id}, thread={thread_id}): "
                f"{user.first_name}(id={user.id}) 投出 {dice_value}, "
                f"当前人数={len(game.players)}"
            )

# ==================== 提问功能 ====================


# 用户等待提问状态 - 键为 user_id
_waiting_for_question: Dict[int, PendingQuestion] = {}


@Client.on_message(filters.command("start") & filters.private, group=0)
async def start_command_handler(client: Client, message: Message):
    """处理 /start 命令（深度链接）"""
    user = message.from_user
    if not user:
        return

    # 解析参数
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        # 普通 /start 命令
        await message.reply_text(
            "👋 你好！我是真心话大冒险机器人。\n\n"
            "请在群组中使用 /dice 发起游戏。"
        )
        return

    param = parts[1]
    
    # 处理提问深度链接
    if param.startswith("ask_"):
        try:
            parts = param.split("_")
            winner_id = int(parts[1])
            
            # 验证是否是提问方
            if user.id != winner_id:
                await message.reply_text(
                    "⚠️ 你不是提问方，无法提问。"
                )
                return
            
            # 检查是否有待提问数据
            async with _questions_lock:
                pending = _pending_questions.get(winner_id)
            
            if not pending:
                await message.reply_text(
                    "⚠️ 提问已过期或无效。"
                )
                return
            
            # 检查是否过期（24小时）
            if time.time() - pending.timestamp > 86400:
                async with _questions_lock:
                    _pending_questions.pop(winner_id, None)
                await message.reply_text(
                    "⚠️ 提问已过期（超过24小时）。"
                )
                return
            
            # 标记用户正在等待输入提问
            _waiting_for_question[user.id] = pending
            
            # 提示用户输入提问
            loser_names = "、".join([m.replace('<a href="tg://user?id=', '').replace('">', ' ').replace('</a>', '') for m in pending.loser_mentions])
            
            await message.reply_text(
                "💬 <b>请输入你的提问</b>\n\n"
                f"回答方: {', '.join(pending.loser_mentions)}\n\n"
                "请直接发送你的提问内容（文本、图片、视频等）",
                parse_mode=ParseMode.HTML,
            )
            
            logger.info(f"用户 {user.first_name}(id={user.id}) 开始提问")
            
        except (ValueError, IndexError) as e:
            logger.error(f"解析深度链接失败: {param}, 错误: {e}")
            await message.reply_text(
                "⚠️ 链接格式错误。"
            )


@Client.on_message(filters.private & ~filters.command(["start", "dice_end", "dice_status", "dealer"]), group=2)
async def private_question_handler(client: Client, message: Message):
    """处理私聊提问消息"""
    user = message.from_user
    if not user:
        return

    # 检查用户是否在等待提问状态
    pending = _waiting_for_question.get(user.id)
    if not pending:
        return

    # 移除等待状态
    _waiting_for_question.pop(user.id, None)

    # 移除待提问数据
    async with _questions_lock:
        _pending_questions.pop(user.id, None)

    try:
        # 构建提问消息
        question_text = (
            "💬 <b>提问方的问题：</b>\n\n"
            f"提问方: {pending.winner_mentions[0]}\n"
            f"回答方: {', '.join(pending.loser_mentions)}\n\n"
        )

        # 如果是文本消息，直接附加
        if message.text:
            question_text += message.text
            await client.send_message(
                pending.chat_id,
                question_text,
                parse_mode=ParseMode.HTML,
                message_thread_id=pending.thread_id,
            )
        elif message.caption:
            # 如果是带标题的媒体消息
            question_text += message.caption
            # 转发媒体
            if message.photo:
                await client.send_photo(
                    pending.chat_id,
                    message.photo.file_id,
                    caption=question_text,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=pending.thread_id,
                )
            elif message.video:
                await client.send_video(
                    pending.chat_id,
                    message.video.file_id,
                    caption=question_text,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=pending.thread_id,
                )
            elif message.document:
                await client.send_document(
                    pending.chat_id,
                    message.document.file_id,
                    caption=question_text,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=pending.thread_id,
                )
        else:
            # 纯媒体消息（无标题）
            # 先发送说明文本
            await client.send_message(
                pending.chat_id,
                question_text,
                parse_mode=ParseMode.HTML,
                message_thread_id=pending.thread_id,
            )
            # 再转发媒体
            if message.photo:
                await client.send_photo(
                    pending.chat_id,
                    message.photo.file_id,
                    message_thread_id=pending.thread_id,
                )
            elif message.video:
                await client.send_video(
                    pending.chat_id,
                    message.video.file_id,
                    message_thread_id=pending.thread_id,
                )
            elif message.document:
                await client.send_document(
                    pending.chat_id,
                    message.document.file_id,
                    message_thread_id=pending.thread_id,
                )

        # 生成返回群聊按钮
        try:
            chat = await client.get_chat(pending.chat_id)

            # 构建返回链接
            if chat.username:
                # 公开群
                if pending.thread_id:
                    # 话题群
                    back_url = f"https://t.me/{chat.username}/{pending.thread_id}"
                else:
                    back_url = f"https://t.me/{chat.username}"
            else:
                # 私有群
                # 使用 t.me/c/ 格式（需要去掉负号和前缀100）
                chat_id_str = str(pending.chat_id)
                if chat_id_str.startswith("-100"):
                    chat_id_numeric = chat_id_str[4:]  # 去掉 -100
                else:
                    chat_id_numeric = chat_id_str.lstrip("-")

                if pending.thread_id:
                    back_url = f"https://t.me/c/{chat_id_numeric}/{pending.thread_id}"
                else:
                    back_url = f"https://t.me/c/{chat_id_numeric}/1"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回群聊", url=back_url)]
            ])

            await message.reply_text(
                "✅ 提问已发送到群组！",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning(f"生成返回按钮失败: {e}")
            # 如果失败，至少发送简单确认
            await message.reply_text(
                "✅ 提问已发送到群组！"
            )

        logger.info(
            f"提问已转发: user={user.first_name}(id={user.id}), "
            f"chat_id={pending.chat_id}, thread={pending.thread_id}"
        )

        # 保存提问到数据库（异步执行，不阻塞用户体验）
        asyncio.create_task(_save_question_reference(pending, message))

    except Exception as e:
        logger.exception(f"转发提问失败: {e}")
        await message.reply_text(
            "❌ 发送提问失败，请稍后重试。"
        )


async def _save_question_reference(pending: PendingQuestion, message: Message):
    """保存提问到参考数据库（带语义去重）"""
    try:
        from kmua.services.embedding import get_embedding_service

        # 提取提问文本
        question_text = message.text or message.caption or "[媒体消息]"

        # 如果是纯媒体消息，不保存（因为没有文本）
        if question_text == "[媒体消息]":
            logger.debug("纯媒体消息，跳过保存")
            return

        # 获取 embedding 服务
        embedding_service = get_embedding_service()

        # 获取 embedding 和哈希
        embedding = await embedding_service.get_embedding(question_text)
        embedding_hash = None

        if embedding:
            embedding_hash = embedding_service.compute_embedding_hash(embedding)
            logger.debug(f"提问 embedding hash: {embedding_hash}")
        else:
            logger.warning("无法获取 embedding，将不进行语义去重")

        # 保存到数据库
        await add_question_reference(
            chat_id=pending.chat_id,
            question_text=question_text,
            winner_id=pending.winner_id,
            loser_ids=pending.loser_ids,
            embedding_hash=embedding_hash,
        )

        logger.info(
            f"✅ 提问已保存到数据库: chat_id={pending.chat_id}, "
            f"question='{question_text[:50]}...'"
        )

    except Exception as e:
        logger.exception(f"保存提问到数据库失败: {e}")


# ==================== 回调查询处理 ====================


@Client.on_callback_query(filters.regex(r"^random_q_"))
async def random_question_callback(client: Client, callback_query: CallbackQuery):
    """处理随机提问按钮"""
    try:
        # 解析 chat_id
        data = callback_query.data
        chat_id = int(data.split("_")[2])

        # 获取随机提问
        question = await get_random_question(chat_id)

        if not question:
            await callback_query.answer(
                "❌ 暂无历史提问",
                show_alert=True,
            )
            return

        # 增加使用次数
        await increment_question_used_count(question.id)

        # 发送提问内容
        await callback_query.answer("🎲 已抽取随机提问")

        await client.send_message(
            callback_query.message.chat.id,
            f"🎲 <b>随机提问参考</b>\n\n"
            f"{question.question_text}\n\n"
            f"<i>💡 来自历史记录（已被参考 {question.used_count + 1} 次）</i>",
            parse_mode=ParseMode.HTML,
            message_thread_id=callback_query.message.message_thread_id,
        )

        logger.info(
            f"随机提问被查看: question_id={question.id}, "
            f"user={callback_query.from_user.first_name}(id={callback_query.from_user.id})"
        )

    except Exception as e:
        logger.exception(f"处理随机提问回调失败: {e}")
        await callback_query.answer(
            "❌ 操作失败",
            show_alert=True,
        )


@Client.on_callback_query(filters.regex(r"^top_q_"))
async def top_questions_callback(client: Client, callback_query: CallbackQuery):
    """处理提问参考按钮"""
    try:
        # 解析 chat_id
        data = callback_query.data
        chat_id = int(data.split("_")[2])

        # 获取热门提问（前5个）
        top_questions = await get_top_questions(chat_id, limit=5)

        if not top_questions:
            await callback_query.answer(
                "❌ 暂无历史提问",
                show_alert=True,
            )
            return

        # 构建提问列表
        question_lines = []
        for i, q in enumerate(top_questions, 1):
            # 截取提问内容（最多50字符）
            text_preview = q.question_text[:50]
            if len(q.question_text) > 50:
                text_preview += "..."

            question_lines.append(
                f"{i}. {text_preview}\n"
                f"   <i>被参考 {q.used_count} 次</i>"
            )

        questions_text = "\n\n".join(question_lines)

        await callback_query.answer("📚 已获取热门提问")

        await client.send_message(
            callback_query.message.chat.id,
            f"📚 <b>热门提问参考</b>\n\n"
            f"{questions_text}\n\n"
            f"<i>💡 这些是使用最多的提问</i>",
            parse_mode=ParseMode.HTML,
            message_thread_id=callback_query.message.message_thread_id,
        )

        logger.info(
            f"热门提问被查看: chat_id={chat_id}, "
            f"user={callback_query.from_user.first_name}(id={callback_query.from_user.id})"
        )

    except Exception as e:
        logger.exception(f"处理提问参考回调失败: {e}")
        await callback_query.answer(
            "❌ 操作失败",
            show_alert=True,
        )
