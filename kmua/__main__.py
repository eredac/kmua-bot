import uvloop

uvloop.install()

import hashlib
import json

import pyrogram
from pyrogram.client import Client
from pyrogram.sync import idle
from pyrogram.types import BotCommand

from kmua import common, database, i18n
from kmua.bot import jobs
from kmua.bot.client import client
from kmua.config import app_config
from kmua.database import db
from kmua.health import start_health_server, stop_health_server
from kmua.logger import logger
from kmua.plugins.agent import sticker_vec
from kmua.plugins.agent.tools import init_code_repository


def _get_commands_hash(commands_dict: dict[str, list[BotCommand]]) -> str:
    """
    计算命令列表的哈希值，用于检测命令是否发生变化
    """
    # 将命令转换为可序列化的格式
    serializable = {}
    for scope, commands in commands_dict.items():
        serializable[scope] = [
            {"command": cmd.command, "description": cmd.description} for cmd in commands
        ]
    # 计算 hash
    content = json.dumps(serializable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()


def _load_cached_hash() -> str | None:
    """
    从文件加载缓存的命令哈希值
    """
    try:
        commands_hash_file = app_config.workdir / ".commands_hash"
        if commands_hash_file.exists():
            return commands_hash_file.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning(f"Failed to load cached commands hash: {e}")
    return None


def _save_commands_hash(commands_hash: str) -> None:
    """
    保存命令哈希值到文件
    """
    try:
        commands_hash_file = app_config.workdir / ".commands_hash"
        commands_hash_file.parent.mkdir(parents=True, exist_ok=True)
        commands_hash_file.write_text(commands_hash, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save commands hash: {e}")


async def _should_update_commands(commands_dict: dict[str, list[BotCommand]]) -> bool:
    """
    检查是否需要更新命令
    """
    current_hash = _get_commands_hash(commands_dict)
    cached_hash = _load_cached_hash()

    if cached_hash is None:
        logger.debug("No cached commands hash found, will set commands")
        return True

    if current_hash != cached_hash:
        logger.debug("Commands changed, will update commands")
        return True

    logger.debug("Commands unchanged, skipping command setup")
    return False


@client.on_start()
async def init_bot(client: Client = client):
    # Initialize code repository for agent self-awareness
    if app_config.agent_code_awareness:
        try:
            await init_code_repository()
            logger.info("Code repository initialized for agent self-awareness")
        except Exception as e:
            logger.error(f"Failed to initialize code repository: {e}")

    logger.info(i18n.t("log.initing", locale=app_config.lang))
    if not app_config.avatar_cache_dir.exists():
        app_config.avatar_cache_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(i18n.t("log.getting_me", locale=app_config.lang))
    me = await client.get_me()
    db_me = await database.upsert_user(me)
    logger.info(
        i18n.t("log.welcome", locale=app_config.lang).format(
            name=db_me.full_name,
            username=db_me.username,
            id=db_me.id,
        )
    )

    # 准备所有命令列表
    common_commands = [
        BotCommand(
            "start",
            i18n.t("bot.cmd.start", locale=app_config.lang),
        ),
        BotCommand("help", i18n.t("bot.cmd.help", locale=app_config.lang)),
        BotCommand("setu", i18n.t("bot.cmd.setu", locale=app_config.lang)),
        BotCommand(
            "throwbottle", i18n.t("bot.cmd.throwbottle", locale=app_config.lang)
        ),
        BotCommand("pickbottle", i18n.t("bot.cmd.pickbottle", locale=app_config.lang)),
        BotCommand("forget", i18n.t("bot.cmd.forget", locale=app_config.lang)),
        BotCommand("id", i18n.t("bot.cmd.id", locale=app_config.lang)),
        BotCommand("ip", i18n.t("bot.cmd.ip", locale=app_config.lang)),
        BotCommand("f5avatar", i18n.t("bot.cmd.f5avatar", locale=app_config.lang)),
    ]
    group_common_commands = [
        BotCommand("waifu", i18n.t("bot.cmd.waifu", locale=app_config.lang)),
        BotCommand(
            "waifu_graph", i18n.t("bot.cmd.waifu_graph", locale=app_config.lang)
        ),
        BotCommand("q", i18n.t("bot.cmd.q", locale=app_config.lang)),
        BotCommand("d", i18n.t("bot.cmd.d", locale=app_config.lang)),
        BotCommand("qrand", i18n.t("bot.cmd.qrand", locale=app_config.lang)),
        BotCommand("qp", i18n.t("bot.cmd.qp", locale=app_config.lang)),
        BotCommand("t", i18n.t("bot.cmd.t", locale=app_config.lang)),
        BotCommand("td", i18n.t("bot.cmd.td", locale=app_config.lang)),
        BotCommand("wordcloud", i18n.t("bot.cmd.wordcloud", locale=app_config.lang)),
        BotCommand("muteme", i18n.t("bot.cmd.muteme", locale=app_config.lang)),
        # Image generation
        BotCommand("genimg", "生成图片 (AI)"),
        BotCommand("editimg", "编辑图片 (AI)"),
        BotCommand("multiedit", "批量编辑图片 (AI)"),
        BotCommand("imgmodel", "切换图片模型"),
        # Minecraft server status
        BotCommand("mcstatus", "群mc服务器连通情况"),
        # Dice game
        BotCommand("dice", "🎲 发起真心话大冒险游戏"),
        BotCommand("dice_end", "⏹ 停止当前游戏"),
        BotCommand("dice_status", "📊 查看游戏状态"),
        BotCommand("dealer", "🎰 荷官模式管理"),
        BotCommand("dice_stats", "📚 查看提问统计"),
        # Music search
        BotCommand("ms", "🎵 搜索音乐"),
        # Leaderboard & points
        BotCommand("rank", "🏆 查看积分排行榜"),
        BotCommand("settag", "🏷 购买/续费个人标签 (100积分/月)"),
        BotCommand("edittag", "✏️ 修改标签内容 (50积分，不重置有效期)"),
        BotCommand("mytag", "🏷 查看我的标签状态"),
        BotCommand("gifttag", "🎁 赠送标签给他人 (100积分/月)"),
        BotCommand("challenge", "⚔️ 发起积分猜拳挑战 (默认2%/上限5%)"),
        # Gacha card system
        BotCommand("gacha", "🃏 集换卡牌菜单"),
        BotCommand("trade", "🤝 发起卡牌交易 (回复目标用户)"),
    ]
    group_admin_commands = [
        BotCommand("sett", i18n.t("bot.cmd.sett", locale=app_config.lang)),
        BotCommand(
            "syncmembers", i18n.t("bot.cmd.syncmembers", locale=app_config.lang)
        ),
        BotCommand("botpromote", i18n.t("bot.cmd.botpromote", locale=app_config.lang)),
        BotCommand("botdemote", i18n.t("bot.cmd.botdemote", locale=app_config.lang)),
        BotCommand("config", i18n.t("bot.cmd.config", locale=app_config.lang)),
        BotCommand("greet", i18n.t("bot.cmd.greet", locale=app_config.lang)),
        BotCommand("gachaban", "🚫 卡牌系统黑名单管理 (仅owner)"),
    ]
    private_commands = [
        BotCommand("buygift", i18n.t("bot.cmd.buygift", locale=app_config.lang)),
        BotCommand("gift", i18n.t("bot.cmd.gift", locale=app_config.lang)),
    ]
    owner_commands = [
        BotCommand(
            "randmyavatar", i18n.t("bot.cmd.randmyavatar", locale=app_config.lang)
        ),
        BotCommand("reload", i18n.t("bot.cmd.reload", locale=app_config.lang)),
    ]

    # 构建命令字典用于检查
    commands_dict = {
        "all_group_chats": common_commands + group_common_commands,
        "all_chat_administrators": common_commands
        + group_common_commands
        + group_admin_commands,
        "all_private_chats": common_commands + private_commands,
    }
    # 为每个 owner 添加命令
    for owner_id in app_config.owners:
        commands_dict[f"chat_{owner_id}"] = (
            common_commands + private_commands + owner_commands
        )

    # 检查是否需要更新命令
    if await _should_update_commands(commands_dict):
        logger.debug(i18n.t("log.setting_commands", locale=app_config.lang))
        await client.delete_bot_commands()
        await client.set_bot_commands(
            common_commands + group_common_commands,
            scope=pyrogram.types.BotCommandScopeAllGroupChats(),
        )
        await client.set_bot_commands(
            common_commands + group_common_commands + group_admin_commands,
            scope=pyrogram.types.BotCommandScopeAllChatAdministrators(),
        )
        await client.set_bot_commands(
            common_commands + private_commands,
            scope=pyrogram.types.BotCommandScopeAllPrivateChats(),
        )
        # 为每个 owner 注册 owner 专属命令
        for owner_id in app_config.owners:
            await client.set_bot_commands(
                common_commands + private_commands + owner_commands,
                scope=pyrogram.types.BotCommandScopeChat(owner_id),
            )
        # 保存命令哈希值
        current_hash = _get_commands_hash(commands_dict)
        _save_commands_hash(current_hash)
        logger.debug("Bot commands set and cached")

    common.jobqueue.add_daily_job("cleanup", jobs.cleanup, hour=4)
    common.jobqueue.add_daily_job("tag_expiry_check", jobs.check_tag_expiry, hour=4)

    if app_config.agent_sticker_memory:
        await sticker_vec.init()
        logger.debug("Sticker vector DB initialized")

    # 添加定时更换 bot 头像任务
    if app_config.avatar_change_enabled:
        logger.info(
            i18n.t("log.avatar_change_enabled", locale=app_config.lang).format(
                interval=app_config.avatar_change_interval
            )
        )
        common.jobqueue.add_interval_job(
            "change_bot_avatar",
            jobs.change_bot_avatar,
            hours=app_config.avatar_change_interval,
        )


    common.jobqueue.start()

    # 恢复待提问状态（5分钟内）
    from kmua.plugins.dice_game import restore_pending_questions
    await restore_pending_questions()

    # 恢复超时挑战（处理 Bot 重启期间遗留的超时记录）
    from kmua.plugins.challenge import recover_challenges_on_startup
    await recover_challenges_on_startup(client)

    # 恢复待确认的标签赠送
    from kmua.plugins.tag import recover_gift_on_startup
    await recover_gift_on_startup(client)

    logger.success(i18n.t("log.inited", locale=app_config.lang))


@client.on_stop()
async def stop_bot(client: Client = client):
    logger.info(i18n.t("log.stopping", locale=app_config.lang))

    # Close code repository
    if app_config.agent_code_awareness:
        try:
            from kmua.plugins.agent.tools import close_code_repository

            await close_code_repository()
            logger.debug("Code repository closed")
        except Exception as e:
            logger.warning(f"Error closing code repository: {e}")

    common.jobqueue.shutdown()
    await db.close_db()
    logger.success(i18n.t("log.exit", locale=app_config.lang))


async def main():
    await db.init_db()

    # Start health check server
    health_runner = None
    if app_config.health_check_enabled:
        health_runner = await start_health_server(
            host=app_config.health_check_host,
            port=app_config.health_check_port,
        )

    await client.start()
    await idle()
    await client.stop()  # type: ignore

    # Stop health check server
    if health_runner:
        await stop_health_server(health_runner)


if __name__ == "__main__":
    if app_config.automigrate:
        db.migrate_db()
    client.loop.run_until_complete(main())
