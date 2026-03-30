"""积分排行榜插件

/rank - 查看本群积分排行榜，支持翻页按钮。
显示：排名、用户昵称、连续签到天数、积分。
"""
import asyncio
import math
import re

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
from kmua.logger import logger

_PAGE_SIZE = 10
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_rank_text(
    rows,
    streaks: dict[int, int],
    page: int,
    total: int,
    chat_title: str,
) -> str:
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    lines = [
        f"🏆 <b>{_escape(chat_title)} 积分排行榜</b>"
        f"（第 {page + 1}/{total_pages} 页）\n"
    ]
    for i, (user_points, full_name) in enumerate(rows):
        rank = page * _PAGE_SIZE + i + 1
        streak = streaks.get(user_points.user_id, 0)
        streak_text = f"🔥{streak}天" if streak > 1 else "——"
        name = full_name[:14] + "…" if len(full_name) > 14 else full_name
        medal = _MEDALS.get(rank, f"{rank}.")
        mention = f'<a href="tg://user?id={user_points.user_id}">{_escape(name)}</a>'
        lines.append(
            f"{medal} {mention}  {streak_text}  <b>{user_points.points}</b>分"
        )
    return "\n".join(lines)


def _build_keyboard(chat_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(total / _PAGE_SIZE))
    buttons = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                "◀ 上一页", callback_data=f"rank:{chat_id}:{page - 1}"
            )
        )
    if page < total_pages - 1:
        buttons.append(
            InlineKeyboardButton(
                "下一页 ▶", callback_data=f"rank:{chat_id}:{page + 1}"
            )
        )
    return InlineKeyboardMarkup([buttons]) if buttons else None


async def _fetch_page(chat_id: int, page: int, chat_title: str):
    """获取指定页的排行榜数据，返回 (text, keyboard)"""
    total = await database.get_leaderboard_total(chat_id)
    if total == 0:
        return "本群暂无积分数据～", None

    rows = await database.get_chat_leaderboard_page(
        chat_id, page=page, page_size=_PAGE_SIZE
    )
    if not rows:
        return "该页暂无数据～", None

    # 并发获取每位用户的连续签到天数
    user_ids = [up.user_id for up, _ in rows]
    streak_results = await asyncio.gather(
        *[database.get_consecutive_streak(uid, chat_id) for uid in user_ids]
    )
    streaks = dict(zip(user_ids, streak_results))

    text = _build_rank_text(rows, streaks, page=page, total=total, chat_title=chat_title)
    keyboard = _build_keyboard(chat_id, page=page, total=total)
    return text, keyboard


@Client.on_message(filters.command("rank") & filters.group)
async def rank_command(client: Client, message: Message):
    """查看本群积分排行榜"""
    chat_id = message.chat.id
    chat_title = message.chat.title or "本群"

    # 先发占位消息：初次发送若含 tg://user 链接会触发通知，编辑则不会
    placeholder = await message.reply_text("⏳ 加载排行榜中...")
    text, keyboard = await _fetch_page(chat_id, page=0, chat_title=chat_title)
    await placeholder.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    logger.info(f"rank: chat={chat_id}")


@Client.on_callback_query(filters.regex(r"^rank:(-?\d+):(\d+)$"))
async def rank_page_callback(client: Client, callback: CallbackQuery):
    """处理排行榜翻页按钮"""
    m = re.match(r"^rank:(-?\d+):(\d+)$", callback.data)
    if not m:
        await callback.answer()
        return

    chat_id = int(m.group(1))
    page = int(m.group(2))

    # 安全校验：只能操作消息所在的群
    if callback.message and callback.message.chat.id != chat_id:
        await callback.answer("不能操作其他群组的排行榜", show_alert=True)
        return

    chat_title = (
        callback.message.chat.title if callback.message else "本群"
    ) or "本群"

    text, keyboard = await _fetch_page(chat_id, page=page, chat_title=chat_title)
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await callback.answer()
