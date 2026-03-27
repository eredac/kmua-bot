"""
个人标签功能模块

- /settag <标签文字>：消耗 100 积分购买/续费 30 天个人标签
- /mytag：查看当前标签状态

依赖 Bot API 9.5 的 setChatMemberTag 方法（Telegram 2026-03-01 新增）。
- Telegram 是标签文字的实际来源，数据库只负责记录计费到期信息。
- 若管理员手动修改了标签，/mytag 显示的是 Telegram 实际标签，数据库中的文字仅作备份参考。
"""
import asyncio
import datetime

from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from kmua import database
from kmua.database.db import AsyncSessionFactory
from kmua.logger import logger

_TAG_COST = 100          # 每次购买/续费消耗的积分
_EDIT_TAG_COST = 50      # 仅修改标签文字消耗的积分
_TAG_DURATION_DAYS = 30  # 标签有效期（天）
_MAX_TAG_LEN = 16        # 标签最大字符数
_AUTO_DELETE_DELAY = 30  # 成功/错误回复的自动删除延迟（秒）

_TZ_CST = datetime.timezone(datetime.timedelta(hours=8))


async def _auto_delete(*msgs: Message, delay: int = _AUTO_DELETE_DELAY) -> None:
    try:
        await asyncio.sleep(delay)
        for msg in msgs:
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"自动删除标签消息失败: {e}")


def _remaining_days(expires_at: datetime.datetime) -> int:
    """计算距到期的剩余天数（向上取整）"""
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_utc = expires_at.replace(tzinfo=datetime.timezone.utc)
    delta = expires_utc - now
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() / 86400) + (1 if delta.total_seconds() % 86400 > 0 else 0)


async def _get_actual_tag(client: Client, chat_id: int, user_id: int) -> str | None:
    """从 Telegram API 获取用户在群组的实际当前标签（Bot API 9.5）。
    Kurigram 尚未支持或调用失败时返回 None。
    """
    try:
        member = await client.get_chat_member(chat_id, user_id)
        # Bot API 9.5 新增 tag 字段，Pyrogram/Kurigram 映射名待确认
        tag = getattr(member, "tag", None)
        return tag if tag else None
    except Exception as e:
        logger.debug(f"get_chat_member 获取标签失败: chat={chat_id}, user={user_id}: {e}")
        return None


@Client.on_message(filters.command("settag") & filters.group, group=0)
async def settag_handler(client: Client, message: Message) -> None:
    """处理 /settag <标签文字> 命令"""
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    user_id = user.id

    # 解析标签文字
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        reply = await message.reply_text(
            "💡 用法：<code>/settag 你的标签</code>（最多 16 个字符）",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    tag_text = args[1].strip()
    if len(tag_text) > _MAX_TAG_LEN:
        reply = await message.reply_text(
            f"⚠️ 标签文字不能超过 {_MAX_TAG_LEN} 个字符（当前 {len(tag_text)} 个）",
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 检查用户积分是否充足
    user_points = await database.get_user_points(user_id, chat_id)
    current_points = user_points.points if user_points else 0
    if current_points < _TAG_COST:
        reply = await message.reply_text(
            f"⚠️ 积分不足！购买标签需要 <b>{_TAG_COST}</b> 积分，"
            f"当前积分：<b>{current_points}</b>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 判断是新购还是续费：
    # 优先以 Telegram 实际状态为准（是否有 tag），其次看数据库计费记录是否有效
    actual_tag = await _get_actual_tag(client, chat_id, user_id)
    if actual_tag is not None:
        is_active = True  # Telegram 实际有标签 → 续费
    else:
        # Telegram 无法确认（API 未支持或无标签），回退到数据库计费记录
        db_tag = await database.get_user_tag(user_id, chat_id)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        is_active = (
            db_tag is not None
            and db_tag.expires_at.replace(tzinfo=datetime.timezone.utc) > now_utc
        )

    reason = "续费个人标签（30天）" if is_active else "购买个人标签（30天）"

    # 原子扣积分 + 写入标签（同一事务）
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                updated_points = await database.cost_points(
                    user_id, chat_id, _TAG_COST, reason=reason, session=session
                )
                tag = await database.upsert_user_tag(
                    user_id, chat_id, tag_text,
                    duration_days=_TAG_DURATION_DAYS,
                    session=session,
                )
    except ValueError as e:
        reply = await message.reply_text(f"⚠️ {e}")
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 调用 Bot API 9.5 setChatMemberTag
    try:
        await client.set_chat_member_tag(chat_id, user_id, tag=tag_text)
    except AttributeError:
        logger.warning("set_chat_member_tag 未被当前客户端库支持，跳过 API 调用")
    except Exception as e:
        logger.warning(f"set_chat_member_tag 调用失败: {e}")

    expires_cst = tag.expires_at.replace(tzinfo=datetime.timezone.utc).astimezone(_TZ_CST)
    expires_str = expires_cst.strftime("%Y-%m-%d %H:%M")
    action = "续费" if is_active else "购买"
    reply = await message.reply_text(
        f"✅ 标签{action}成功！\n\n"
        f"🏷 标签：<b>{tag_text}</b>\n"
        f"📅 到期时间：<b>{expires_str}</b>（UTC+8）\n"
        f"💰 剩余积分：<b>{updated_points.points}</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_auto_delete(message, reply))
    logger.info(
        f"用户标签{action}: user={user_id}, chat={chat_id}, "
        f"tag='{tag_text}', expires={tag.expires_at}"
    )


@Client.on_message(filters.command("mytag") & filters.group, group=0)
async def mytag_handler(client: Client, message: Message) -> None:
    """处理 /mytag 命令，查看当前标签状态。
    显示文字以 Telegram 实际状态为准，到期时间以数据库计费记录为准。
    """
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    user_id = user.id

    # 并发获取 Telegram 实际标签和数据库计费记录
    actual_tag, db_tag = await asyncio.gather(
        _get_actual_tag(client, chat_id, user_id),
        database.get_user_tag(user_id, chat_id),
    )

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # 无论哪一侧有数据，都尝试呈现完整信息
    display_tag_text = actual_tag or (db_tag.tag_text if db_tag else None)

    if display_tag_text is None and db_tag is None:
        # Telegram 和数据库都没有记录
        reply = await message.reply_text(
            "🏷 您在本群还没有个人标签。\n\n"
            f"发送 <code>/settag 你的标签</code> 花费 <b>{_TAG_COST} 积分</b>购买（有效期 30 天）",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    if db_tag is None:
        # Telegram 有标签但数据库没有计费记录（管理员手动设置）
        reply = await message.reply_text(
            f"🏷 当前标签：<b>{display_tag_text}</b>\n"
            f"ℹ️ 该标签由管理员手动设置，不在 bot 计费范围内，不会自动过期。\n\n"
            f"发送 <code>/settag {display_tag_text}</code> 可将其纳入 bot 管理（{_TAG_COST} 积分/月）",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 有数据库计费记录
    expires_utc = db_tag.expires_at.replace(tzinfo=datetime.timezone.utc)
    expires_cst = expires_utc.astimezone(_TZ_CST)
    expires_str = expires_cst.strftime("%Y-%m-%d %H:%M")

    # 检测管理员是否修改了标签文字
    tag_modified_note = ""
    if actual_tag is not None and actual_tag != db_tag.tag_text:
        tag_modified_note = f"\n⚠️ 标签文字已被管理员修改（原记录：{db_tag.tag_text}）"

    if expires_utc < now_utc:
        reply = await message.reply_text(
            f"⚠️ 您的标签「<b>{display_tag_text}</b>」已于 <b>{expires_str}</b>（UTC+8）到期。{tag_modified_note}\n\n"
            f"发送 <code>/settag {display_tag_text}</code> 花费 <b>{_TAG_COST} 积分</b>续费",
            parse_mode=ParseMode.HTML,
        )
    else:
        remaining = _remaining_days(db_tag.expires_at)
        reply = await message.reply_text(
            f"🏷 当前标签：<b>{display_tag_text}</b>{tag_modified_note}\n"
            f"📅 到期时间：<b>{expires_str}</b>（UTC+8）\n"
            f"⏳ 剩余天数：<b>{remaining}</b> 天\n\n"
            f"发送 <code>/settag 新标签</code> 可续费或修改标签（{_TAG_COST} 积分/月）",
            parse_mode=ParseMode.HTML,
        )
    asyncio.create_task(_auto_delete(message, reply))


@Client.on_message(filters.command("edittag") & filters.group, group=0)
async def edittag_handler(client: Client, message: Message) -> None:
    """处理 /edittag <标签文字> 命令，仅修改标签内容，不改变到期时间，花费 50 积分"""
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    user_id = user.id

    # 解析标签文字
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        reply = await message.reply_text(
            f"💡 用法：<code>/edittag 新标签内容</code>（最多 {_MAX_TAG_LEN} 个字符，花费 {_EDIT_TAG_COST} 积分）",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    tag_text = args[1].strip()
    if len(tag_text) > _MAX_TAG_LEN:
        reply = await message.reply_text(
            f"⚠️ 标签文字不能超过 {_MAX_TAG_LEN} 个字符（当前 {len(tag_text)} 个）",
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 检查积分是否充足
    user_points = await database.get_user_points(user_id, chat_id)
    current_points = user_points.points if user_points else 0
    if current_points < _EDIT_TAG_COST:
        reply = await message.reply_text(
            f"⚠️ 积分不足！修改标签需要 <b>{_EDIT_TAG_COST}</b> 积分，"
            f"当前积分：<b>{current_points}</b>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 原子扣积分 + 仅更新标签文字（同一事务）
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                updated_points = await database.cost_points(
                    user_id, chat_id, _EDIT_TAG_COST,
                    reason="修改个人标签文字",
                    session=session,
                )
                tag = await database.update_tag_text_only(
                    user_id, chat_id, tag_text, session=session
                )
    except ValueError as e:
        reply = await message.reply_text(f"⚠️ {e}")
        asyncio.create_task(_auto_delete(message, reply))
        return

    # 调用 Bot API 9.5 setChatMemberTag 更新 Telegram 侧标签
    try:
        await client.set_chat_member_tag(chat_id, user_id, tag=tag_text)
    except AttributeError:
        logger.warning("set_chat_member_tag 未被当前客户端库支持，跳过 API 调用")
    except Exception as e:
        logger.warning(f"set_chat_member_tag 调用失败: {e}")

    expires_cst = tag.expires_at.replace(tzinfo=datetime.timezone.utc).astimezone(_TZ_CST)
    expires_str = expires_cst.strftime("%Y-%m-%d %H:%M")
    reply = await message.reply_text(
        f"✅ 标签修改成功！\n\n"
        f"🏷 新标签：<b>{tag_text}</b>\n"
        f"📅 到期时间：<b>{expires_str}</b>（UTC+8，不变）\n"
        f"💰 剩余积分：<b>{updated_points.points}</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_auto_delete(message, reply))
    logger.info(
        f"用户标签修改: user={user_id}, chat={chat_id}, "
        f"new_tag='{tag_text}', expires={tag.expires_at}"
    )
