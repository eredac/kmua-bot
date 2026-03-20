from kmua import common, database, enums
from kmua.logger import logger

from .client import client


async def cleanup():
    try:
        logger.info("cleaning data")
        await common.memstore.set(enums.GLockKey.CLEANING, True)
        await database.cleanup_waifu_data()
        # await database.cleanup_user_avatar()
        # common.cleanup_avatar_cache()
    finally:
        logger.info("clean data done")
        await common.memstore.delete(enums.GLockKey.CLEANING)


async def check_tag_expiry():
    """检查标签到期情况：发送临期提醒、清除已过期标签"""
    logger.info("check_tag_expiry: start")

    # 1. 即将到期（24 小时内）：发送私聊提醒
    try:
        expiring = await database.get_expiring_tags(within_hours=24)
        for tag in expiring:
            try:
                chat = await client.get_chat(tag.chat_id)
                chat_title = getattr(chat, "title", str(tag.chat_id))
                await client.send_message(
                    tag.user_id,
                    f"⚠️ 您在群组「{chat_title}」的个人标签「{tag.tag_text}」"
                    f"将在 24 小时内到期，请发送 /settag 续费（{100} 积分/月）",
                )
            except Exception as e:
                logger.debug(f"标签临期提醒发送失败: user={tag.user_id}, chat={tag.chat_id}: {e}")
    except Exception as e:
        logger.warning(f"get_expiring_tags 失败: {e}")

    # 2. 已过期：清除 API 标签、删除数据库记录、发送通知
    try:
        expired = await database.get_expired_tags()
        for tag in expired:
            try:
                await client.set_chat_member_tag(tag.chat_id, tag.user_id, tag="")
            except AttributeError:
                logger.debug("set_chat_member_tag 未被当前客户端库支持，跳过清除")
            except Exception as e:
                logger.debug(f"清除过期标签失败: user={tag.user_id}, chat={tag.chat_id}: {e}")

            try:
                await database.delete_user_tag(tag.user_id, tag.chat_id)
            except Exception as e:
                logger.warning(f"删除过期标签记录失败: user={tag.user_id}, chat={tag.chat_id}: {e}")
                continue

            try:
                chat = await client.get_chat(tag.chat_id)
                chat_title = getattr(chat, "title", str(tag.chat_id))
                await client.send_message(
                    tag.user_id,
                    f"📢 您在群组「{chat_title}」的个人标签「{tag.tag_text}」已到期，"
                    f"如需续费请发送 /settag（{100} 积分/月）",
                )
            except Exception as e:
                logger.debug(f"标签到期通知发送失败: user={tag.user_id}, chat={tag.chat_id}: {e}")
    except Exception as e:
        logger.warning(f"get_expired_tags 失败: {e}")

    logger.info("check_tag_expiry: done")
