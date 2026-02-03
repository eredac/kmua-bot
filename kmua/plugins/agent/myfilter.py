import pyrogram
from pyrogram import filters
from pyrogram.client import Client

# 导入dice_game的等待提问状态（延迟导入以避免循环依赖）
_dice_game_waiting_for_question = None


def _get_dice_game_waiting_state():
    """获取dice_game模块的等待提问状态字典"""
    global _dice_game_waiting_for_question
    if _dice_game_waiting_for_question is None:
        try:
            from kmua.plugins import dice_game
            _dice_game_waiting_for_question = dice_game._waiting_for_question
        except (ImportError, AttributeError):
            _dice_game_waiting_for_question = {}
    return _dice_game_waiting_for_question


async def base_filter_func(_, __, message: pyrogram.types.Message) -> bool:
    if not message:
        return False
    text = message.text or message.caption
    if not text or len(text.strip()) == 0:
        return False
    if (
        message.entities is not None
        and message.entities[0].type == pyrogram.enums.MessageEntityType.BOT_COMMAND
    ):
        return False
    if text.startswith("/") or text.startswith("\\"):
        return False

    # 在私聊场景下，检查用户是否在等待输入dice_game提问
    if message.chat and message.chat.type == pyrogram.enums.ChatType.PRIVATE:
        if message.from_user:
            waiting_state = _get_dice_game_waiting_state()
            if message.from_user.id in waiting_state:
                return False  # 用户正在等待输入提问，不触发LLM

    return True


def _is_dice_game_message(text: str) -> bool:
    """检测消息是否来自dice_game模块"""
    if not text:
        return False

    # dice_game 消息的特征关键词
    dice_game_keywords = [
        "🎲",
        "真心话大冒险",
        "游戏开始",
        "游戏结束",
        "提问方",
        "回答方",
        "发起人",
        "时间限制",
        "参与人数",
        "剩余时间",
        "荷官模式",
        "提问统计",
        "提问已发送到群组",
        "随机提问参考",
        "热门提问参考",
        "提问描述",
        "正在搜索",
        "迟到者",
        "最大点数者",
        "最小点数者",
    ]

    # 检查是否包含任何特征关键词
    return any(keyword in text for keyword in dice_game_keywords)


async def reply_me_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not message.reply_to_message:
        return False
    if not message.reply_to_message.from_user:
        return False
    if not client.me:
        return False
    if message.reply_to_message.from_user.username != client.me.username:
        return False

    # 检查被回复的消息是否来自 dice_game 模块
    replied_text = message.reply_to_message.text or message.reply_to_message.caption
    if _is_dice_game_message(replied_text):
        return False  # 如果是 dice_game 消息，不触发 LLM 回复

    return True


async def mention_me_filter_func(
    _, client: Client, message: pyrogram.types.Message
) -> bool:
    if not message.text:
        return False
    if not client.me:
        return False
    username = client.me.username
    if not username:
        return False
    if username in message.text:
        # 检查消息是否在回复 dice_game 的消息
        if message.reply_to_message:
            replied_text = message.reply_to_message.text or message.reply_to_message.caption
            if _is_dice_game_message(replied_text):
                return False  # 如果在回复 dice_game 消息时 @ bot，不触发 LLM 回复
        return True
    if message.caption and username in message.caption:
        # 检查 caption 场景
        if message.reply_to_message:
            replied_text = message.reply_to_message.text or message.reply_to_message.caption
            if _is_dice_game_message(replied_text):
                return False
        return True
    return False


base_filter = filters.create(base_filter_func)
reply_me_filter = filters.create(reply_me_filter_func)
mention_me_filter = filters.create(mention_me_filter_func)
