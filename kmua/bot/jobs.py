import io
import random

import httpx
import pyrogram

from kmua import common, database, enums, i18n
from kmua.config import app_config
from kmua.logger import logger


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
    from kmua.bot.client import client

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


async def change_bot_avatar():
    """
    定时更换 bot 头像
    使用 manyacg 获取随机图片，aniobjcut 裁切为头像，然后更新 bot profile photo
    """
    from kmua.bot.client import client
    from kmua.services import aniobjcut, manyacg

    if not manyacg.manyacg_client or not aniobjcut.aniobjcut_client:
        logger.warning(i18n.t("log.avatar_change_disabled", locale=app_config.lang))
        return

    try:
        logger.info(i18n.t("log.avatar_changing", locale=app_config.lang))

        # 获取随机图片
        resp = await manyacg.manyacg_client.random_artwork(limit=1, r18=0)
        if resp.status != 200 or not resp.data:
            logger.error(f"failed to get random artwork: {resp.message}")
            return

        artwork = resp.data[0]
        picture = artwork.pictures[random.randint(0, len(artwork.pictures) - 1)]

        # 下载图片
        async with httpx.AsyncClient(timeout=30) as http_client:
            fileresp = await http_client.get(
                f"{app_config.manyacg_api_url}/picture/file/{picture.id}",
            )
            fileresp.raise_for_status()

        # 裁切为头像
        avatar = await aniobjcut.aniobjcut_client.cut_avatar(fileresp.content)

        await client.set_profile_photo(
            pyrogram.types.InputChatPhotoStatic(io.BytesIO(avatar))
        )
        logger.success(
            i18n.t("log.avatar_changed", locale=app_config.lang).format(
                title=artwork.title, url=artwork.source_url
            )
        )

    except Exception as e:
        logger.exception(
            i18n.t("log.avatar_change_failed", locale=app_config.lang).format(
                error=str(e)
            )
        )
