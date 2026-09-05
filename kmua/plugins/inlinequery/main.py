import asyncio
import random

from pyrogram import enums, types
from pyrogram.client import Client

from kmua import database, i18n
from kmua.logger import logger

from . import hack

# Telegram 🎰 每轮符号：index 0-3 对应 BAR / 🍇 / 🍋 / 7️⃣
_SLOT_SYMBOLS = ["BAR", "🍇", "🍋", "7️⃣"]
_SLOT_POINTS_MAP = {64: 50, 1: 30, 22: 15, 43: 5}  # 其余均为 1 分
_SLOT_MAX_DAILY = 3
_AUTO_DELETE_DELAY = 60  # 结果消息自动删除延迟（秒）


def _decode_slot_pattern(value: int) -> str:
    """将 Telegram 🎰 点数（1-64）解码为三轮图案字符串"""
    idx = value - 1
    r1 = _SLOT_SYMBOLS[idx % 4]
    r2 = _SLOT_SYMBOLS[(idx // 4) % 4]
    r3 = _SLOT_SYMBOLS[(idx // 16) % 4]
    return f"[ {r1} | {r2} | {r3} ]"


async def _delete_after(client: Client, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception as e:
        logger.warning(f"Auto-delete inline message failed: {e}")


@Client.on_inline_query()
async def inline_query_handler(client: Client, query: types.InlineQuery):
    user = query.from_user
    user_config = await database.get_user_config(user)
    results: list[types.InlineQueryResult] = []

    if query.chat_type == enums.ChatType.SUPERGROUP:
        # inline query 阶段 Telegram 不提供 chat_id，无法按群判断签到状态
        # 始终展示两个选项，实际的按群限制在 chosen_inline_result 阶段执行
        results.append(
            types.InlineQueryResultArticle(
                id="slot_checkin",
                title="🎰 老虎机签到",
                description=f"摇老虎机获得随机积分（每天最多 {_SLOT_MAX_DAILY} 次）",
                input_message_content=types.InputTextMessageContent(
                    message_text="🎰 老虎机启动中...",
                ),
                reply_markup=types.InlineKeyboardMarkup(
                    [[types.InlineKeyboardButton(text="🎰", callback_data="noop")]]
                ),
            )
        )
        results.append(
            types.InlineQueryResultArticle(
                id="daily_checkin",
                title="📅 每日签到",
                description="固定获得 5 积分（每天限一次）",
                input_message_content=types.InputTextMessageContent(
                    message_text="⏳ 正在签到...",
                ),
                reply_markup=types.InlineKeyboardMarkup(
                    [[types.InlineKeyboardButton(text="⏳", callback_data="noop")]]
                ),
            )
        )

    await query.answer(
        results=results,
        cache_time=0,
        is_personal=True,
        switch_pm_text=i18n.t("bot.inline.switch_pm_text", locale=user_config.lang),
        switch_pm_parameter="inline_query",
    )
    logger.debug(f"Inline query answered with {len(results)} results for user {user.id}")


@Client.on_chosen_inline_result()
async def chosen_inline_result(client: Client, result: types.ChosenInlineResult):
    import time
    _cir_t0 = time.time()
    user = result.from_user
    logger.info(f"chosen_inline_result: result_id={result.result_id}, inline_message_id={result.inline_message_id!r}, user={user.id}")
    info = None
    try:
        info = hack.resolve_inline_message_id(result.inline_message_id)
    except Exception as e:
        logger.warning(f"Failed to resolve inline message id: {e}")
    if info is None:
        await client.edit_inline_text(
            inline_message_id=result.inline_message_id,
            text="解析消息失败了呢，请稍后再试",
        )
        return

    try:
        await _handle_checkin(client, result, user, info)
    except Exception as e:
        logger.exception(f"chosen_inline_result error: {e}")


async def _handle_checkin(client, result, user, info):
    safe_name = (
        user.first_name
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    mention = f'<a href="tg://user?id={user.id}">{safe_name}</a>'

    if result.result_id == "daily_checkin":
        if await database.has_any_checkin_today(user.id, info.chat_id):
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text="⚠️ 今天已经签到过了哦～",
            )
            asyncio.create_task(
                _delete_after(client, info.chat_id, info.message_id, _AUTO_DELETE_DELAY)
            )
            return
        user_points = await database.record_checkin_and_add_points(
            user.id, info.chat_id, "daily", 5
        )
        await client.edit_inline_text(
            inline_message_id=result.inline_message_id,
            text=(
                f"✅ {mention} 签到成功！\n\n"
                f"获得积分：<b>+5</b>\n"
                f"当前积分：<b>{user_points.points}</b>"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        asyncio.create_task(
            _delete_after(client, info.chat_id, info.message_id, _AUTO_DELETE_DELAY)
        )

    elif result.result_id == "slot_checkin":
        daily_count = await database.get_checkin_count_today(user.id, info.chat_id, "daily")
        if daily_count >= 1:
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text="⚠️ 今天已经进行过普通签到了，不能再摇老虎机啦～",
            )
            asyncio.create_task(
                _delete_after(client, info.chat_id, info.message_id, _AUTO_DELETE_DELAY)
            )
            return
        slot_count = await database.get_checkin_count_today(user.id, info.chat_id, "slot")
        if slot_count >= _SLOT_MAX_DAILY:
            await client.edit_inline_text(
                inline_message_id=result.inline_message_id,
                text=f"⚠️ 今天老虎机已用完 {_SLOT_MAX_DAILY} 次啦～",
            )
            asyncio.create_task(
                _delete_after(client, info.chat_id, info.message_id, _AUTO_DELETE_DELAY)
            )
            return
        value = random.randint(1, 64)
        points = _SLOT_POINTS_MAP.get(value, 1)
        pattern = _decode_slot_pattern(value)
        user_points = await database.record_checkin_and_add_points(
            user.id, info.chat_id, "slot", points
        )
        remaining = _SLOT_MAX_DAILY - slot_count - 1
        if points == 50:
            prize_text = "🎉 <b>超级大奖！</b> 777！"
        elif points == 30:
            prize_text = "🌟 <b>大奖！</b> BAR BAR BAR！"
        elif points == 15:
            prize_text = "✨ <b>不错！</b> 三葡萄！"
        elif points == 5:
            prize_text = "👍 <b>小奖！</b> 三柠檬！"
        else:
            prize_text = "😅 <b>安慰奖</b>"
        await client.edit_inline_text(
            inline_message_id=result.inline_message_id,
            text=(
                f"🎰 {mention} 的老虎机结果：\n\n"
                f"{pattern}\n\n"
                f"{prize_text}\n"
                f"获得积分：<b>+{points}</b>\n"
                f"当前积分：<b>{user_points.points}</b>\n"
                f"今日剩余次数：<b>{remaining}</b>"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        # 安慰奖自动删除，中奖消息保留
        if points <= 1:
            asyncio.create_task(
                _delete_after(client, info.chat_id, info.message_id, _AUTO_DELETE_DELAY)
            )
