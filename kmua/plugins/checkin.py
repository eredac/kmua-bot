"""
签到功能模块
- @bot 每日签到：固定获得 3 积分
- @bot 老虎机签到：投老虎机，根据点数获得不同积分

并发控制：每个 (user_id, chat_id) 维护一把 asyncio.Lock，
采用双重检查锁（先无锁快查，再带锁二次确认），防止并发重复签到。

所有签到回复（成功/重复提示）均在 10 秒后自动删除。
"""
import asyncio

import pyrogram
import zhconv
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from kmua import database
from kmua.logger import logger

# 老虎机积分规则：{点数: 积分}
_SLOT_POINTS: dict[int, int] = {
    64: 100,
    1: 50,
    22: 20,
    43: 10,
}
_SLOT_DEFAULT_POINTS = 1
_DAILY_CHECKIN_POINTS = 3
_AUTO_DELETE_DELAY = 10  # 秒

# 每 (user_id, chat_id) 一把锁，防止并发重复签到
_checkin_locks: dict[tuple[int, int], asyncio.Lock] = {}


def _get_lock(user_id: int, chat_id: int) -> asyncio.Lock:
    key = (user_id, chat_id)
    if key not in _checkin_locks:
        _checkin_locks[key] = asyncio.Lock()
    return _checkin_locks[key]


def _get_slot_points(value: int) -> int:
    return _SLOT_POINTS.get(value, _SLOT_DEFAULT_POINTS)


def _extract_text(message: Message, bot_username: str) -> str:
    """移除 @botname 后的纯文本（繁→简）"""
    raw = message.text or message.caption or ""
    return zhconv.convert(raw.replace(f"@{bot_username}", "").strip().lower(), "zh-cn")


async def _auto_delete(msg: Message, delay: int = _AUTO_DELETE_DELAY) -> None:
    """延迟后自动删除消息"""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception as e:
        logger.debug(f"自动删除签到消息失败: {e}")


async def _checkin_filter_func(
    _, client: pyrogram.Client, message: pyrogram.types.Message
) -> bool:
    if not message.text and not message.caption:
        return False
    if not client.me:
        return False
    username = client.me.username
    if not username:
        return False
    full_text = message.text or message.caption or ""
    if f"@{username}" not in full_text:
        return False
    text = _extract_text(message, username)
    return "每日签到" in text or "老虎机签到" in text


checkin_filter = filters.create(_checkin_filter_func)

_ALREADY_CHECKED_IN_MSG = "今天已经签到过了哦～"


@Client.on_message(checkin_filter & filters.group, group=0)
async def checkin_handler(client: Client, message: Message):
    """处理签到指令"""
    user = message.from_user
    if not user or not client.me:
        return
    chat_config = await database.get_chat_config(message.chat)
    if not chat_config.checkin_enabled:
        return

    text = _extract_text(message, client.me.username)
    chat_id = message.chat.id
    user_id = user.id
    safe_name = (
        user.first_name
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    mention = f'<a href="tg://user?id={user_id}">{safe_name}</a>'

    if "老虎机签到" in text:
        await _handle_slot_checkin(client, message, user_id, chat_id, mention)
    else:
        await _handle_daily_checkin(message, user_id, chat_id, mention)

    message.stop_propagation()


async def _handle_daily_checkin(
    message: Message, user_id: int, chat_id: int, mention: str
) -> None:
    """处理每日签到：固定 3 积分，双重检查锁防并发"""
    # 第一次检查（无锁快速路径）
    if await database.has_any_checkin_today(user_id, chat_id):
        reply = await message.reply_text(
            f"⚠️ {mention}，{_ALREADY_CHECKED_IN_MSG}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(reply))
        return

    async with _get_lock(user_id, chat_id):
        # 第二次检查（锁内确认，防止并发重复）
        if await database.has_any_checkin_today(user_id, chat_id):
            reply = await message.reply_text(
                f"⚠️ {mention}，{_ALREADY_CHECKED_IN_MSG}",
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(_auto_delete(reply))
            return

        user_points = await database.record_checkin_and_add_points(
            user_id, chat_id, "daily", _DAILY_CHECKIN_POINTS
        )

    reply = await message.reply_text(
        f"✅ {mention} 签到成功！\n\n"
        f"获得积分：<b>+{_DAILY_CHECKIN_POINTS}</b>\n"
        f"当前积分：<b>{user_points.points}</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_auto_delete(reply))
    logger.info(
        f"每日签到: user={user_id}, chat={chat_id}, "
        f"points=+{_DAILY_CHECKIN_POINTS}, total={user_points.points}"
    )


async def _handle_slot_checkin(
    client: Client, message: Message, user_id: int, chat_id: int, mention: str
) -> None:
    """处理老虎机签到：双重检查锁内发骰子，防并发重复"""
    # 第一次检查（无锁快速路径）
    if await database.has_any_checkin_today(user_id, chat_id):
        reply = await message.reply_text(
            f"⚠️ {mention}，{_ALREADY_CHECKED_IN_MSG}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(reply))
        return

    async with _get_lock(user_id, chat_id):
        # 第二次检查（锁内确认）
        if await database.has_any_checkin_today(user_id, chat_id):
            reply = await message.reply_text(
                f"⚠️ {mention}，{_ALREADY_CHECKED_IN_MSG}",
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(_auto_delete(reply))
            return

        # 发送老虎机，等待动画结束再读取点数
        slot_msg = await client.send_dice(
            chat_id, "🎰", message_thread_id=message.message_thread_id
        )
        await asyncio.sleep(3)

        value = slot_msg.dice.value
        points = _get_slot_points(value)

        user_points = await database.record_checkin_and_add_points(
            user_id, chat_id, "slot", points
        )

    # 构建奖励说明
    if points == 100:
        prize_text = "🎉 <b>超级大奖！</b> 777！"
    elif points == 50:
        prize_text = "🌟 <b>大奖！</b>"
    elif points == 20:
        prize_text = "✨ <b>不错的奖励！</b>"
    elif points == 10:
        prize_text = "👍 <b>小奖！</b>"
    else:
        prize_text = "😅 <b>安慰奖</b>"

    reply = await message.reply_text(
        f"{mention} 的老虎机结果：🎰 点数 <b>{value}</b>\n\n"
        f"{prize_text}\n"
        f"获得积分：<b>+{points}</b>\n"
        f"当前积分：<b>{user_points.points}</b>",
        parse_mode=ParseMode.HTML,
    )
    # 安慰奖自动删除，中奖消息保留
    if points <= _SLOT_DEFAULT_POINTS:
        asyncio.create_task(_auto_delete(reply))
    logger.info(
        f"老虎机签到: user={user_id}, chat={chat_id}, "
        f"slot_value={value}, points=+{points}, total={user_points.points}"
    )
