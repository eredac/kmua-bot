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
import re

import httpx
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from kmua import database
from kmua.config import app_config
from kmua.database.db import AsyncSessionFactory
from kmua.logger import logger

_TAG_COST = 100          # 每次购买/续费消耗的积分
_EDIT_TAG_COST = 50      # 仅修改标签文字消耗的积分
_TAG_DURATION_DAYS = 30  # 标签有效期（天）
_MAX_TAG_LEN = 16        # 标签最大字符数
_AUTO_DELETE_DELAY = 30  # 成功/错误回复的自动删除延迟（秒）

_TZ_CST = datetime.timezone(datetime.timedelta(hours=8))


async def _set_chat_member_tag(client: Client, chat_id: int, user_id: int, tag: str) -> bool:
    """调用 Bot API setChatMemberTag，优先用 Pyrogram 原生方法，不支持则直接 HTTP 调用"""
    try:
        await client.set_chat_member_tag(chat_id, user_id, tag=tag)
        return True
    except AttributeError:
        pass

    # Pyrogram 未实现，直接 HTTP 调用 Bot API
    try:
        url = f"https://api.telegram.org/bot{app_config.token}/setChatMemberTag"
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(url, json={
                "chat_id": chat_id,
                "user_id": user_id,
                "tag": tag,
            })
            data = resp.json()
            if data.get("ok"):
                return True
            logger.warning(f"setChatMemberTag API 返回失败: {data}")
            return False
    except Exception as e:
        logger.warning(f"setChatMemberTag HTTP 调用失败: {e}")
        return False


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
    ok = await _set_chat_member_tag(client, chat_id, user_id, tag_text)
    if not ok:
        logger.warning(f"setChatMemberTag 失败: user={user_id}, chat={chat_id}, tag='{tag_text}'")

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
    ok = await _set_chat_member_tag(client, chat_id, user_id, tag_text)
    if not ok:
        logger.warning(f"setChatMemberTag 失败 (edittag): user={user_id}, chat={chat_id}, tag='{tag_text}'")

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


# ─── 赠送标签（数据库持久化） ───────────────────────────────


_GIFT_TIMEOUT_SECS = 86400  # 1 天
_gift_timers: dict[int, asyncio.Task] = {}


def _safe_html(name: str) -> str:
    return name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _gift_timeout_task(client: Client, gift_id: int) -> None:
    """1 天后自动取消赠送请求"""
    await asyncio.sleep(_GIFT_TIMEOUT_SECS)
    _gift_timers.pop(gift_id, None)
    gift = await database.get_pending_gift(gift_id)
    if gift is None or gift.status != "pending":
        return
    try:
        await database.complete_pending_gift(gift_id, status="expired")
    except ValueError:
        return
    if gift.message_id:
        try:
            await client.edit_message_text(
                gift.chat_id, gift.message_id,
                "⏰ 标签赠送请求已过期，自动取消。",
            )
        except Exception:
            pass
    logger.info(f"标签赠送超时: gift_id={gift_id}, sender={gift.sender_id}, target={gift.target_id}")


async def recover_gift_on_startup(client: Client) -> None:
    """Bot 启动时清理过期的赠送请求，为未过期的重新启动计时器"""
    # 清理已过期的
    expired = await database.get_expired_pending_gifts()
    for gift in expired:
        try:
            await database.complete_pending_gift(gift.id, status="expired")
        except ValueError:
            continue
        if gift.message_id:
            try:
                await client.edit_message_text(
                    gift.chat_id, gift.message_id,
                    "⏰ 标签赠送请求已过期，自动取消。",
                )
            except Exception:
                pass
    if expired:
        logger.info(f"启动恢复：清理 {len(expired)} 个过期标签赠送")

    # 为仍有效的 pending gift 重新启动计时器
    from kmua.database.db import AsyncSessionFactory
    import sqlalchemy
    from kmua.database.models import PendingTagGift

    async with AsyncSessionFactory() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = sqlalchemy.select(PendingTagGift).where(
            PendingTagGift.status == "pending",
            PendingTagGift.expires_at >= now,
        )
        result = await session.execute(stmt)
        active = result.scalars().all()
        for gift in active:
            remaining = (gift.expires_at.replace(tzinfo=datetime.timezone.utc) - now).total_seconds()
            if remaining > 0:
                task = asyncio.create_task(_gift_timeout_resume(client, gift.id, remaining))
                _gift_timers[gift.id] = task
        if active:
            logger.info(f"启动恢复：恢复 {len(active)} 个待确认标签赠送计时器")


async def _gift_timeout_resume(client: Client, gift_id: int, remaining: float) -> None:
    """恢复的超时计时器"""
    await asyncio.sleep(remaining)
    _gift_timers.pop(gift_id, None)
    gift = await database.get_pending_gift(gift_id)
    if gift is None or gift.status != "pending":
        return
    try:
        await database.complete_pending_gift(gift_id, status="expired")
    except ValueError:
        return
    if gift.message_id:
        try:
            await client.edit_message_text(
                gift.chat_id, gift.message_id,
                "⏰ 标签赠送请求已过期，自动取消。",
            )
        except Exception:
            pass
    logger.info(f"标签赠送超时(恢复): gift_id={gift_id}")


@Client.on_message(filters.command("gifttag") & filters.group, group=0)
async def gifttag_handler(client: Client, message: Message) -> None:
    """处理 /gifttag <标签文字>（回复目标用户消息或 @用户）
    用法：
      回复某人消息：/gifttag <标签文字>
      @某人：/gifttag @username <标签文字>
    """
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    sender_id = user.id

    # 解析目标用户：优先回复消息，其次 @mention
    target = None
    tag_text = None

    reply = message.reply_to_message
    # 排除 Forum 话题的自动回复（非用户主动回复）
    _is_real_reply = (
        reply is not None
        and reply.from_user is not None
        and not getattr(reply, "forum_topic_created", None)
        and not getattr(reply, "forum_topic_edited", None)
        and (
            getattr(message, "message_thread_id", None) is None
            or message.reply_to_message_id != getattr(message, "message_thread_id", None)
        )
    )
    if _is_real_reply:
        # 回复消息模式
        target = reply.from_user
        args = message.text.split(maxsplit=1)
        tag_text = args[1].strip() if len(args) >= 2 else None
    elif message.entities:
        # @mention 模式：找第一个非命令的 mention entity
        import pyrogram.enums as enums
        raw_text = message.text or ""
        for entity in message.entities:
            if entity.type == enums.MessageEntityType.BOT_COMMAND:
                continue
            if entity.type == enums.MessageEntityType.MENTION:
                username = raw_text[entity.offset + 1 : entity.offset + entity.length]  # 去掉 @
                try:
                    target_user = await client.get_users(username)
                    target = target_user
                except Exception:
                    pass
                # 标签文字 = @username 之后的部分
                after = raw_text[entity.offset + entity.length:]
                tag_text = after.strip() if after.strip() else None
                break
            elif entity.type == enums.MessageEntityType.TEXT_MENTION:
                target = entity.user
                after = raw_text[entity.offset + entity.length:]
                tag_text = after.strip() if after.strip() else None
                break

    if target is None:
        r = await message.reply_text("⚠️ 请回复目标用户的消息，或使用 /gifttag @用户 <标签文字>")
        asyncio.create_task(_auto_delete(message, r))
        return

    if target.id == sender_id:
        r = await message.reply_text("⚠️ 不能给自己赠送标签喵～ 请使用 /settag")
        asyncio.create_task(_auto_delete(message, r))
        return
    if target.is_bot:
        r = await message.reply_text("⚠️ 不能给 Bot 赠送标签喵～")
        asyncio.create_task(_auto_delete(message, r))
        return

    if not tag_text:
        r = await message.reply_text("⚠️ 请指定标签文字：/gifttag <标签文字> 或 /gifttag @用户 <标签文字>")
        asyncio.create_task(_auto_delete(message, r))
        return
    if len(tag_text) > _MAX_TAG_LEN:
        r = await message.reply_text(f"⚠️ 标签最长 {_MAX_TAG_LEN} 个字符喵～")
        asyncio.create_task(_auto_delete(message, r))
        return

    # 检查目标用户是否已有有效标签
    existing_tag = await database.get_user_tag(target.id, chat_id)
    has_existing = False
    if existing_tag:
        now = datetime.datetime.now(datetime.timezone.utc)
        if existing_tag.expires_at.replace(tzinfo=datetime.timezone.utc) > now:
            has_existing = True

    # 验证发送方积分
    user_points = await database.get_user_points(sender_id, chat_id)
    total = user_points.points if user_points else 0
    if total < _TAG_COST:
        r = await message.reply_text(
            f"⚠️ 积分不足！需要 <b>{_TAG_COST}</b> 积分，当前：<b>{total}</b>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(message, r))
        return

    # 创建赠送记录（持久化到数据库）
    safe_sender = _safe_html(user.first_name)
    safe_target = _safe_html(target.first_name)
    sender_mention = f'<a href="tg://user?id={sender_id}">{safe_sender}</a>'
    target_mention = f'<a href="tg://user?id={target.id}">{safe_target}</a>'

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=_GIFT_TIMEOUT_SECS)
    gift = await database.create_pending_gift(
        sender_id=sender_id,
        sender_name=safe_sender,
        target_id=target.id,
        target_name=safe_target,
        chat_id=chat_id,
        tag_text=tag_text,
        expires_at=expires_at,
    )
    gift_id = gift.id

    # 发送确认消息
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 接受", callback_data=f"gift_tag_accept_{gift_id}"),
            InlineKeyboardButton("❌ 拒绝", callback_data=f"gift_tag_reject_{gift_id}"),
        ]
    ])
    replace_note = (
        f"\n⚠️ 注意：将替换现有标签「{existing_tag.tag_text}」\n"
        if has_existing else ""
    )
    reply_msg = await message.reply_text(
        f"🎁 {sender_mention} 想赠送标签给 {target_mention}！\n\n"
        f"🏷 标签：<b>{tag_text}</b>\n"
        f"💰 费用：<b>{_TAG_COST}</b> 积分（由赠送方支付）\n"
        f"📅 有效期：<b>{_TAG_DURATION_DAYS}</b> 天\n"
        f"{replace_note}\n"
        f"请 {target_mention} 点击按钮确认是否接受～",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await database.update_gift_message_id(gift_id, reply_msg.id)

    # 启动超时定时器
    task = asyncio.create_task(_gift_timeout_task(client, gift_id))
    _gift_timers[gift_id] = task

    logger.info(
        f"标签赠送发起: gift_id={gift_id}, sender={sender_id}, "
        f"target={target.id}, tag='{tag_text}'"
    )


@Client.on_callback_query(filters.regex(r"^gift_tag_accept_(\d+)$"))
async def on_gift_accept(client: Client, callback: CallbackQuery) -> None:
    """目标用户接受赠送"""
    m = re.match(r"^gift_tag_accept_(\d+)$", callback.data)
    gift_id = int(m.group(1))
    user_id = callback.from_user.id

    gift = await database.get_pending_gift(gift_id)
    if gift is None or gift.status != "pending":
        await callback.answer("❌ 该赠送请求已过期或不存在", show_alert=True)
        return
    if user_id != gift.target_id:
        await callback.answer("⚠️ 只有被赠送的人才能操作喵～", show_alert=True)
        return

    # 验证发送方积分
    sender_points = await database.get_user_points(gift.sender_id, gift.chat_id)
    sender_total = sender_points.points if sender_points else 0
    if sender_total < _TAG_COST:
        await callback.answer(
            f"⚠️ 赠送方积分不足（需要 {_TAG_COST}，当前 {sender_total}），赠送失败",
            show_alert=True,
        )
        return

    # 原子：标记完成 + 扣积分 + 写入标签
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await database.complete_pending_gift(gift_id, status="accepted", session=session)
                updated_points = await database.cost_points(
                    gift.sender_id, gift.chat_id, _TAG_COST,
                    reason=f"赠送标签给 {gift.target_name}（{gift.tag_text}）",
                    session=session,
                )
                # 先删除旧标签，确保有效期从现在重新计算（不叠加）
                await database.delete_user_tag(gift.target_id, gift.chat_id, session=session)
                tag = await database.upsert_user_tag(
                    gift.target_id, gift.chat_id, gift.tag_text,
                    duration_days=_TAG_DURATION_DAYS,
                    session=session,
                )
    except ValueError as e:
        await callback.answer(f"⚠️ {e}", show_alert=True)
        return

    # 调用 Bot API 设置标签
    ok = await _set_chat_member_tag(client, gift.chat_id, gift.target_id, gift.tag_text)
    if not ok:
        logger.warning(f"setChatMemberTag 失败 (gifttag): target={gift.target_id}, tag='{gift.tag_text}'")

    # 取消定时器
    timer = _gift_timers.pop(gift_id, None)
    if timer:
        timer.cancel()

    expires_cst = tag.expires_at.replace(tzinfo=datetime.timezone.utc).astimezone(_TZ_CST)
    expires_str = expires_cst.strftime("%Y-%m-%d %H:%M")
    sender_mention = f'<a href="tg://user?id={gift.sender_id}">{gift.sender_name}</a>'
    target_mention = f'<a href="tg://user?id={gift.target_id}">{gift.target_name}</a>'

    await callback.message.edit_text(
        f"✅ 标签赠送成功！\n\n"
        f"🎁 {sender_mention} → {target_mention}\n"
        f"🏷 标签：<b>{gift.tag_text}</b>\n"
        f"📅 到期时间：<b>{expires_str}</b>（UTC+8）\n"
        f"💰 赠送方剩余积分：<b>{updated_points.points}</b>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("✅ 已接受标签赠送！")
    logger.info(
        f"标签赠送完成: gift_id={gift_id}, sender={gift.sender_id}, "
        f"target={gift.target_id}, tag='{gift.tag_text}'"
    )


@Client.on_callback_query(filters.regex(r"^gift_tag_reject_(\d+)$"))
async def on_gift_reject(client: Client, callback: CallbackQuery) -> None:
    """目标用户拒绝赠送"""
    m = re.match(r"^gift_tag_reject_(\d+)$", callback.data)
    gift_id = int(m.group(1))
    user_id = callback.from_user.id

    gift = await database.get_pending_gift(gift_id)
    if gift is None or gift.status != "pending":
        await callback.answer("❌ 该赠送请求已过期或不存在", show_alert=True)
        return
    if user_id != gift.target_id:
        await callback.answer("⚠️ 只有被赠送的人才能操作喵～", show_alert=True)
        return

    try:
        await database.complete_pending_gift(gift_id, status="rejected")
    except ValueError:
        await callback.answer("❌ 该赠送请求已过期或不存在", show_alert=True)
        return

    # 取消定时器
    timer = _gift_timers.pop(gift_id, None)
    if timer:
        timer.cancel()

    sender_mention = f'<a href="tg://user?id={gift.sender_id}">{gift.sender_name}</a>'
    target_mention = f'<a href="tg://user?id={gift.target_id}">{gift.target_name}</a>'
    await callback.message.edit_text(
        f"❌ {target_mention} 拒绝了 {sender_mention} 的标签赠送（{gift.tag_text}）",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("已拒绝")
    logger.info(f"标签赠送被拒绝: gift_id={gift_id}")
