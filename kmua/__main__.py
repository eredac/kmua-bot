from pyrogram.client import Client
from pyrogram.sync import idle
from pyrogram.types import BotCommand

from kmua import common, database, i18n
from kmua.bot import jobs
from kmua.bot.client import client
from kmua.config import app_config
from kmua.database import db
from kmua.logger import logger


@client.on_start()
async def init_bot(client: Client = client):
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
    logger.debug(i18n.t("log.setting_commands", locale=app_config.lang))
    await client.delete_bot_commands()
    await client.set_bot_commands(
        [
            BotCommand(
                "start",
                i18n.t("bot.cmd.start", locale=app_config.lang),
            ),
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
            BotCommand("sett", i18n.t("bot.cmd.sett", locale=app_config.lang)),
            BotCommand("id", i18n.t("bot.cmd.id", locale=app_config.lang)),
            BotCommand("ip", i18n.t("bot.cmd.ip", locale=app_config.lang)),
            BotCommand("setu", i18n.t("bot.cmd.setu", locale=app_config.lang)),
            BotCommand(
                "throwbottle", i18n.t("bot.cmd.throwbottle", locale=app_config.lang)
            ),
            BotCommand(
                "pickbottle", i18n.t("bot.cmd.pickbottle", locale=app_config.lang)
            ),
            BotCommand(
                "wordcloud", i18n.t("bot.cmd.wordcloud", locale=app_config.lang)
            ),
            BotCommand("config", i18n.t("bot.cmd.config", locale=app_config.lang)),
            BotCommand("greet", i18n.t("bot.cmd.greet", locale=app_config.lang)),
            BotCommand("help", i18n.t("bot.cmd.help", locale=app_config.lang)),
            # Image generation commands
            BotCommand("genimg", "生成图片 (AI)"),
            BotCommand("editimg", "编辑图片 (AI)"),
            BotCommand("multiedit", "批量编辑图片 (AI)"),
            BotCommand("imgmodel", "切换图片模型"),
            # Minecraft server status
            BotCommand("mcstatus", "群mc服务器连通情况"),
            # Dice game commands
            BotCommand("dice", "🎲 发起真心话大冒险游戏"),
            BotCommand("dice_end", "⏹ 停止当前游戏"),
            BotCommand("dice_status", "📊 查看游戏状态"),
            BotCommand("dealer", "🎰 荷官模式管理"),
            BotCommand("dice_stats", "📚 查看提问统计"),
            # Music search
            BotCommand("ms", "🎵 搜索音乐"),
            # Leaderboard
            BotCommand("rank", "🏆 查看积分排行榜"),
            # Tag
            BotCommand("settag", "🏷 购买/续费个人标签 (100积分/月)"),
            BotCommand("edittag", "✏️ 修改标签内容 (50积分，不重置有效期)"),
            BotCommand("mytag", "🏷 查看我的标签状态"),
        ]
    )
    common.jobqueue.add_daily_job("cleanup", jobs.cleanup, hour=4)
    common.jobqueue.add_daily_job("tag_expiry_check", jobs.check_tag_expiry, hour=4)
    common.jobqueue.start()

    # 恢复待提问状态（5分钟内）
    from kmua.plugins.dice_game import restore_pending_questions
    await restore_pending_questions()

    logger.success(i18n.t("log.inited", locale=app_config.lang))


@client.on_stop()
async def stop_bot(client: Client = client):
    logger.info(i18n.t("log.stopping", locale=app_config.lang))
    common.jobqueue.shutdown()
    await db.close_db()
    logger.success(i18n.t("log.exit", locale=app_config.lang))


async def main():
    await db.init_db()
    await client.start()
    await idle()
    await client.stop()  # type: ignore


if __name__ == "__main__":
    if app_config.automigrate:
        db.migrate_db()
    client.loop.run_until_complete(main())
