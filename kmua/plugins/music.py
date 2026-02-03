"""
音乐搜索与解析插件
使用 TuneHub V3 API 提供跨平台音乐搜索和解析功能
支持网易云音乐、QQ音乐、酷我音乐
"""
import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from dynaconf import Dynaconf
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# 加载配置
_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)

# TuneHub V3 API 配置
TUNEHUB_API_URL = "https://tunehub.sayqz.com/api"
REQUEST_TIMEOUT = 15.0

# 平台配置
PLATFORMS = ["kuwo", "qq", "netease"]
PLATFORM_NAMES = {
    "netease": "网易云音乐",
    "kuwo": "酷我音乐",
    "qq": "QQ音乐",
}
PLATFORM_EMOJI = {
    "netease": "☁️",
    "kuwo": "🎵",
    "qq": "🎶",
}

# 搜索结果缓存 (chat_id -> {keyword, results, platform, page})
_search_cache: Dict[int, Dict] = {}

# 分页配置
SONGS_PER_PAGE = 10  # 每页显示歌曲数（双排，5行）
SEARCH_LIMIT_PER_PLATFORM = 30  # 每个平台搜索数量

# 音乐临时文件目录
MUSIC_TEMP_DIR = Path(tempfile.gettempdir()) / "kmua_music"
MUSIC_TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 文件保留时间（秒）- 10分钟后清理
FILE_RETENTION_SECONDS = 600


def _get_api_key() -> str:
    """获取 API Key"""
    return _settings.get("tunehub_api_key", "")


def _get_headers() -> dict:
    """获取请求头"""
    headers = {"User-Agent": "KMUA MusicBot/1.0"}
    api_key = _get_api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


class TuneHubAPI:
    """TuneHub V3 API 封装类"""

    @staticmethod
    async def search_kuwo(keyword: str, limit: int = 10) -> List[Dict]:
        """酷我音乐搜索"""
        songs = []
        try:
            params = {
                "client": "kt",
                "all": keyword,
                "pn": "0",
                "rn": str(limit),
                "uid": "794762570",
                "ver": "kwplayer_ar_9.2.2.1",
                "vipver": "1",
                "show_copyright_off": "1",
                "newver": "1",
                "ft": "music",
                "cluster": "0",
                "strategy": "2012",
                "encoding": "utf8",
                "rformat": "json",
                "vermerge": "1",
                "mobi": "1",
                "issubtitle": "1",
            }
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get("http://search.kuwo.cn/r.s", params=params, headers=headers)
                response.raise_for_status()
                data = response.json()

                for item in data.get("abslist", [])[:limit]:
                    songs.append({
                        "id": item.get("MUSICRID", "").replace("MUSIC_", ""),
                        "name": item.get("SONGNAME", ""),
                        "artist": item.get("ARTIST", "").replace("&", ", "),
                        "album": item.get("ALBUM", ""),
                        "duration": int(item.get("DURATION", 0)),
                        "source": "kuwo",
                    })
        except Exception as e:
            logger.error(f"Kuwo search failed: {e}")

        return songs

    @staticmethod
    async def search_qq(keyword: str, limit: int = 10) -> List[Dict]:
        """QQ音乐搜索"""
        songs = []
        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; WOW64; Trident/5.0)",
            }
            payload = {
                "comm": {
                    "ct": 11,
                    "cv": "1003006",
                    "v": "1003006",
                    "os_ver": "12",
                    "phonetype": "0",
                    "devicelevel": "31",
                    "tmeAppID": "qqmusiclight",
                    "nettype": "NETWORK_WIFI",
                },
                "req": {
                    "module": "music.search.SearchCgiService",
                    "method": "DoSearchForQQMusicLite",
                    "param": {
                        "query": keyword,
                        "search_type": 0,
                        "num_per_page": limit,
                        "page_num": 1,
                        "nqc_flag": 0,
                        "grp": 1,
                    },
                },
            }

            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    "https://u.y.qq.com/cgi-bin/musicu.fcg",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                body = data.get("req", {}).get("data", {}).get("body", {})
                song_list = body.get("item_song", [])

                for item in song_list[:limit]:
                    artists = [s.get("name", "") for s in item.get("singer", [])]
                    songs.append({
                        "id": item.get("mid", ""),
                        "name": item.get("name", ""),
                        "artist": ", ".join(artists),
                        "album": item.get("album", {}).get("name", ""),
                        "duration": item.get("interval", 0),
                        "source": "qq",
                    })
        except Exception as e:
            logger.error(f"QQ Music search failed: {e}")

        return songs

    @staticmethod
    async def search_netease(keyword: str, limit: int = 10) -> List[Dict]:
        """网易云音乐搜索 - 使用 cloudsearch API"""
        songs = []
        try:
            # 使用更稳定的 cloudsearch API
            params = {
                "s": keyword,
                "type": "1",  # 1=单曲
                "offset": "0",
                "limit": str(limit),
            }
            headers = {
                "Referer": "https://music.163.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                # 尝试 cloudsearch API
                response = await client.post(
                    "https://music.163.com/api/cloudsearch/pc",
                    data=params,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                if isinstance(data, dict) and data.get("code") == 200:
                    result = data.get("result", {})
                    if isinstance(result, dict):
                        song_list = result.get("songs", [])
                        for item in song_list[:limit]:
                            if not isinstance(item, dict):
                                continue
                            # 艺术家可能在 ar 或 artists 字段
                            artists_field = item.get("ar") or item.get("artists") or []
                            artists = [a.get("name", "") for a in artists_field if isinstance(a, dict)]
                            # 专辑可能在 al 或 album 字段
                            album_field = item.get("al") or item.get("album") or {}
                            album_name = album_field.get("name", "") if isinstance(album_field, dict) else ""
                            # 时长可能是毫秒或秒
                            duration = item.get("dt", 0) or item.get("duration", 0)
                            if duration > 100000:  # 如果大于100000，则是毫秒
                                duration = duration // 1000

                            songs.append({
                                "id": str(item.get("id", "")),
                                "name": item.get("name", ""),
                                "artist": ", ".join(artists),
                                "album": album_name,
                                "duration": duration,
                                "source": "netease",
                            })
        except Exception as e:
            logger.error(f"Netease search failed: {e}")

        return songs

    @staticmethod
    async def search_all_platforms(keyword: str, limit_per_platform: int = 8) -> Dict[str, List[Dict]]:
        """
        并行搜索所有平台
        返回: {platform: [songs]}
        """
        import asyncio

        results = {}

        # 并行搜索
        tasks = [
            TuneHubAPI.search_kuwo(keyword, limit_per_platform),
            TuneHubAPI.search_qq(keyword, limit_per_platform),
            TuneHubAPI.search_netease(keyword, limit_per_platform),
        ]

        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        for platform, result in zip(PLATFORMS, search_results):
            if isinstance(result, Exception):
                logger.error(f"Search failed for {platform}: {result}")
                results[platform] = []
            else:
                results[platform] = result

        return results

    @staticmethod
    async def parse_song(platform: str, song_id: str, quality: str = "320k") -> Optional[Dict]:
        """解析歌曲获取播放链接"""
        api_key = _get_api_key()
        if not api_key:
            logger.error("TuneHub API Key not configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=_get_headers()) as client:
                response = await client.post(
                    f"{TUNEHUB_API_URL}/v1/parse",
                    json={
                        "platform": platform,
                        "ids": song_id,
                        "quality": quality,
                    }
                )
                response.raise_for_status()
                data = response.json()

                if data.get("code") == 0:
                    return data.get("data")
                else:
                    logger.error(f"Parse failed: {data.get('message')}")
                    return None

        except Exception as e:
            logger.exception(f"Parse song failed: {e}")
            return None

    @staticmethod
    async def download_music(url: str, filename: str, source: str = "") -> Optional[Path]:
        """
        下载音乐文件到临时目录

        Args:
            url: 音乐文件URL
            filename: 文件名（不含路径）
            source: 来源平台（用于设置正确的请求头）

        Returns:
            下载后的文件路径，失败返回 None
        """
        try:
            # 清理旧文件
            cleanup_temp_files()

            filepath = MUSIC_TEMP_DIR / filename

            # 根据不同平台设置请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

            # QQ音乐需要特殊的 Referer
            if "qqmusic" in url or "qq.com" in url:
                headers["Referer"] = "https://y.qq.com/"
                headers["Origin"] = "https://y.qq.com"
            elif "kuwo" in url:
                headers["Referer"] = "https://www.kuwo.cn/"
            elif "163" in url or "netease" in url:
                headers["Referer"] = "https://music.163.com/"

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()

                # 写入文件
                with open(filepath, "wb") as f:
                    f.write(response.content)

                logger.info(f"Music downloaded: {filepath} ({len(response.content)} bytes)")
                return filepath

        except Exception as e:
            logger.exception(f"Music download failed: {e}")
            return None


def cleanup_temp_files():
    """清理过期的临时音乐文件"""
    try:
        current_time = time.time()
        cleaned_count = 0

        for filepath in MUSIC_TEMP_DIR.glob("*"):
            if filepath.is_file():
                file_age = current_time - filepath.stat().st_mtime
                if file_age > FILE_RETENTION_SECONDS:
                    filepath.unlink()
                    cleaned_count += 1

        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} expired music files")

    except Exception as e:
        logger.error(f"Failed to cleanup temp files: {e}")


def build_platform_keyboard(
    songs: List[Dict],
    current_platform: str,
    all_platforms: List[str],
    chat_id: int,
    page: int = 0,
) -> InlineKeyboardMarkup:
    """构建带平台切换和分页的搜索结果按钮（双排布局）"""
    buttons = []

    # 计算分页
    total_songs = len(songs)
    total_pages = (total_songs + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE
    start_idx = page * SONGS_PER_PAGE
    end_idx = min(start_idx + SONGS_PER_PAGE, total_songs)
    page_songs = songs[start_idx:end_idx]

    # 歌曲列表按钮（双排布局）
    row = []
    for i, song in enumerate(page_songs):
        source = song.get("source", "")
        song_id = song.get("id", "")
        name = song.get("name", "未知")
        artist = song.get("artist", "未知")

        # 缩短显示文本以适应双排
        text = f"{name} - {artist}"
        if len(text) > 28:
            text = text[:25] + "..."

        callback_data = f"ms:{source}:{song_id}"
        row.append(InlineKeyboardButton(text, callback_data=callback_data))

        # 每两个一行
        if len(row) == 2:
            buttons.append(row)
            row = []

    # 如果最后一行只有一个按钮，也添加进去
    if row:
        buttons.append(row)

    # 分页按钮（如果需要）
    if total_pages > 1:
        page_buttons = []
        if page > 0:
            page_buttons.append(
                InlineKeyboardButton("⬅️ 上一页", callback_data=f"mspg:{current_platform}:{page - 1}")
            )
        page_buttons.append(
            InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="mspg:noop")
        )
        if page < total_pages - 1:
            page_buttons.append(
                InlineKeyboardButton("下一页 ➡️", callback_data=f"mspg:{current_platform}:{page + 1}")
            )
        buttons.append(page_buttons)

    # 平台切换按钮
    platform_buttons = []
    for platform in all_platforms:
        emoji = PLATFORM_EMOJI.get(platform, "🎵")
        name = PLATFORM_NAMES.get(platform, platform)[:4]  # 缩短名称

        if platform == current_platform:
            # 当前平台，高亮显示
            btn_text = f"【{emoji} {name}】"
        else:
            btn_text = f"{emoji} {name}"

        platform_buttons.append(
            InlineKeyboardButton(btn_text, callback_data=f"msp:{platform}")
        )

    buttons.append(platform_buttons)

    # 关闭按钮
    buttons.append([InlineKeyboardButton("❌ 关闭", callback_data="ms:close")])

    return InlineKeyboardMarkup(buttons)


def build_quality_keyboard(source: str, song_id: str) -> InlineKeyboardMarkup:
    """构建音质选择按钮"""
    buttons = [
        [
            InlineKeyboardButton("🎵 128K", callback_data=f"msq:{source}:{song_id}:128k"),
            InlineKeyboardButton("🎶 320K", callback_data=f"msq:{source}:{song_id}:320k"),
            InlineKeyboardButton("💿 FLAC", callback_data=f"msq:{source}:{song_id}:flac"),
        ],
        [InlineKeyboardButton("🔙 返回搜索结果", callback_data="msp:back")],
    ]
    return InlineKeyboardMarkup(buttons)


# ==================== 指令处理 ====================

@Client.on_message(filters.command("ms"), group=0)
async def music_search_handler(client: Client, message: Message):
    """处理 /ms 音乐搜索指令"""
    if not _settings.get("tunehub_enabled", True):
        await message.reply_text("❌ 音乐搜索功能未启用")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "🎵 **音乐搜索**\n\n"
            "**用法:** `/ms <歌曲名/歌手>`\n"
            "**示例:** `/ms 周杰伦 晴天`\n\n"
            "**支持平台:**\n"
            "🎵 酷我音乐\n"
            "🎶 QQ音乐\n"
            "☁️ 网易云音乐",
        )
        return

    keyword = parts[1].strip()
    chat_id = message.chat.id
    status_msg = await message.reply_text(f"🔍 正在搜索「{keyword}」...")

    try:
        # 并行搜索所有平台
        all_results = await TuneHubAPI.search_all_platforms(keyword, limit_per_platform=SEARCH_LIMIT_PER_PLATFORM)

        # 统计结果
        total_count = sum(len(songs) for songs in all_results.values())
        if total_count == 0:
            await status_msg.edit_text(f"😢 未找到「{keyword}」相关歌曲")
            return

        # 找到第一个有结果的平台
        current_platform = "kuwo"
        for platform in PLATFORMS:
            if all_results.get(platform):
                current_platform = platform
                break

        # 缓存搜索结果（包含当前平台和页码）
        _search_cache[chat_id] = {
            "keyword": keyword,
            "results": all_results,
            "message_id": status_msg.id,
            "platform": current_platform,
            "page": 0,
        }

        # 构建结果消息
        platform_name = PLATFORM_NAMES.get(current_platform, current_platform)
        songs = all_results.get(current_platform, [])

        # 统计各平台数量
        stats = " | ".join([
            f"{PLATFORM_EMOJI.get(p, '🎵')}{len(all_results.get(p, []))}"
            for p in PLATFORMS
        ])

        keyboard = build_platform_keyboard(songs, current_platform, PLATFORMS, chat_id, page=0)
        await status_msg.edit_text(
            f"🎵 **搜索: {keyword}**\n"
            f"📊 {stats}\n\n"
            f"当前: {PLATFORM_EMOJI.get(current_platform, '🎵')} {platform_name}",
            reply_markup=keyboard,
        )

        logger.info(f"Music search: {keyword}, total {total_count} songs")

    except Exception as e:
        logger.exception(f"Music search error: {e}")
        await status_msg.edit_text(f"❌ 搜索失败: {str(e)}")


@Client.on_callback_query(filters.regex(r"^msp:"))
async def music_platform_switch_callback(client: Client, callback: CallbackQuery):
    """处理平台切换回调"""
    data = callback.data.split(":")
    if len(data) < 2:
        await callback.answer("无效操作", show_alert=True)
        return

    action = data[1]
    chat_id = callback.message.chat.id

    # 返回搜索结果
    if action == "back":
        cache = _search_cache.get(chat_id)
        if not cache:
            await callback.answer("搜索已过期，请重新搜索", show_alert=True)
            return

        # 恢复搜索结果显示
        keyword = cache.get("keyword", "")
        all_results = cache.get("results", {})
        current_platform = cache.get("platform", "kuwo")
        page = cache.get("page", 0)

        platform_name = PLATFORM_NAMES.get(current_platform, current_platform)
        songs = all_results.get(current_platform, [])

        stats = " | ".join([
            f"{PLATFORM_EMOJI.get(p, '🎵')}{len(all_results.get(p, []))}"
            for p in PLATFORMS
        ])

        keyboard = build_platform_keyboard(songs, current_platform, PLATFORMS, chat_id, page=page)
        await callback.message.edit_text(
            f"🎵 **搜索: {keyword}**\n"
            f"📊 {stats}\n\n"
            f"当前: {PLATFORM_EMOJI.get(current_platform, '🎵')} {platform_name}",
            reply_markup=keyboard,
        )
        await callback.answer()
        return

    # 切换平台
    platform = action
    cache = _search_cache.get(chat_id)

    if not cache:
        await callback.answer("搜索已过期，请重新搜索", show_alert=True)
        return

    keyword = cache.get("keyword", "")
    all_results = cache.get("results", {})
    songs = all_results.get(platform, [])

    if not songs:
        await callback.answer(f"{PLATFORM_NAMES.get(platform, platform)} 无搜索结果", show_alert=True)
        return

    # 切换平台时重置页码
    cache["platform"] = platform
    cache["page"] = 0

    platform_name = PLATFORM_NAMES.get(platform, platform)

    stats = " | ".join([
        f"{PLATFORM_EMOJI.get(p, '🎵')}{len(all_results.get(p, []))}"
        for p in PLATFORMS
    ])

    keyboard = build_platform_keyboard(songs, platform, PLATFORMS, chat_id, page=0)
    await callback.message.edit_text(
        f"🎵 **搜索: {keyword}**\n"
        f"📊 {stats}\n\n"
        f"当前: {PLATFORM_EMOJI.get(platform, '🎵')} {platform_name}",
        reply_markup=keyboard,
    )
    await callback.answer()


@Client.on_callback_query(filters.regex(r"^mspg:"))
async def music_page_callback(client: Client, callback: CallbackQuery):
    """处理分页回调"""
    data = callback.data.split(":")
    if len(data) < 3:
        await callback.answer()
        return

    platform = data[1]
    if platform == "noop":
        await callback.answer()
        return

    try:
        page = int(data[2])
    except ValueError:
        await callback.answer("无效操作", show_alert=True)
        return

    chat_id = callback.message.chat.id
    cache = _search_cache.get(chat_id)

    if not cache:
        await callback.answer("搜索已过期，请重新搜索", show_alert=True)
        return

    keyword = cache.get("keyword", "")
    all_results = cache.get("results", {})
    songs = all_results.get(platform, [])

    if not songs:
        await callback.answer("无搜索结果", show_alert=True)
        return

    # 更新缓存中的页码
    cache["page"] = page
    cache["platform"] = platform

    platform_name = PLATFORM_NAMES.get(platform, platform)

    stats = " | ".join([
        f"{PLATFORM_EMOJI.get(p, '🎵')}{len(all_results.get(p, []))}"
        for p in PLATFORMS
    ])

    keyboard = build_platform_keyboard(songs, platform, PLATFORMS, chat_id, page=page)
    await callback.message.edit_text(
        f"🎵 **搜索: {keyword}**\n"
        f"📊 {stats}\n\n"
        f"当前: {PLATFORM_EMOJI.get(platform, '🎵')} {platform_name}",
        reply_markup=keyboard,
    )
    await callback.answer()


@Client.on_callback_query(filters.regex(r"^ms:"))
async def music_select_callback(client: Client, callback: CallbackQuery):
    """处理歌曲选择回调"""
    data = callback.data.split(":")

    if len(data) < 2:
        await callback.answer("无效操作", show_alert=True)
        return

    action = data[1]

    # 关闭按钮
    if action == "close":
        chat_id = callback.message.chat.id
        if chat_id in _search_cache:
            del _search_cache[chat_id]
        await callback.message.delete()
        await callback.answer("已关闭")
        return

    # 选择歌曲 - 显示音质选项
    if len(data) >= 3:
        source = data[1]
        song_id = data[2]

        keyboard = build_quality_keyboard(source, song_id)
        await callback.message.edit_text(
            "🎵 **选择音质**\n\n"
            "请选择需要的音质：",
            reply_markup=keyboard,
        )
        await callback.answer()


@Client.on_callback_query(filters.regex(r"^msq:"))
async def music_quality_callback(client: Client, callback: CallbackQuery):
    """处理音质选择回调"""
    data = callback.data.split(":")

    if len(data) < 4:
        await callback.answer("无效操作", show_alert=True)
        return

    source = data[1]
    song_id = data[2]
    quality = data[3]

    await callback.answer("🎵 正在解析，请稍候...")

    try:
        # 更新消息显示处理中
        await callback.message.edit_text("🎵 正在解析歌曲，请稍候...")

        result = await TuneHubAPI.parse_song(source, song_id, quality)

        if not result:
            await callback.message.edit_text(
                "❌ **解析失败**\n\n"
                "可能原因：\n"
                "• API Key 未配置或已过期\n"
                "• 积分不足\n"
                "• 该歌曲暂不支持解析\n\n"
                "请稍后重试或联系管理员"
            )
            return

        songs_data = result.get("data", [])
        if not songs_data:
            await callback.message.edit_text("❌ 未获取到歌曲信息")
            return

        song = songs_data[0]
        if not song.get("success", False):
            await callback.message.edit_text("❌ 解析失败，该歌曲可能不可用")
            return

        info = song.get("info", {})
        name = info.get("name", "未知歌曲")
        artist = info.get("artist", "未知艺术家")
        album = info.get("album", "")
        duration = info.get("duration", 0)
        url = song.get("url", "")
        cover_url = song.get("cover", "")

        if not url:
            await callback.message.edit_text("❌ 未获取到播放链接，该音质可能不可用")
            return

        # 更新状态：正在下载
        await callback.message.edit_text(f"⬇️ 正在下载「{name}」...")

        # 生成安全的文件名
        safe_name = "".join(c for c in f"{name} - {artist}" if c.isalnum() or c in " -_")[:50]
        actual_quality = song.get("actualQuality", quality)

        # 根据音质确定文件扩展名
        if "flac" in actual_quality.lower():
            ext = "flac"
        else:
            ext = "mp3"

        filename = f"{safe_name}_{song_id}.{ext}"

        # 下载音乐文件
        filepath = await TuneHubAPI.download_music(url, filename, source=source)

        if not filepath or not filepath.exists():
            await callback.message.edit_text("❌ 下载失败，请稍后重试")
            return

        # 更新状态：正在发送
        await callback.message.edit_text(f"📤 正在发送「{name}」...")

        # 准备封面图片
        thumb = None
        if cover_url:
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http_client:
                    cover_response = await http_client.get(cover_url)
                    if cover_response.status_code == 200:
                        thumb_path = MUSIC_TEMP_DIR / f"{song_id}_cover.jpg"
                        with open(thumb_path, "wb") as f:
                            f.write(cover_response.content)
                        thumb = str(thumb_path)
            except Exception as e:
                logger.warning(f"Failed to download cover: {e}")

        # 发送音频文件
        platform_name = PLATFORM_NAMES.get(source, source)
        emoji = PLATFORM_EMOJI.get(source, "🎵")
        quality_names = {
            "128k": "128K",
            "320k": "320K",
            "flac": "FLAC",
            "flac24bit": "Hi-Res",
        }
        quality_name = quality_names.get(actual_quality, actual_quality)

        caption = f"{emoji} {platform_name} | {quality_name}"
        if song.get("wasDowngraded", False):
            caption += " (已降级)"

        try:
            await client.send_audio(
                chat_id=callback.message.chat.id,
                audio=str(filepath),
                caption=caption,
                title=name,
                performer=artist,
                duration=duration,
                thumb=thumb,
                message_thread_id=callback.message.message_thread_id,  # 支持话题群组
            )

            # 删除搜索结果消息
            await callback.message.delete()

            logger.info(f"Music sent: {source}/{song_id} - {name}")

        finally:
            # 清理临时文件
            try:
                if filepath and filepath.exists():
                    filepath.unlink()
                if thumb and Path(thumb).exists():
                    Path(thumb).unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file: {e}")

    except Exception as e:
        logger.exception(f"Music parse error: {e}")
        await callback.message.edit_text(f"❌ 处理出错: {str(e)}")
