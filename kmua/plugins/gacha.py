"""
集换卡牌系统插件
触发方式：/gacha 指令唤起菜单，/trade 指令发起交易
所有操作通过 InlineKeyboard 回调完成
"""
import asyncio
import io
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 使用 UTC+8 时区用于日期计算
TZ_UTC8 = timezone(timedelta(hours=8))

from PIL import Image, ImageDraw, ImageFont
from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from kmua import database
from kmua.config import app_config
from kmua.database.gacha import RARITY_LABELS
from kmua.logger import logger
from kmua.common.message_queue import enqueue_message_operation, get_queue_size
from kmua.common.animation_cache import get_single_draw_animation

_AUTO_DELETE_DELAY = 30
_drawing_locks: set[str] = set()  # 防重复点击: "{user_id}_{action}"

# ==================== 群白名单和黑名单管理 ====================

# 卡牌系统仅在以下群中可用
_ALLOWED_GROUPS: set[int] = {-1002434265967, -1003872095297}

_BLACKLIST_PATH = Path("/kmua/data/gacha_blacklist.json")
_blacklist_cache: set[int] = set()


def _load_blacklist() -> set[int]:
    global _blacklist_cache
    if _BLACKLIST_PATH.exists():
        try:
            data = json.loads(_BLACKLIST_PATH.read_text())
            _blacklist_cache = set(data)
        except (json.JSONDecodeError, TypeError):
            _blacklist_cache = set()
    return _blacklist_cache


def _save_blacklist():
    _BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BLACKLIST_PATH.write_text(json.dumps(list(_blacklist_cache)))


def _is_banned(user_id: int) -> bool:
    if not _blacklist_cache:
        _load_blacklist()
    return user_id in _blacklist_cache


def _is_group_allowed(chat_id: int) -> bool:
    """检查群是否在白名单中"""
    return chat_id in _ALLOWED_GROUPS


_load_blacklist()

RARITY_EMOJI = {
    "common": "⬜",
    "rare": "🟦",
    "epic": "🟪",
    "legendary": "🟨",
}


_GRID_COLS = 5
_GRID_ROWS = 2
_CELL_W = 320
_CELL_H = 448
_GAP = 10
_GRID_W = _GRID_COLS * _CELL_W + (_GRID_COLS - 1) * _GAP
_GRID_H = _GRID_ROWS * _CELL_H + (_GRID_ROWS - 1) * _GAP


def _load_pil_font(size):
    for path in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _cell_position(idx: int) -> tuple[int, int]:
    """计算第 idx 张卡在网格中的左上角坐标"""
    col = idx % _GRID_COLS
    row = idx // _GRID_COLS
    return col * (_CELL_W + _GAP), row * (_CELL_H + _GAP)


def _generate_multi_draw_png(card_numbers: list[int], season_id: int) -> bytes:
    """生成十连网格高清 PNG（5×2 横向布局），卡名已在卡面图上"""
    t0 = time.time()
    base = f"/kmua/data/cards/season_{season_id}"
    bg_color = (25, 25, 30)

    face_pngs = []
    for num in card_numbers:
        face = Image.open(f"{base}/card_{num:02d}.png").convert("RGB")
        face_pngs.append(face.resize((_CELL_W, _CELL_H), Image.Resampling.LANCZOS))

    png_grid = Image.new("RGB", (_GRID_W, _GRID_H), bg_color)
    for idx, face in enumerate(face_pngs):
        png_grid.paste(face, _cell_position(idx))

    png_buf = io.BytesIO()
    png_grid.save(png_buf, format="PNG")
    png_bytes = png_buf.getvalue()

    logger.info(f"[gacha] multi-draw PNG generated in {time.time()-t0:.2f}s, size={len(png_bytes)//1024}KB")
    return png_bytes


def _generate_single_draw_mp4(card_number: int, season_id: int) -> bytes:
    """生成单抽翻牌 MP4 动画（单卡居中，流式编码）"""
    import subprocess
    import tempfile
    t0 = time.time()

    import os
    base = f"/kmua/data/cards/season_{season_id}"
    personal_back = f"{base}/card_{card_number:02d}_back.png"
    generic_back = "/kmua/data/cards/card_back.png"
    back_path = personal_back if os.path.exists(personal_back) else generic_back
    back_img = Image.open(back_path).convert("RGB")
    face_img = Image.open(f"{base}/card_{card_number:02d}.png").convert("RGB")

    card_w, card_h = 384, 538
    pad = 20
    canvas_w = card_w + pad * 2
    canvas_h = card_h + pad * 2
    bg_color = (25, 25, 30)

    back_cell = back_img.resize((card_w, card_h), Image.Resampling.BILINEAR)
    face_cell = face_img.resize((card_w, card_h), Image.Resampling.BILINEAR)

    fps = 15
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    frame_count = 0
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{canvas_w}x{canvas_h}", "-pix_fmt", "rgb24", "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            tmp_path,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pipe = proc.stdin

        canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
        canvas.paste(back_cell, (pad, pad))

        # 开场卡背静止: 10帧 (667ms)
        static_bytes = canvas.tobytes()
        for _ in range(10):
            pipe.write(static_bytes)
            frame_count += 1

        # 翻转动画: 20帧 (1.33s)
        flip_count = 20
        for i in range(flip_count):
            t = i / (flip_count - 1)
            width_ratio = abs(math.cos(t * math.pi))
            width_ratio = max(0.08, width_ratio)
            src = back_cell if i < flip_count // 2 else face_cell
            squeeze_w = max(4, int(card_w * width_ratio))
            squeezed = src.resize((squeeze_w, card_h), Image.Resampling.NEAREST)

            canvas_frame = Image.new("RGB", (canvas_w, canvas_h), bg_color)
            x_offset = pad + (card_w - squeeze_w) // 2
            canvas_frame.paste(squeezed, (x_offset, pad))
            pipe.write(canvas_frame.tobytes())
            frame_count += 1

        # 卡面定格: 20帧 (1.33s)
        canvas.paste(face_cell, (pad, pad))
        static_bytes = canvas.tobytes()
        for _ in range(20):
            pipe.write(static_bytes)
            frame_count += 1

        pipe.close()
        proc.wait()

        if proc.returncode != 0:
            err = proc.stderr.read().decode(errors="replace")
            logger.warning(f"[gacha] single-draw ffmpeg error: {err[:300]}")
            return b""

        import os
        with open(tmp_path, "rb") as f:
            mp4_bytes = f.read()
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    logger.info(f"[gacha] single-draw MP4 generated in {time.time()-t0:.2f}s, frames={frame_count}, size={len(mp4_bytes)//1024}KB")
    return mp4_bytes


def _generate_multi_draw_mp4(card_numbers: list[int], season_id: int) -> bytes:
    """生成十连翻牌 MP4 动画（5×2 横向布局，流式编码优化版）"""
    import subprocess
    import tempfile
    t0 = time.time()

    import os
    base = f"/kmua/data/cards/season_{season_id}"
    generic_back = "/kmua/data/cards/card_back.png"

    back_cells = []
    faces = []
    for num in card_numbers:
        personal_back = f"{base}/card_{num:02d}_back.png"
        back_path = personal_back if os.path.exists(personal_back) else generic_back
        back_img = Image.open(back_path).convert("RGB")
        back_cells.append(back_img.resize((_CELL_W, _CELL_H), Image.Resampling.LANCZOS))

        face = Image.open(f"{base}/card_{num:02d}.png").convert("RGB")
        faces.append(face.resize((_CELL_W, _CELL_H), Image.Resampling.LANCZOS))

    bg_color = (25, 25, 30)
    current = Image.new("RGB", (_GRID_W, _GRID_H), bg_color)
    for idx in range(10):
        current.paste(back_cells[idx], _cell_position(idx))

    fps = 12
    w, h = _GRID_W, _GRID_H
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    frame_count = 0
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{w}x{h}", "-pix_fmt", "rgb24", "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "25", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            tmp_path,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pipe = proc.stdin

        # 开场静止: 3帧 (250ms)
        static_bytes = current.tobytes()
        for _ in range(3):
            pipe.write(static_bytes)
            frame_count += 1

        # 逐张翻牌: 4步翻转 + 1帧停顿展示
        flip_steps = [0.0, 0.3, 0.6, 1.0]
        for i in range(10):
            x, y = _cell_position(i)
            for step in flip_steps:
                width_ratio = abs(math.cos(step * math.pi))
                width_ratio = max(0.08, width_ratio)
                src = back_cells[i] if step < 0.5 else faces[i]
                squeeze_w = max(4, int(_CELL_W * width_ratio))
                squeezed = src.resize((squeeze_w, _CELL_H), Image.Resampling.NEAREST)

                cell = Image.new("RGB", (_CELL_W, _CELL_H), bg_color)
                cell.paste(squeezed, ((_CELL_W - squeeze_w) // 2, 0))
                current.paste(cell, (x, y))
                pipe.write(current.tobytes())
                frame_count += 1

            current.paste(faces[i], (x, y))

            # 翻完后停顿1帧展示
            pipe.write(current.tobytes())
            frame_count += 1

        # 结尾定格: 10帧 (~830ms)
        static_bytes = current.tobytes()
        for _ in range(10):
            pipe.write(static_bytes)
            frame_count += 1

        pipe.close()
        proc.wait()

        if proc.returncode != 0:
            err = proc.stderr.read().decode(errors="replace")
            logger.warning(f"[gacha] ffmpeg error: {err[:300]}")
            return b""

        import os
        with open(tmp_path, "rb") as f:
            mp4_bytes = f.read()
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    logger.info(f"[gacha] multi-draw MP4 generated in {time.time()-t0:.2f}s, frames={frame_count}, size={len(mp4_bytes)//1024}KB")
    return mp4_bytes


# ==================== 9宫格图片生成 ====================

_PAGE_COLS, _PAGE_ROWS = 3, 3
_PAGE_SIZE = _PAGE_COLS * _PAGE_ROWS
_PG_CELL_W, _PG_CELL_H = 340, 476
_PG_GAP = 10
_PG_GRID_W = _PAGE_COLS * _PG_CELL_W + (_PAGE_COLS - 1) * _PG_GAP
_PG_GRID_H = _PAGE_ROWS * _PG_CELL_H + (_PAGE_ROWS - 1) * _PG_GAP


def _generate_card_grid(
    card_infos: list[dict],
    season_id: int,
) -> bytes:
    """生成 3×3 卡牌网格 PNG，卡名已在卡面图上。
    card_infos: [{"card_number": int, "owned": bool, "count": int|None, "name": str, "rarity": str}]
    """
    bg_color = (25, 25, 30)
    grid = Image.new("RGBA", (_PG_GRID_W, _PG_GRID_H), bg_color + (255,))
    base = f"/kmua/data/cards/season_{season_id}"
    badge_font = _load_pil_font(28)

    for idx, info in enumerate(card_infos):
        if idx >= _PAGE_SIZE:
            break
        col = idx % _PAGE_COLS
        row = idx // _PAGE_COLS
        x = col * (_PG_CELL_W + _PG_GAP)
        y = row * (_PG_CELL_H + _PG_GAP)

        if not info.get("owned", True) and not info.get("unlocked"):
            # State 3: 未解锁 — 完全隐藏卡面，纯色占位 + "?"
            cell = Image.new("RGBA", (_PG_CELL_W, _PG_CELL_H), (30, 30, 38, 255))
            draw = ImageDraw.Draw(cell)
            q_font = _load_pil_font(72)
            draw.text((_PG_CELL_W // 2, _PG_CELL_H // 2), "?", fill=(80, 80, 90), font=q_font, anchor="mm")
        else:
            img_path = f"{base}/card_{info['card_number']:02d}.png"
            try:
                card_img = Image.open(img_path).convert("RGBA")
                cell = card_img.resize((_PG_CELL_W, _PG_CELL_H), Image.Resampling.LANCZOS)
            except Exception:
                cell = Image.new("RGBA", (_PG_CELL_W, _PG_CELL_H), (40, 40, 50, 255))

            if not info.get("owned", True):
                # State 2: 解锁但未拥有 — 卡面可见但灰度
                cell = cell.convert("L").convert("RGBA")

        grid.paste(cell, (x, y), cell)

        # 重复数标注（左上角，半透明圆角矩形 pill）
        if info.get("count") and info["count"] > 1:
            label = f"×{info['count']}"
            bbox = badge_font.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x, pad_y = 8, 5
            pill_w = tw + pad_x * 2
            pill_h = th + pad_y * 2
            badge_x = x + 8
            badge_y = y + 8

            overlay = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
            ov_draw = ImageDraw.Draw(overlay)
            ov_draw.rounded_rectangle(
                [0, 0, pill_w - 1, pill_h - 1],
                radius=pill_h // 2,
                fill=(0, 0, 0, 180),
            )
            ov_draw.text((pad_x, pad_y - bbox[1]), label, fill=(255, 255, 255), font=badge_font)
            grid.paste(overlay, (badge_x, badge_y), overlay)

    buf = io.BytesIO()
    output = Image.new("RGB", grid.size, (25, 25, 30))
    output.paste(grid, mask=grid.split()[3])
    output.save(buf, format="PNG")
    return buf.getvalue()


async def _auto_delete(msg: Message, delay: int = _AUTO_DELETE_DELAY) -> None:
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass


async def _replace_gif_with_photo(client: Client, msg: Message, photo_path: str, caption: str = "", delay: float = 1.5) -> None:
    """等翻牌动画播完后，把 GIF 替换为静态卡图"""
    try:
        await asyncio.sleep(delay)
        media_kwargs = {"media": photo_path}
        if caption:
            media_kwargs["caption"] = caption
            media_kwargs["parse_mode"] = ParseMode.HTML
        await client.edit_message_media(
            chat_id=msg.chat.id,
            message_id=msg.id,
            media=InputMediaPhoto(**media_kwargs),
        )
    except Exception as e:
        logger.debug(f"Replace gif->photo failed (may be deleted): {e}")




# ==================== 主菜单入口 ====================


def _main_menu_keyboard(user_id: int, chat_id: int, topic_msg: int = 0, is_active: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if is_active:
        rows.append([
            InlineKeyboardButton("🎴 抽卡", callback_data=f"gc_d_{user_id}_{chat_id}_{topic_msg}"),
            InlineKeyboardButton("🎴×10 十连", callback_data=f"gc_m_{user_id}_{chat_id}_{topic_msg}"),
        ])
    rows.append([
        InlineKeyboardButton("📖 卡册", callback_data=f"gc_c_{user_id}_{chat_id}_{topic_msg}"),
        InlineKeyboardButton("🎁 特典", callback_data=f"gc_t_{user_id}_{chat_id}_{topic_msg}"),
    ])
    rows.append([
        InlineKeyboardButton("🃏 信息", callback_data=f"gc_s_{user_id}_{chat_id}_{topic_msg}"),
    ])
    return InlineKeyboardMarkup(rows)


# ==================== 特典解锁检查辅助函数 ====================


async def _check_and_unlock_tokuten(
    client: Client,
    chat_id: int,
    user_id: int,
    season_id: int,
    topic_msg: int,
):
    """检查用户是否集齐32张卡并解锁特典奖励"""
    try:
        # 检查用户当前拥有的不重复卡片数
        unique_count = await database.get_user_unique_count(user_id, chat_id, season_id)

        # 获取赛季信息
        season = await database.get_season_by_id(season_id)
        if not season:
            return

        # 如果还没集齐32张,不触发
        if unique_count < season.total_cards:
            return

        # 检查是否已经解锁过特典
        already_unlocked = await database.check_tokuten_unlocked(user_id, chat_id, season_id)
        if already_unlocked:
            return

        # 解锁特典
        await database.unlock_tokuten(user_id, chat_id, season_id)

        # 发送祝贺消息
        season_name = season.name
        congrats_text = (
            f"🎊 <b>恭喜解锁特典!</b> 🎊\n\n"
            f"你已集齐 <b>{season_name}</b> 的全部 {season.total_cards} 张卡牌!\n"
            f"特典奖励已解锁,可在卡册中查看～\n\n"
            f"✨ 特典卡片不可交易和兑换,是你收集成就的专属证明!"
        )

        await client.send_message(
            chat_id=chat_id,
            text=congrats_text,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=topic_msg if topic_msg != 0 else None,
        )

        logger.info(f"[gacha] User {user_id} unlocked tokuten for season {season_id}")

    except Exception as e:
        logger.exception(f"[gacha] Failed to check/unlock tokuten: {e}")


# ==================== 黑名单指令 ====================


@Client.on_message(filters.command("gachaban") & filters.group, group=0)
async def gachaban_handler(client: Client, message: Message):
    if not _is_group_allowed(message.chat.id):
        return
    user = message.from_user
    if not user or user.id not in app_config.owners:
        return

    text = (message.text or "").strip()
    parts = text.split()

    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        target_id = target.id
        target_name = target.first_name
    elif len(parts) >= 2 and parts[1].isdigit():
        target_id = int(parts[1])
        target_name = str(target_id)
    else:
        banned_list = _blacklist_cache
        if not banned_list:
            reply = await message.reply_text("当前黑名单为空。\n用法：回复目标用户 /gachaban 或 /gachaban <uid>")
        else:
            lines = [f"• <code>{uid}</code>" for uid in banned_list]
            reply = await message.reply_text(
                f"📋 <b>卡牌黑名单</b>（{len(banned_list)}人）\n" + "\n".join(lines) +
                "\n\n回复目标用户 /gachaban 切换封禁状态",
                parse_mode=ParseMode.HTML,
            )
        asyncio.create_task(_auto_delete(reply, delay=15))
        return

    if target_id in _blacklist_cache:
        _blacklist_cache.discard(target_id)
        _save_blacklist()
        reply = await message.reply_text(f"✅ 已将 {target_name} 移出卡牌黑名单")
    else:
        _blacklist_cache.add(target_id)
        _save_blacklist()
        reply = await message.reply_text(f"🚫 已将 {target_name} 加入卡牌黑名单")
    asyncio.create_task(_auto_delete(reply, delay=10))


@Client.on_message(filters.command("gacha") & filters.group, group=0)
async def gacha_menu_handler(client: Client, message: Message):
    if not _is_group_allowed(message.chat.id):
        return
    user = message.from_user
    if not user:
        return

    if _is_banned(user.id):
        return

    season = await database.get_current_or_latest_season()
    if not season:
        reply = await message.reply_text("当前没有卡牌赛季哦～")
        asyncio.create_task(_auto_delete(reply))
        return

    # 判断赛季是否仍在活跃期内
    now = datetime.now(timezone.utc)
    is_active = season.status == "active" and season.starts_at <= now < season.ends_at

    safe_name = (
        user.first_name
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    mention = f'<a href="tg://user?id={user.id}">{safe_name}</a>'

    unique = await database.get_user_unique_count(user.id, message.chat.id, season.id)

    if is_active:
        today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
        free_count = await database.get_today_free_draw_count(
            user.id, message.chat.id, season.id, today
        )
        free_remaining = max(0, season.daily_free_draws - free_count)
        text = (
            f"🃏 <b>集换卡牌系统</b> — {season.name}\n\n"
            f"{mention} 的状态：\n"
            f"  收集进度：{unique}/{season.total_cards}\n"
            f"  今日免费抽卡：{free_remaining}/{season.daily_free_draws}\n"
            f"  付费单价：{season.draw_price} 积分/抽\n\n"
            f"请选择操作："
        )
    else:
        text = (
            f"🃏 <b>集换卡牌系统</b> — {season.name}（已结束）\n\n"
            f"{mention} 的状态：\n"
            f"  收集进度：{unique}/{season.total_cards}\n\n"
            f"赛季已结束，卡牌永久保留，可查看卡册和图鉴。"
        )

    # 检查是否解锁特典，解锁后显示特典照片
    tokuten = await database.check_tokuten_unlocked(user.id, message.chat.id, season.id)
    logger.info(f"[DEBUG] check_tokuten_unlocked返回: {tokuten}, user_id={user.id}, season_id={season.id}")

    if tokuten:
        # 已解锁：发送特典照片作为菜单
        tokuten_path = "/kmua/data/cards/photo_2026-09-02_14-40-22.jpg"
        await message.reply_photo(
            photo=tokuten_path,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(user.id, message.chat.id, message.id, is_active=is_active),
        )
    else:
        # 未解锁：普通文本菜单
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_keyboard(user.id, message.chat.id, message.id, is_active=is_active),
        )


# ==================== 编辑消息辅助 ====================


async def _edit_text(client: Client, callback: CallbackQuery, text: str, reply_markup=None):
    """统一处理 inline 消息和普通消息的编辑"""
    if callback.message:
        # 检查当前消息是否是媒体消息
        is_media_msg = callback.message.photo or callback.message.animation or callback.message.document

        if is_media_msg:
            # 从图片切换到文本：删除图片消息，发送新文本消息
            try:
                await callback.message.delete()
            except Exception:
                pass
            send_kwargs = dict(
                chat_id=callback.message.chat.id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            # 保持话题回复
            if callback.message.reply_to_message:
                send_kwargs["reply_to_message_id"] = callback.message.reply_to_message.id
            await client.send_message(**send_kwargs)
        else:
            # 从文本切换到文本：直接编辑
            await enqueue_message_operation(
                callback.message.chat.id,
                callback.message.edit_text,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
    else:
        await client.edit_inline_text(
            inline_message_id=callback.inline_message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )


# ==================== 回调统一入口 ====================


@Client.on_callback_query(filters.regex(r"^gc_"))
async def gacha_callback_handler(client: Client, callback: CallbackQuery):
    if callback.message and not _is_group_allowed(callback.message.chat.id):
        await callback.answer("卡牌系统仅在特定群开放", show_alert=True)
        return
    data = callback.data
    user_id = callback.from_user.id

    if _is_banned(user_id):
        await callback.answer("你已被禁止使用卡牌系统", show_alert=True)
        return

    logger.info(f"[gacha] callback received: data={data}, user={user_id}")

    # 解析格式: gc_{action}_{...extra...}_{uid}_{cid}_{topic}
    # uid/cid/topic 始终是最后3段
    parts = data.split("_")
    if len(parts) < 5:
        await callback.answer("无效操作", show_alert=True)
        return

    action = parts[1]
    target_uid = int(parts[-3])
    chat_id = int(parts[-2])
    topic_msg = int(parts[-1])
    extra = parts[2:-3]  # 中间段为额外参数

    if target_uid != user_id:
        await callback.answer("这不是你的菜单哦～", show_alert=True)
        return

    try:
        if action == "d":
            await _cb_draw_check(client, callback, user_id, chat_id, topic_msg)
        elif action == "cd":
            await _cb_draw(client, callback, user_id, chat_id, topic_msg)
        elif action == "m":
            await _cb_multi_draw_check(client, callback, user_id, chat_id, topic_msg)
        elif action == "cm":
            await _cb_multi_draw(client, callback, user_id, chat_id, topic_msg)
        elif action == "c":
            await _cb_collection(client, callback, user_id, chat_id, topic_msg)
        elif action == "cp":
            page = int(extra[0]) if len(extra) > 0 else 1
            sid = int(extra[1]) if len(extra) > 1 else None
            await _cb_collection(client, callback, user_id, chat_id, topic_msg, season_id=sid, page=page)
        elif action == "cs":
            await _cb_collection_season_list(client, callback, user_id, chat_id, topic_msg)
        elif action == "i":
            await _cb_inventory(client, callback, user_id, chat_id, topic_msg, page=1)
        elif action == "ip":
            page = int(extra[0]) if extra else 1
            await _cb_inventory(client, callback, user_id, chat_id, topic_msg, page=page)
        elif action == "a":
            await _cb_album(client, callback, user_id, chat_id, topic_msg)
        elif action == "as":
            sid = int(extra[0]) if extra else 1
            await _cb_album_season(client, callback, user_id, chat_id, topic_msg, season_id=sid, page=1)
        elif action == "ap":
            sid = int(extra[0]) if len(extra) > 0 else 1
            page = int(extra[1]) if len(extra) > 1 else 1
            await _cb_album_season(client, callback, user_id, chat_id, topic_msg, season_id=sid, page=page)
        elif action == "cv":
            card_num = int(extra[0]) if len(extra) > 0 else 1
            sid = int(extra[1]) if len(extra) > 1 else 1
            source = extra[2] if len(extra) > 2 else "i"
            source_page = int(extra[3]) if len(extra) > 3 else 1
            await _cb_view_card(client, callback, user_id, chat_id, topic_msg, season_id=sid, card_number=card_num, source=source, source_page=source_page)
        elif action == "vb":
            # 查看卡背
            card_num = int(extra[0]) if len(extra) > 0 else 1
            sid = int(extra[1]) if len(extra) > 1 else 1
            source = extra[2] if len(extra) > 2 else "i"
            source_page = int(extra[3]) if len(extra) > 3 else 1
            await _cb_view_card_back(client, callback, user_id, chat_id, topic_msg, season_id=sid, card_number=card_num, source=source, source_page=source_page)
        elif action == "vf":
            # 查看卡正面（从卡背翻转回来）
            card_num = int(extra[0]) if len(extra) > 0 else 1
            sid = int(extra[1]) if len(extra) > 1 else 1
            source = extra[2] if len(extra) > 2 else "i"
            source_page = int(extra[3]) if len(extra) > 3 else 1
            await _cb_view_card_front(client, callback, user_id, chat_id, topic_msg, season_id=sid, card_number=card_num, source=source, source_page=source_page)
        elif action == "del":
            # 关闭按钮：返回主菜单而不是删除消息
            await _cb_back_to_menu(client, callback, user_id, chat_id, topic_msg)
        elif action == "r":
            await _cb_redeem(client, callback, user_id, chat_id, topic_msg)
        elif action == "s":
            await _cb_season_info(client, callback, user_id, chat_id, topic_msg)
        elif action == "t":
            await _cb_tokuten(client, callback, user_id, chat_id, topic_msg)
        elif action == "b":
            # 普通返回：不显示特典图片
            await _cb_back_to_menu(client, callback, user_id, chat_id, topic_msg, show_tokuten_photo=False)
        elif action == "bt":
            # 从特典返回：显示特典图片
            await _cb_back_to_menu(client, callback, user_id, chat_id, topic_msg, show_tokuten_photo=True)
    except Exception as e:
        logger.exception(f"[gacha] handler error: action={action}, err={e}")
        await callback.answer(f"操作出错了: {e}", show_alert=True)


# ==================== 抽卡 ====================


async def _cb_draw_check(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    """单抽前检查：免费直接抽，付费显示确认按钮"""
    season = await database.get_active_season()
    if not season:
        await callback.answer("没有进行中的赛季", show_alert=True)
        return
    today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
    free_count = await database.get_today_free_draw_count(user_id, chat_id, season.id, today)
    if free_count < season.daily_free_draws:
        await _cb_draw(client, callback, user_id, chat_id, topic_msg)
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"✅ 确认 (-{season.draw_price}积分)", callback_data=f"gc_cd_{user_id}_{chat_id}_{topic_msg}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}"),
            ]
        ])
        await _edit_text(
            client, callback,
            f"🎴 免费次数已用完\n本次抽卡消耗：<b>{season.draw_price} 积分</b>",
            reply_markup=keyboard,
        )
        await callback.answer()


async def _cb_multi_draw_check(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    """十连前检查：全免费直接抽，有付费部分显示确认按钮"""
    season = await database.get_active_season()
    if not season:
        await callback.answer("没有进行中的赛季", show_alert=True)
        return
    today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
    free_count = await database.get_today_free_draw_count(user_id, chat_id, season.id, today)
    actual_free = min(10, max(0, season.daily_free_draws - free_count))
    paid_count = 10 - actual_free
    total_cost = paid_count * season.draw_price

    if total_cost == 0:
        await _cb_multi_draw(client, callback, user_id, chat_id, topic_msg)
    else:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"✅ 确认 (-{total_cost}积分)", callback_data=f"gc_cm_{user_id}_{chat_id}_{topic_msg}"),
                InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}"),
            ]
        ])
        await _edit_text(
            client, callback,
            f"🎴×10 本次十连消耗：<b>{total_cost} 积分</b>\n"
            f"（{actual_free}免费 + {paid_count}付费）",
            reply_markup=keyboard,
        )
        await callback.answer()


async def _cb_draw(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    lock_key = f"{user_id}_draw"
    if lock_key in _drawing_locks:
        await callback.answer("正在生成中，请稍等～", show_alert=False)
        return
    _drawing_locks.add(lock_key)
    try:
        await _cb_draw_inner(client, callback, user_id, chat_id, topic_msg)
    finally:
        _drawing_locks.discard(lock_key)


async def _cb_draw_inner(client, callback, user_id, chat_id, topic_msg):
    logger.info(f"[gacha] _cb_draw start: user={user_id}, chat={chat_id}")
    season = await database.get_active_season()
    if not season:
        await callback.answer("没有进行中的赛季", show_alert=True)
        return

    today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
    free_count = await database.get_today_free_draw_count(
        user_id, chat_id, season.id, today
    )

    is_free = free_count < season.daily_free_draws
    if not is_free:
        try:
            await database.cost_points(
                user_id, chat_id, season.draw_price,
                reason=f"卡牌抽取(赛季{season.id})"
            )
        except ValueError:
            await callback.answer(
                f"积分不足！需要 {season.draw_price} 积分（免费次数已用完）",
                show_alert=True,
            )
            return

    try:
        card, pity = await database.perform_draw(
            user_id, chat_id, season.id, is_free, today
        )
    except Exception:
        if not is_free:
            await database.add_points(
                user_id, chat_id, season.draw_price,
                reason=f"抽卡异常退还(赛季{season.id})"
            )
        raise

    emoji = RARITY_EMOJI.get(card.rarity, "⬜")
    rarity_name = RARITY_LABELS.get(card.rarity, card.rarity)
    pity_text = ""
    if pity == "legendary":
        pity_text = "\n🎊 <b>传说保底触发！</b>"
    elif pity == "dedup":
        pity_text = "\n✨ <b>去重保底！获得新卡！</b>"

    cost_text = "免费" if is_free else f"-{season.draw_price}积分"
    new_free_count = free_count + (1 if is_free else 0)
    free_remaining = max(0, season.daily_free_draws - new_free_count)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎴 再抽一次", callback_data=f"gc_d_{user_id}_{chat_id}_{topic_msg}"),
            InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}"),
        ]
    ])

    # 更新菜单显示剩余次数
    await _edit_text(
        client, callback,
        f"🎴 已抽卡 ({cost_text})\n"
        f"今日剩余免费：{free_remaining}/{season.daily_free_draws}",
        reply_markup=keyboard,
    )

    # 发送翻牌MP4到群聊
    player_name = callback.from_user.first_name if callback.from_user else "旅行者"
    draw_caption = f"🎴 <b>{player_name} 的抽卡结果</b>\n{emoji}【{rarity_name}】{card.name}{pity_text}"
    try:
        # 优先使用预生成的动画缓存
        mp4_bytes = get_single_draw_animation(season.id, card.card_number)

        # 如果缓存不存在，实时生成（降级方案）
        if not mp4_bytes:
            logger.info(f"[gacha] Cache miss for card {card.card_number}, generating on-the-fly")
            mp4_bytes = await asyncio.to_thread(
                _generate_single_draw_mp4, card.card_number, season.id
            )

        if mp4_bytes:
            mp4_io = io.BytesIO(mp4_bytes)
            mp4_io.name = "single_draw.mp4"
            send_kwargs = dict(
                chat_id=chat_id,
                animation=mp4_io,
            )
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            msg = await client.send_animation(**send_kwargs)
            png_path = f"/kmua/data/cards/season_{season.id}/card_{card.card_number:02d}.png"
            asyncio.create_task(_replace_gif_with_photo(client, msg, png_path, draw_caption, delay=4.0))
        else:
            png_path = f"/kmua/data/cards/season_{season.id}/card_{card.card_number:02d}.png"
            send_kwargs = dict(chat_id=chat_id, photo=png_path, caption=draw_caption, parse_mode=ParseMode.HTML)
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            msg = await client.send_photo(**send_kwargs)
        # 传说卡保留不删除
        if card.rarity != "legendary":
            asyncio.create_task(_auto_delete(msg, 45))
    except Exception as e:
        logger.warning(f"Failed to send card animation: {e}")

    # 检查是否解锁特典
    await _check_and_unlock_tokuten(client, chat_id, user_id, season.id, topic_msg)

    await callback.answer()
# ==================== 十连抽 ====================


async def _cb_multi_draw(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    t_start = time.time()

    lock_key = f"{user_id}_multi"
    if lock_key in _drawing_locks:
        await callback.answer("正在生成中，请稍等～", show_alert=False)
        return
    _drawing_locks.add(lock_key)

    try:
        await _cb_multi_draw_inner(client, callback, user_id, chat_id, topic_msg, t_start)
    finally:
        _drawing_locks.discard(lock_key)


async def _cb_multi_draw_inner(client, callback, user_id, chat_id, topic_msg, t_start):
    season = await database.get_active_season()
    if not season:
        await callback.answer("没有进行中的赛季", show_alert=True)
        return

    count = 10
    today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
    free_count = await database.get_today_free_draw_count(
        user_id, chat_id, season.id, today
    )
    actual_free_used = min(count, max(0, season.daily_free_draws - free_count))
    paid_count = count - actual_free_used
    total_cost = paid_count * season.draw_price

    if total_cost > 0:
        try:
            await database.cost_points(
                user_id, chat_id, total_cost,
                reason=f"十连抽(赛季{season.id})"
            )
        except ValueError:
            await callback.answer(
                f"积分不足！需要 {total_cost} 积分（{actual_free_used}免+{paid_count}付费）",
                show_alert=True,
            )
            return

    # 抽10张卡
    await callback.answer()
    cards_drawn = []
    try:
        for i in range(count):
            is_free = i < actual_free_used
            card, pity = await database.perform_draw(
                user_id, chat_id, season.id, is_free, today
            )
            cards_drawn.append((card, pity))
    except Exception:
        if total_cost > 0:
            await database.add_points(
                user_id, chat_id, total_cost,
                reason=f"十连异常退还(赛季{season.id})"
            )
        raise

    cost_text = f"免费{actual_free_used}"
    if paid_count > 0:
        cost_text += f"+付费{paid_count}(-{total_cost}积分)"

    new_free_count = free_count + actual_free_used
    free_remaining = max(0, season.daily_free_draws - new_free_count)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎴×10 再来十连", callback_data=f"gc_m_{user_id}_{chat_id}_{topic_msg}"),
            InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}"),
        ]
    ])

    # 更新菜单
    await _edit_text(
        client, callback,
        f"🎴 十连完成 ({cost_text})\n"
        f"今日剩余免费：{free_remaining}/{season.daily_free_draws}",
        reply_markup=keyboard,
    )

    # 生成十连网格 GIF + PNG
    card_numbers = [card.card_number for card, _ in cards_drawn]
    has_legendary = any(card.rarity == "legendary" for card, _ in cards_drawn)

    # 构建十连结果文字
    draw_lines = []
    for card, pity in cards_drawn:
        emoji = RARITY_EMOJI.get(card.rarity, "⬜")
        rarity_name = RARITY_LABELS.get(card.rarity, card.rarity)
        line = f"{emoji}【{rarity_name}】{card.name}"
        if pity == "legendary":
            line += " 🎊保底"
        elif pity == "dedup":
            line += " ✨去重"
        draw_lines.append(line)
    player_name = callback.from_user.first_name if callback.from_user else "旅行者"
    multi_caption = f"🎴 <b>{player_name} 的十连结果</b>\n" + "\n".join(draw_lines)

    try:
        mp4_bytes, png_bytes = await asyncio.gather(
            asyncio.to_thread(_generate_multi_draw_mp4, card_numbers, season.id),
            asyncio.to_thread(_generate_multi_draw_png, card_numbers, season.id),
        )

        if mp4_bytes:
            mp4_io = io.BytesIO(mp4_bytes)
            mp4_io.name = "multi_draw.mp4"
            send_kwargs = dict(
                chat_id=chat_id,
                animation=mp4_io,
            )
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            msg = await client.send_animation(**send_kwargs)
            logger.info(f"[gacha] multi-draw total click-to-send: {time.time()-t_start:.2f}s")

            async def _replace_with_grid():
                await asyncio.sleep(6.0)
                try:
                    png_io = io.BytesIO(png_bytes)
                    png_io.name = "multi_draw.png"
                    await client.edit_message_media(
                        chat_id=msg.chat.id,
                        message_id=msg.id,
                        media=InputMediaPhoto(media=png_io, caption=multi_caption),
                    )
                except Exception as e:
                    logger.debug(f"Replace multi-draw grid failed: {e}")

            asyncio.create_task(_replace_with_grid())
        else:
            png_io = io.BytesIO(png_bytes)
            png_io.name = "multi_draw.png"
            send_kwargs = dict(chat_id=chat_id, photo=png_io, caption=multi_caption)
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            msg = await client.send_photo(**send_kwargs)
            logger.info(f"[gacha] multi-draw fallback PNG sent: {time.time()-t_start:.2f}s")

        # 非传说十连 60s 后删除
        if not has_legendary:
            asyncio.create_task(_auto_delete(msg, 60))
    except Exception as e:
        logger.warning(f"Failed to send multi-draw grid: {e}")

    # 检查是否解锁特典
    await _check_and_unlock_tokuten(client, chat_id, user_id, season.id, topic_msg)


# ==================== 卡册（统一视图） ====================


async def _cb_collection(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, season_id: int | None = None, page: int = 1):
    """统一卡册视图：展示赛季所有卡的 3 种状态"""
    # If no season_id specified, use current or latest season
    if season_id is None:
        season = await database.get_current_or_latest_season()
        if not season:
            # Fall back to season list
            await _cb_collection_season_list(client, callback, user_id, chat_id, topic_msg)
            return
        season_id = season.id
    else:
        season = await database.get_season_by_id(season_id)
        if not season:
            await callback.answer("赛季不存在", show_alert=True)
            return

    # Get ALL cards in this season
    all_cards = await database.get_season_cards(season_id)

    # Get user's OWNED cards in this chat (card_def_id -> count)
    owned_data = await database.get_user_cards(user_id, chat_id, season_id)
    owned_map = {cd.id: count for cd, count in owned_data}

    # Get user's ALBUM (ever unlocked)
    album_data = await database.get_user_album(user_id, season_id)
    album_set = {entry[1].id for entry in album_data}

    # Pagination
    total_pages = max(1, math.ceil(len(all_cards) / _PAGE_SIZE))
    page = max(1, min(page, total_pages))
    page_cards = all_cards[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]

    # Build card_infos with 3 states
    card_infos = []
    for cd in page_cards:
        if cd.id in owned_map:
            # State 1: currently owned
            card_infos.append({
                "card_number": cd.card_number, "owned": True,
                "count": owned_map[cd.id], "name": cd.name, "rarity": cd.rarity,
            })
        elif cd.id in album_set:
            # State 2: unlocked but not currently owned (gray, no "?")
            card_infos.append({
                "card_number": cd.card_number, "owned": False, "unlocked": True,
                "count": None, "name": cd.name, "rarity": cd.rarity,
            })
        else:
            # State 3: never seen (dark + "?")
            card_infos.append({
                "card_number": cd.card_number, "owned": False, "unlocked": False,
                "count": None, "name": cd.name, "rarity": cd.rarity,
            })

    png_bytes = await asyncio.to_thread(_generate_card_grid, card_infos, season_id)

    owned_unique = len([1 for cd in all_cards if cd.id in owned_map])
    unlocked_unique = len([1 for cd in all_cards if cd.id in album_set])

    now = datetime.now(timezone.utc)
    is_active = season.status == "active" and season.starts_at <= now < season.ends_at
    status_icon = "🟢" if is_active else "⚪"
    player_name = callback.from_user.first_name if callback.from_user else "旅行者"
    caption = (
        f"📖 <b>{player_name} 的卡册</b>\n"
        f"{status_icon} {season.name}\n"
        f"✨ 持有：{owned_unique}/{season.total_cards} | "
        f"🔓 解锁：{unlocked_unique}/{season.total_cards}\n"
        f"📄 第{page}/{total_pages}页"
    )

    # Card detail buttons — use card name (truncated), "???" for unknown
    card_buttons = []
    row = []
    for cd in page_cards:
        if cd.id in owned_map:
            emoji = RARITY_EMOJI.get(cd.rarity, "⬜")
            name_short = cd.name[:4]
            label = f"{emoji}{name_short}"
            if owned_map[cd.id] > 1:
                label += f"×{owned_map[cd.id]}"
        elif cd.id in album_set:
            label = f"🩶{cd.name[:4]}"
        else:
            label = "❓???"
        cb_data = f"gc_cv_{cd.card_number}_{season_id}_c_{page}_{user_id}_{chat_id}_{topic_msg}"
        row.append(InlineKeyboardButton(label, callback_data=cb_data))
        if len(row) == 3:
            card_buttons.append(row)
            row = []
    if row:
        card_buttons.append(row)

    # Navigation row
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀", callback_data=f"gc_cp_{page-1}_{season_id}_{user_id}_{chat_id}_{topic_msg}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("▶", callback_data=f"gc_cp_{page+1}_{season_id}_{user_id}_{chat_id}_{topic_msg}"))

    # Bottom row: redeem (always show if active) + season list + close
    bottom = []
    if is_active:
        bottom.append(InlineKeyboardButton("🎁 兑换全套", callback_data=f"gc_r_{user_id}_{chat_id}_{topic_msg}"))
    bottom.append(InlineKeyboardButton("📋 赛季", callback_data=f"gc_cs_{user_id}_{chat_id}_{topic_msg}"))
    bottom.append(InlineKeyboardButton("❌ 关闭", callback_data=f"gc_del_{user_id}_{chat_id}_{topic_msg}"))

    keyboard = InlineKeyboardMarkup(card_buttons + [nav_buttons, bottom])

    png_io = io.BytesIO(png_bytes)
    png_io.name = "collection.png"

    is_media_msg = callback.message and (callback.message.photo or callback.message.animation or callback.message.document)
    if is_media_msg:
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaPhoto(png_io, caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=keyboard,
        )
    else:
        # Delete old message first to avoid duplicates
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:
                pass
        send_kwargs = dict(chat_id=chat_id, photo=png_io, caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        if topic_msg:
            send_kwargs["reply_to_message_id"] = topic_msg
        await client.send_photo(**send_kwargs)
    await callback.answer()


async def _cb_collection_season_list(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    """卡册赛季选择器"""
    seasons = await database.get_all_seasons()
    if not seasons:
        await callback.answer("暂无赛季数据", show_alert=True)
        return

    buttons = []
    for s in seasons:
        album_data = await database.get_user_album(user_id, s.id)
        album_count = len(album_data)
        status = "🟢" if s.status == "active" else "⚪"
        buttons.append([InlineKeyboardButton(
            f"{status} {s.name} ({album_count}/{s.total_cards})",
            callback_data=f"gc_cp_1_{s.id}_{user_id}_{chat_id}_{topic_msg}",
        )])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}")])

    await _edit_text(
        client, callback,
        "📖 <b>卡册</b> — 选择赛季查看：",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await callback.answer()


# ==================== 卡包 ====================


async def _cb_inventory(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, page: int = 1):
    season = await database.get_current_or_latest_season()
    if not season:
        await callback.answer("没有卡牌赛季", show_alert=True)
        return

    cards = await database.get_user_cards(user_id, chat_id, season.id)
    unique_count = await database.get_user_unique_count(user_id, chat_id, season.id)

    if not cards:
        if callback.message and callback.message.photo:
            await callback.message.delete()
        await callback.answer("卡包空空如也～点击抽卡开始收集吧！", show_alert=True)
        return

    total_pages = math.ceil(len(cards) / _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    page_cards = cards[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]

    card_infos = [
        {"card_number": cd.card_number, "owned": True, "count": count, "name": cd.name, "rarity": cd.rarity}
        for cd, count in page_cards
    ]
    png_bytes = await asyncio.to_thread(_generate_card_grid, card_infos, season.id)

    caption = (
        f"📦 <b>我的卡包</b> — {season.name}\n"
        f"收集进度：{unique_count}/{season.total_cards} | 第{page}/{total_pages}页"
    )

    card_buttons = []
    row = []
    for idx, (cd, count) in enumerate(page_cards):
        emoji = RARITY_EMOJI.get(cd.rarity, "⬜")
        label = f"{emoji}#{cd.card_number}" + (f" ×{count}" if count > 1 else "")
        cb_data = f"gc_cv_{cd.card_number}_{season.id}_i_{page}_{user_id}_{chat_id}_{topic_msg}"
        row.append(InlineKeyboardButton(label, callback_data=cb_data))
        if len(row) == 3:
            card_buttons.append(row)
            row = []
    if row:
        card_buttons.append(row)

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀", callback_data=f"gc_ip_{page-1}_{user_id}_{chat_id}_{topic_msg}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("▶", callback_data=f"gc_ip_{page+1}_{user_id}_{chat_id}_{topic_msg}"))

    keyboard = InlineKeyboardMarkup(
        card_buttons + [nav_buttons, [InlineKeyboardButton("❌ 关闭", callback_data=f"gc_del_{user_id}_{chat_id}_{topic_msg}")]]
    )

    png_io = io.BytesIO(png_bytes)
    png_io.name = "inventory.png"

    is_media_msg = callback.message and (callback.message.photo or callback.message.animation or callback.message.document)
    if is_media_msg:
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaPhoto(png_io, caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=keyboard,
        )
    else:
        # Delete old message first to avoid duplicates
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:
                pass
        send_kwargs = dict(chat_id=chat_id, photo=png_io, caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        if topic_msg:
            send_kwargs["reply_to_message_id"] = topic_msg
        await client.send_photo(**send_kwargs)
    await callback.answer()


# ==================== 图鉴 ====================


async def _cb_album(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    """图鉴入口：显示赛季列表"""
    seasons = await database.get_all_seasons()
    if not seasons:
        await _edit_text(client, callback, "📖 <b>卡牌图鉴</b>\n\n暂无赛季数据")
        await callback.answer()
        return

    lines = []
    buttons = []
    for s in seasons:
        album_count = len(await database.get_user_album(user_id, s.id))
        status = "🟢" if s.status == "active" else "⚪"
        lines.append(f"{status} {s.name} — {album_count}/{s.total_cards}")
        buttons.append([InlineKeyboardButton(
            f"{status} {s.name} ({album_count}/{s.total_cards})",
            callback_data=f"gc_as_{s.id}_{user_id}_{chat_id}_{topic_msg}",
        )])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}")])

    await _edit_text(
        client, callback,
        f"📖 <b>卡牌图鉴</b>\n\n选择赛季查看图鉴：",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await callback.answer()


async def _cb_album_season(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, season_id: int = 1, page: int = 1):
    """图鉴赛季页：展示该赛季所有卡的 9 宫格"""
    season = await database.get_season_by_id(season_id)
    if not season:
        await callback.answer("赛季不存在", show_alert=True)
        return

    all_cards = await database.get_season_cards(season_id)
    user_album = await database.get_user_album(user_id, season_id)
    owned_card_def_ids = {entry[1].id for entry in user_album}

    total_pages = math.ceil(len(all_cards) / _PAGE_SIZE)
    page = max(1, min(page, total_pages))
    page_cards = all_cards[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]

    card_infos = [
        {
            "card_number": cd.card_number,
            "owned": cd.id in owned_card_def_ids,
            "count": None,
            "name": cd.name,
            "rarity": cd.rarity,
        }
        for cd in page_cards
    ]
    png_bytes = await asyncio.to_thread(_generate_card_grid, card_infos, season_id)

    owned_count = len(owned_card_def_ids)
    caption = (
        f"📖 <b>图鉴</b> — {season.name}\n"
        f"收集进度：{owned_count}/{season.total_cards} | 第{page}/{total_pages}页"
    )

    card_buttons = []
    row = []
    for cd in page_cards:
        label = f"#{cd.card_number}"
        cb_data = f"gc_cv_{cd.card_number}_{season_id}_a_{page}_{user_id}_{chat_id}_{topic_msg}"
        row.append(InlineKeyboardButton(label, callback_data=cb_data))
        if len(row) == 3:
            card_buttons.append(row)
            row = []
    if row:
        card_buttons.append(row)

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀", callback_data=f"gc_ap_{season_id}_{page-1}_{user_id}_{chat_id}_{topic_msg}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("▶", callback_data=f"gc_ap_{season_id}_{page+1}_{user_id}_{chat_id}_{topic_msg}"))

    keyboard = InlineKeyboardMarkup(
        card_buttons + [nav_buttons, [InlineKeyboardButton("❌ 关闭", callback_data=f"gc_del_{user_id}_{chat_id}_{topic_msg}")]]
    )

    png_io = io.BytesIO(png_bytes)
    png_io.name = "album.png"

    is_media_msg = callback.message and (callback.message.photo or callback.message.animation or callback.message.document)
    if is_media_msg:
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaPhoto(png_io, caption=caption, parse_mode=ParseMode.HTML),
            reply_markup=keyboard,
        )
    else:
        # Delete old message first to avoid duplicates
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:
                pass
        send_kwargs = dict(chat_id=chat_id, photo=png_io, caption=caption, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        if topic_msg:
            send_kwargs["reply_to_message_id"] = topic_msg
        await client.send_photo(**send_kwargs)
    await callback.answer()


# ==================== 查看单卡 ====================


async def _cb_view_card(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, season_id: int, card_number: int, source: str = "i", source_page: int = 1):
    """编辑当前图片消息，显示单张卡牌全尺寸图（无边框），可返回九宫格"""
    all_cards = await database.get_season_cards(season_id)
    card_def = next((cd for cd in all_cards if cd.card_number == card_number), None)

    if not card_def:
        await callback.answer("卡牌不存在", show_alert=True)
        return

    # Determine card state: owned / unlocked / unknown
    owned_data = await database.get_user_cards(user_id, chat_id, season_id)
    owned_map = {cd.id: count for cd, count in owned_data}
    album_data = await database.get_user_album(user_id, season_id)
    album_set = {entry[1].id for entry in album_data}

    is_owned = card_def.id in owned_map
    is_unlocked = card_def.id in album_set

    img_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_full.png"
    try:
        if not is_unlocked:
            # State 3: 未解锁 — 纯色占位 + "?"，不透露卡面
            card_img = Image.new("RGB", (680, 952), (30, 30, 38))
            draw = ImageDraw.Draw(card_img)
            q_font = _load_pil_font(120)
            draw.text((340, 476), "?", fill=(80, 80, 90), font=q_font, anchor="mm")
        else:
            card_img = Image.open(img_path).convert("RGB")
            if not is_owned:
                # State 2: 解锁但未拥有 — 灰度
                card_img = card_img.convert("L").convert("RGB")

        buf = io.BytesIO()
        card_img.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "card_detail.png"

        # 返回按钮：根据来源回到对应的卡册页/卡包页/图鉴页
        if source == "c":
            back_cb = f"gc_cp_{source_page}_{season_id}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡册"
        elif source == "a":
            back_cb = f"gc_ap_{season_id}_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回图鉴"
        else:
            back_cb = f"gc_ip_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡包"

        # 添加翻转卡片按钮
        flip_cb = f"gc_vb_{card_number}_{season_id}_{source}_{source_page}_{user_id}_{chat_id}_{topic_msg}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 翻转卡片", callback_data=flip_cb)],
            [InlineKeyboardButton(back_label, callback_data=back_cb)]
        ])

        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaPhoto(buf),
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning(f"[gacha] view card failed: {e}")
        await callback.answer("查看卡牌失败", show_alert=True)
        return

    await callback.answer()


async def _cb_view_card_back(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, season_id: int, card_number: int, source: str = "i", source_page: int = 1):
    """显示正面→背面翻转动画，然后固定在卡背"""
    all_cards = await database.get_season_cards(season_id)
    card_def = next((cd for cd in all_cards if cd.card_number == card_number), None)

    if not card_def:
        await callback.answer("卡牌不存在", show_alert=True)
        return

    # 三态检查：1) 从未解锁 2) 已解锁但未持有 3) 当前持有
    album_data = await database.get_user_album(user_id, season_id)
    album_set = {entry[1].id for entry in album_data}
    is_in_album = card_def.id in album_set

    # 检查是否当前持有（在 user_card 表中）
    owned_card = await database.get_user_card_by_def(user_id, chat_id, season_id, card_def.id)
    is_currently_owned = owned_card is not None

    # 状态 1: 从未解锁（不在图鉴）→ 禁止查看
    if not is_in_album:
        await callback.answer("此卡片尚未解锁，无法查看喵～", show_alert=True)
        return

    try:
        # 第一步：显示正面→背面翻转动画
        # 状态 2: 已解锁但未持有 → 灰度动画
        # 状态 3: 当前持有 → 彩色动画
        if is_currently_owned:
            flip_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_flip_reverse_clean.gif"
        else:
            flip_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_flip_reverse_clean_gray.gif"

        # 翻转卡片按钮（从背面翻回正面）
        flip_front_cb = f"gc_vf_{card_number}_{season_id}_{source}_{source_page}_{user_id}_{chat_id}_{topic_msg}"

        # 返回按钮
        if source == "c":
            back_cb = f"gc_cp_{source_page}_{season_id}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡册"
        elif source == "a":
            back_cb = f"gc_ap_{season_id}_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回图鉴"
        else:
            back_cb = f"gc_ip_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡包"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 翻转卡片", callback_data=flip_front_cb)],
            [InlineKeyboardButton(back_label, callback_data=back_cb)]
        ])

        # 播放翻转动画（使用 Video 避免循环播放）
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaVideo(flip_path),
            reply_markup=keyboard,
        )

        # 等待动画播放完成（动画正好 2.0 秒）
        await asyncio.sleep(2.0)

        # 第二步：替换为固定的卡背图片（未持有显示灰度版本）
        back_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_back.png"
        if is_currently_owned:
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(back_path),
                reply_markup=keyboard,
            )
        else:
            # 已解锁但未持有：生成灰度卡背
            back_img = Image.open(back_path).convert("L").convert("RGB")
            buf = io.BytesIO()
            back_img.save(buf, format="PNG")
            buf.seek(0)
            buf.name = "card_back_gray.png"
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(buf),
                reply_markup=keyboard,
            )

    except Exception as e:
        logger.warning(f"[gacha] view card back failed: {e}")
        await callback.answer("查看卡背失败", show_alert=True)
        return

    await callback.answer()


async def _cb_view_card_front(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, season_id: int, card_number: int, source: str = "i", source_page: int = 1):
    """显示背面→正面翻转动画，然后固定在正面"""
    all_cards = await database.get_season_cards(season_id)
    card_def = next((cd for cd in all_cards if cd.card_number == card_number), None)

    if not card_def:
        await callback.answer("卡牌不存在", show_alert=True)
        return

    # 三态检查：1) 从未解锁 2) 已解锁但未持有 3) 当前持有
    album_data = await database.get_user_album(user_id, season_id)
    album_set = {entry[1].id for entry in album_data}
    is_in_album = card_def.id in album_set

    # 检查是否当前持有（在 user_card 表中）
    owned_card = await database.get_user_card_by_def(user_id, chat_id, season_id, card_def.id)
    is_currently_owned = owned_card is not None

    logger.debug(f"[gacha] 查看卡片 {card_number}: is_in_album={is_in_album}, is_currently_owned={is_currently_owned}")

    # 状态 1: 从未解锁（不在图鉴）→ 禁止查看
    if not is_in_album:
        await callback.answer("此卡片尚未解锁，无法查看喵～", show_alert=True)
        return

    try:
        # 第一步：显示背面→正面翻转动画（MP4 格式，硬件加速流畅播放）
        # 状态 2: 已解锁但未持有 → 灰度动画
        # 状态 3: 当前持有 → 彩色动画
        if is_currently_owned:
            flip_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_flip_clean.mp4"
        else:
            flip_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_flip_clean_gray.mp4"

        logger.debug(f"[gacha] 使用翻转动画: {flip_path}")

        # 翻转卡片按钮（从正面翻到背面）
        flip_back_cb = f"gc_vb_{card_number}_{season_id}_{source}_{source_page}_{user_id}_{chat_id}_{topic_msg}"

        # 返回按钮
        if source == "c":
            back_cb = f"gc_cp_{source_page}_{season_id}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡册"
        elif source == "a":
            back_cb = f"gc_ap_{season_id}_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回图鉴"
        else:
            back_cb = f"gc_ip_{source_page}_{user_id}_{chat_id}_{topic_msg}"
            back_label = "🔙 返回卡包"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 翻转卡片", callback_data=flip_back_cb)],
            [InlineKeyboardButton(back_label, callback_data=back_cb)]
        ])

        # 播放翻转动画（MP4 视频格式）
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaVideo(flip_path),
            reply_markup=keyboard,
        )

        # 等待动画播放完成（动画正好 2.0 秒）
        await asyncio.sleep(2.0)

        # 第二步：替换为固定的正面图片（未持有显示灰度版本）
        front_path = f"/kmua/data/cards/season_{season_id}/card_{card_number:02d}_full.png"
        if is_currently_owned:
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(front_path),
                reply_markup=keyboard,
            )
        else:
            # 已解锁但未持有：生成灰度正面
            front_img = Image.open(front_path).convert("L").convert("RGB")
            buf = io.BytesIO()
            front_img.save(buf, format="PNG")
            buf.seek(0)
            buf.name = "card_front_gray.png"
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(buf),
                reply_markup=keyboard,
            )

    except Exception as e:
        logger.warning(f"[gacha] flip to front failed: {e}")
        await callback.answer("翻转失败", show_alert=True)
        return

    await callback.answer()


# ==================== 兑换 ====================


async def _cb_redeem(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    season = await database.get_current_or_latest_season()
    if not season:
        await callback.answer("没有卡牌赛季", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    is_active = season.status == "active" and season.starts_at <= now < season.ends_at
    if not is_active:
        await callback.answer("赛季已结束，无法兑换", show_alert=True)
        return

    unique_count = await database.get_user_unique_count(user_id, chat_id, season.id)
    if unique_count < season.total_cards:
        await callback.answer(
            f"尚未集齐！进度 {unique_count}/{season.total_cards}，还差 {season.total_cards - unique_count} 张",
            show_alert=True,
        )
        return

    success = await database.redeem_collection(user_id, chat_id, season.id)
    if not success:
        await callback.answer("兑换失败，请确保每种卡至少1张", show_alert=True)
        return

    await database.add_points(
        user_id, chat_id, season.redeem_reward,
        reason=f"卡牌全套兑换(赛季{season.id})"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}")]
    ])

    await _edit_text(
        client, callback,
        f"🎉 <b>恭喜集齐全套！</b>\n\n"
        f"消耗：全套 {season.total_cards} 张卡牌\n"
        f"获得：<b>+{season.redeem_reward} 积分</b>\n\n"
        f"图鉴记录永久保留。",
        reply_markup=keyboard,
    )
    await callback.answer("兑换成功！")


# ==================== 赛季信息 ====================


async def _cb_season_info(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    season = await database.get_current_or_latest_season()
    if not season:
        await callback.answer("没有卡牌赛季", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    is_active = season.status == "active" and season.starts_at <= now < season.ends_at
    status_text = "进行中" if is_active else "已结束"
    ends = season.ends_at.strftime("%Y-%m-%d")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回", callback_data=f"gc_b_{user_id}_{chat_id}_{topic_msg}")]
    ])

    await _edit_text(
        client, callback,
        f"🃏 <b>赛季信息：{season.name}</b>（{status_text}）\n\n"
        f"📊 <b>基础信息</b>\n"
        f"总卡数：{season.total_cards} 张（普通14/稀有9/史诗6/传说3）\n"
        f"每日免费：{season.daily_free_draws} 次\n"
        f"付费单价：{season.draw_price} 积分/抽\n"
        f"截止日期：{ends}\n\n"
        f"🎯 <b>卡牌出货率</b>\n"
        f"• 普通：{database.RARITY_WEIGHTS['common']}%\n"
        f"• 稀有：{database.RARITY_WEIGHTS['rare']}%\n"
        f"• 史诗：{database.RARITY_WEIGHTS['epic']}%\n"
        f"• 传说：{database.RARITY_WEIGHTS['legendary']}%\n\n"
        f"🎲 <b>保底机制</b>\n"
        f"• 传说保底：连续 {season.pity_legendary} 抽未出传说卡时，第 {season.pity_legendary} 抽必得传说卡\n"
        f"• 去重保底：连续 {season.pity_dedup} 抽未获得新卡时，第 {season.pity_dedup} 抽必得未拥有的卡片\n\n"
        f"💰 <b>其他规则</b>\n"
        f"全套兑换：{season.redeem_reward} 积分（消耗全套32张卡）\n"
        f"交易手续费：{season.trade_fee} 积分/人",
        reply_markup=keyboard,
    )
    await callback.answer()


# ==================== 特典查看 ====================


async def _cb_tokuten(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int):
    """查看特典奖励（横图）"""
    season = await database.get_current_or_latest_season()
    if not season:
        await callback.answer("没有卡牌�赛季", show_alert=True)
        return

    # 检查用户是否集齐
    unique_count = await database.get_user_unique_count(user_id, chat_id, season.id)

    # 检查是否已解锁特典
    tokuten = await database.get_user_tokuten(user_id, chat_id, season.id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回", callback_data=f"gc_bt_{user_id}_{chat_id}_{topic_msg}")]
    ])

    if not tokuten:
        # 未解锁：显示提示
        remaining = season.total_cards - unique_count
        hint_text = (
            f"🎁 <b>特典奖励</b>\n\n"
            f"集齐 <b>{season.name}</b> 的全部 {season.total_cards} 张卡牌即可解锁特典奖励！\n\n"
            f"当前进度：{unique_count}/{season.total_cards}\n"
        )
        if remaining > 0:
            hint_text += f"还差 {remaining} 张～加油喵！"
        else:
            hint_text += f"✨ 即将解锁！再抽一次试试～"

        await _edit_text(
            client, callback,
            hint_text,
            reply_markup=keyboard,
        )
        await callback.answer()
    else:
        # 已解锁：发送特典横图
        tokuten_path = "/kmua/data/cards/photo_2026-09-02_14-40-22.jpg"
        unlocked_date = tokuten.unlocked_at.strftime("%Y-%m-%d")
        caption = (
            f"🎊 <b>特典奖励</b>\n\n"
            f"恭喜完成 <b>{season.name}</b> 全套收集！\n"
            f"解锁日期：{unlocked_date}\n\n"
            f"✨ 特典卡片不可交易和兑换，是你的专属荣誉～"
        )

        # 判断当前消息是否为媒体消息
        is_media_msg = callback.message and (callback.message.photo or callback.message.animation or callback.message.document)

        if is_media_msg:
            # 从图片切换到图片（用 edit_media）
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(tokuten_path, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=keyboard,
            )
        else:
            # 从文本切换到图片：先删除旧消息，再发送新图片
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            send_kwargs = dict(
                chat_id=chat_id,
                photo=tokuten_path,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            await client.send_photo(**send_kwargs)

        await callback.answer()


# ==================== 返回主菜单 ====================


async def _cb_back_to_menu(client: Client, callback: CallbackQuery, user_id: int, chat_id: int, topic_msg: int, show_tokuten_photo: bool = False):
    season = await database.get_current_or_latest_season()
    if not season:
        await callback.answer("没有卡牌赛季", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    is_active = season.status == "active" and season.starts_at <= now < season.ends_at

    unique = await database.get_user_unique_count(user_id, chat_id, season.id)

    safe_name = (
        callback.from_user.first_name
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    mention = f'<a href="tg://user?id={user_id}">{safe_name}</a>'

    if is_active:
        today = datetime.now(TZ_UTC8).strftime("%Y-%m-%d")
        free_count = await database.get_today_free_draw_count(
            user_id, chat_id, season.id, today
        )
        free_remaining = max(0, season.daily_free_draws - free_count)
        text = (
            f"🃏 <b>集换卡牌系统</b> — {season.name}\n\n"
            f"{mention} 的状态：\n"
            f"  收集进度：{unique}/{season.total_cards}\n"
            f"  今日免费抽卡：{free_remaining}/{season.daily_free_draws}\n"
            f"  付费单价：{season.draw_price} 积分/抽\n\n"
            f"请选择操作："
        )
    else:
        text = (
            f"🃏 <b>集换卡牌系统</b> — {season.name}（已结束）\n\n"
            f"{mention} 的状态：\n"
            f"  收集进度：{unique}/{season.total_cards}\n\n"
            f"赛季已结束，卡牌永久保留，可查看卡册和图鉴。"
        )

    # 检查是否解锁特典：已解锁则始终显示特典图片
    tokuten_unlocked = await database.check_tokuten_unlocked(user_id, chat_id, season.id)
    is_media_msg = callback.message and (callback.message.photo or callback.message.animation or callback.message.document)

    if tokuten_unlocked:
        # 已解锁特典：返回带特典图片的主菜单
        tokuten_path = "/kmua/data/cards/photo_2026-09-02_14-40-22.jpg"

        if is_media_msg:
            # 从图片切换到图片（用 edit_media）
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_media,
                InputMediaPhoto(tokuten_path, caption=text, parse_mode=ParseMode.HTML),
                reply_markup=_main_menu_keyboard(user_id, chat_id, topic_msg, is_active=is_active),
            )
        else:
            # 从文本切换到图片：先删除旧消息，再发送新图片
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            send_kwargs = dict(
                chat_id=chat_id,
                photo=tokuten_path,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_keyboard(user_id, chat_id, topic_msg, is_active=is_active),
            )
            if topic_msg:
                send_kwargs["reply_to_message_id"] = topic_msg
            await client.send_photo(**send_kwargs)
    else:
        # 未解锁特典：返回普通文本主菜单
        if is_media_msg:
            # 从图片切换到文本（删除图片消息，发送新文本消息）
            try:
                await callback.message.delete()
                # 删除成功，发送新文本消息
                send_kwargs = dict(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_main_menu_keyboard(user_id, chat_id, topic_msg, is_active=is_active),
                )
                if topic_msg:
                    send_kwargs["reply_to_message_id"] = topic_msg
                await client.send_message(**send_kwargs)
            except Exception as e:
                # 删除失败，用 answer 提示用户手动关闭
                await callback.answer("无法切换菜单，请手动关闭后重新打开", show_alert=True)
                return
        else:
            # 从文本切换到文本（用 edit_text）
            await enqueue_message_operation(
                chat_id,
                callback.message.edit_text,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_keyboard(user_id, chat_id, topic_msg, is_active=is_active),
            )

    await callback.answer()


# ==================== 交易（/trade 指令触发） ====================


@Client.on_message(filters.command("trade") & filters.group, group=0)
async def trade_handler(client: Client, message: Message):
    if not _is_group_allowed(message.chat.id):
        return
    user = message.from_user
    if not user:
        return

    if _is_banned(user.id):
        return

    season = await database.get_active_season()
    if not season:
        reply = await message.reply_text("当前没有进行中的卡牌赛季哦～")
        asyncio.create_task(_auto_delete(reply))
        return

    user_id = user.id
    chat_id = message.chat.id

    if not message.reply_to_message or not message.reply_to_message.from_user:
        reply = await message.reply_text(
            "💡 回复目标用户的消息并发送 /trade 即可发起交易",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_auto_delete(reply))
        return

    target_user = message.reply_to_message.from_user
    if target_user.id == user_id:
        reply = await message.reply_text("不能和自己交易哦～")
        asyncio.create_task(_auto_delete(reply))
        return

    all_cards = await database.get_user_cards(user_id, chat_id, season.id)
    if not all_cards:
        reply = await message.reply_text("你还没有卡牌，先抽卡吧～")
        asyncio.create_task(_auto_delete(reply))
        return

    sender_points = await database.get_user_points(user_id, chat_id)
    if not sender_points or sender_points.points < season.trade_fee:
        reply = await message.reply_text(f"手续费 {season.trade_fee} 积分，余额不足。")
        asyncio.create_task(_auto_delete(reply))
        return

    buttons = []
    for card_def, count in list(all_cards)[:10]:
        emoji = RARITY_EMOJI.get(card_def.rarity, "⬜")
        buttons.append([InlineKeyboardButton(
            f"{emoji} #{card_def.card_number} {card_def.name} (×{count})",
            callback_data=f"trs_{target_user.id}_{card_def.id}",
        )])
    buttons.append([InlineKeyboardButton("❌ 取消", callback_data="trs_cancel")])

    safe_name = (
        target_user.first_name
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    target_mention = f'<a href="tg://user?id={target_user.id}">{safe_name}</a>'

    await message.reply_text(
        f"🤝 <b>发起交易</b>\n\n"
        f"目标：{target_mention}\n"
        f"请选择你要交换出去的卡牌：",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ==================== 交易回调 ====================


@Client.on_callback_query(filters.regex(r"^trs_"))
async def trade_sender_select_handler(client: Client, callback: CallbackQuery):
    if callback.message and not _is_group_allowed(callback.message.chat.id):
        await callback.answer("卡牌系统仅在特定群开放", show_alert=True)
        return
    if _is_banned(callback.from_user.id):
        await callback.answer("你已被禁止使用卡牌系统", show_alert=True)
        return
    data = callback.data
    user_id = callback.from_user.id

    if data == "trs_cancel":
        await enqueue_message_operation(
            callback.message.chat.id,
            callback.message.edit_text,
            "❌ 交易已取消"
        )
        await callback.answer("已取消")
        return

    parts = data.split("_")
    receiver_id = int(parts[1])
    card_def_id = int(parts[2])

    season = await database.get_active_season()
    if not season:
        await callback.answer("当前没有进行中的赛季", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_card = await database.get_user_card_by_def(user_id, chat_id, season.id, card_def_id)
    if not user_card:
        await callback.answer("你已没有这张卡", show_alert=True)
        return

    trade = await database.create_trade_request(
        chat_id=chat_id,
        sender_id=user_id,
        receiver_id=receiver_id,
        sender_card_id=user_card.id,
        season_id=season.id,
    )
    if not trade:
        await callback.answer("这张卡已有进行中的交易", show_alert=True)
        return

    card_def = await database.get_card_def_by_id(card_def_id)
    emoji = RARITY_EMOJI.get(card_def.rarity, "⬜") if card_def else "⬜"
    card_label = f"{emoji} #{card_def.card_number} {card_def.name}" if card_def else "未知卡牌"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 选卡交换", callback_data=f"trade_view_{trade.id}")],
        [InlineKeyboardButton("❌ 拒绝", callback_data=f"trade_cancel_{trade.id}")],
    ])

    await enqueue_message_operation(
        chat_id,
        callback.message.edit_text,
        f"🤝 <b>交易请求</b>\n\n"
        f"出：{card_label}\n"
        f"等待对方选择一张同稀有度的卡交换\n"
        f"双方各付手续费：{season.trade_fee} 积分\n"
        f"⏰ 24小时内有效",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await callback.answer("已发起交易")


@Client.on_callback_query(filters.regex(r"^trade_"))
async def trade_callback_handler(client: Client, callback: CallbackQuery):
    if callback.message and not _is_group_allowed(callback.message.chat.id):
        await callback.answer("卡牌系统仅在特定群开放", show_alert=True)
        return
    if _is_banned(callback.from_user.id):
        await callback.answer("你已被禁止使用卡牌系统", show_alert=True)
        return
    await _handle_trade_callback(client, callback)


async def _handle_trade_callback(client: Client, callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if data.startswith("trade_cancel_"):
        trade_id = int(data.replace("trade_cancel_", ""))
        trade = await database.get_trade_request(trade_id)
        if not trade:
            await callback.answer("交易不存在", show_alert=True)
            return
        if user_id not in (trade.sender_id, trade.receiver_id):
            await callback.answer("这不是你的交易", show_alert=True)
            return
        await database.cancel_trade(trade_id)
        await enqueue_message_operation(
            callback.message.chat.id,
            callback.message.edit_text,
            "❌ 交易已取消"
        )
        await callback.answer("已取消")

    elif data.startswith("trade_view_"):
        trade_id = int(data.replace("trade_view_", ""))
        trade = await database.get_trade_request(trade_id)
        if not trade:
            await callback.answer("交易不存在", show_alert=True)
            return
        if user_id != trade.receiver_id:
            await callback.answer("只有接收方可以操作", show_alert=True)
            return

        sender_card_def = await database.get_card_def_for_user_card(trade.sender_card_id)
        if not sender_card_def:
            await callback.answer("发起方卡牌数据异常", show_alert=True)
            return

        all_cards = await database.get_user_cards(user_id, trade.chat_id, trade.season_id)
        same_rarity_cards = [(cd, count) for cd, count in all_cards if cd.rarity == sender_card_def.rarity]

        if not same_rarity_cards:
            await callback.answer(f"你没有同稀有度（{RARITY_LABELS.get(sender_card_def.rarity, sender_card_def.rarity)}）的卡可以交换", show_alert=True)
            return

        buttons = []
        for card_def, count in list(same_rarity_cards)[:10]:
            emoji = RARITY_EMOJI.get(card_def.rarity, "⬜")
            buttons.append([InlineKeyboardButton(
                f"{emoji} #{card_def.card_number} {card_def.name} (×{count})",
                callback_data=f"trade_accept_{trade_id}_{card_def.id}",
            )])
        buttons.append([InlineKeyboardButton("❌ 拒绝", callback_data=f"trade_cancel_{trade_id}")])
        await callback.message.edit_reply_markup(InlineKeyboardMarkup(buttons))
        await callback.answer()

    elif data.startswith("trade_accept_"):
        # B 选好卡 → 直接进入等待 A 确认（不再有中间确认步骤）
        parts = data.replace("trade_accept_", "").split("_")
        trade_id = int(parts[0])
        offered_card_def_id = int(parts[1])

        trade = await database.get_trade_request(trade_id)
        if not trade or trade.status != "pending":
            await callback.answer("交易已失效", show_alert=True)
            return
        if user_id != trade.receiver_id:
            await callback.answer("只有接收方可以操作", show_alert=True)
            return
        if datetime.now(timezone.utc) > trade.expires_at:
            await database.cancel_trade(trade_id)
            await enqueue_message_operation(
                callback.message.chat.id,
                callback.message.edit_text,
                "⏰ 交易已过期"
            )
            await callback.answer("已过期", show_alert=True)
            return

        receiver_card = await database.get_user_card_by_def(
            user_id, trade.chat_id, trade.season_id, offered_card_def_id
        )
        if not receiver_card:
            await callback.answer("你已没有这张卡", show_alert=True)
            return

        sender_card_def = await database.get_card_def_for_user_card(trade.sender_card_id)
        receiver_card_def = await database.get_card_def_by_id(offered_card_def_id)
        if not sender_card_def or not receiver_card_def or sender_card_def.rarity != receiver_card_def.rarity:
            await callback.answer("只能交换同稀有度的卡牌", show_alert=True)
            return

        # 保存 B 的选卡，状态转为等待 A 确认
        await database.set_trade_awaiting_sender(trade_id, receiver_card.id)

        s_emoji = RARITY_EMOJI.get(sender_card_def.rarity, "⬜")
        r_emoji = RARITY_EMOJI.get(receiver_card_def.rarity, "⬜")

        season = await database.get_season_by_id(trade.season_id)
        fee = season.trade_fee if season else 0

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 同意交换", callback_data=f"trade_final_{trade_id}")],
            [InlineKeyboardButton("❌ 拒绝交易", callback_data=f"trade_cancel_{trade_id}")],
        ])
        sender_name = f'<a href="tg://user?id={trade.sender_id}">发起方</a>'
        receiver_name = f'<a href="tg://user?id={trade.receiver_id}">接收方</a>'
        await enqueue_message_operation(
            callback.message.chat.id,
            callback.message.edit_text,
            f"🔄 <b>等待发起方确认</b>\n\n"
            f"{sender_name} 出：{s_emoji} #{sender_card_def.card_number} {sender_card_def.name}\n"
            f"{receiver_name} 出：{r_emoji} #{receiver_card_def.card_number} {receiver_card_def.name}\n\n"
            f"双方各付手续费：{fee} 积分\n"
            f"请发起方确认是否同意交换～",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        await callback.answer("已提交，等待发起方确认")

    elif data.startswith("trade_final_"):
        # A 最终确认 → 执行交换
        trade_id = int(data.replace("trade_final_", ""))

        trade = await database.get_trade_request(trade_id)
        if not trade or trade.status != "awaiting_sender":
            await callback.answer("交易已失效", show_alert=True)
            return
        if user_id != trade.sender_id:
            await callback.answer("只有发起方可以确认", show_alert=True)
            return
        if datetime.now(timezone.utc) > trade.expires_at:
            await database.cancel_trade(trade_id)
            await enqueue_message_operation(
                callback.message.chat.id,
                callback.message.edit_text,
                "⏰ 交易已过期"
            )
            await callback.answer("已过期", show_alert=True)
            return

        season = await database.get_season_by_id(trade.season_id)
        if not season:
            await callback.answer("赛季不存在", show_alert=True)
            return

        sender_card_def = await database.get_card_def_for_user_card(trade.sender_card_id)
        receiver_card_def = await database.get_card_def_for_user_card(trade.receiver_card_id)
        if not sender_card_def or not receiver_card_def:
            await callback.answer("卡牌数据异常", show_alert=True)
            return

        try:
            await database.cost_points(
                trade.sender_id, trade.chat_id, season.trade_fee,
                reason=f"交易手续费(#{trade_id})"
            )
        except ValueError:
            await callback.answer("你的积分不足，无法支付手续费", show_alert=True)
            return

        try:
            await database.cost_points(
                trade.receiver_id, trade.chat_id, season.trade_fee,
                reason=f"交易手续费(#{trade_id})"
            )
        except ValueError:
            await database.add_points(
                trade.sender_id, trade.chat_id, season.trade_fee,
                reason=f"退还手续费(#{trade_id})"
            )
            await callback.answer("对方积分不足", show_alert=True)
            return

        await database.accept_trade(trade_id, trade.receiver_card_id)

        s_emoji = RARITY_EMOJI.get(sender_card_def.rarity, "⬜")
        r_emoji = RARITY_EMOJI.get(receiver_card_def.rarity, "⬜")
        sender_name = f'<a href="tg://user?id={trade.sender_id}">发起方</a>'
        receiver_name = f'<a href="tg://user?id={trade.receiver_id}">接收方</a>'

        await enqueue_message_operation(
            callback.message.chat.id,
            callback.message.edit_text,
            f"✅ <b>交易完成！</b>\n\n"
            f"{sender_name}：{s_emoji} #{sender_card_def.card_number} {sender_card_def.name}\n"
            f"  ⇄\n"
            f"{receiver_name}：{r_emoji} #{receiver_card_def.card_number} {receiver_card_def.name}\n\n"
            f"双方各支付 {season.trade_fee} 积分手续费。",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer("交易成功！")
