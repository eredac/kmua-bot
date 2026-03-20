"""
占卜功能插件
从 hktrpg-bot 迁移的占卜系统
包含：塔罗牌、时间塔罗、大十字塔罗、浅草签、运势
"""
import json
import random
from pathlib import Path

import httpx
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message

# ── 资产路径 ──────────────────────────────────────────────
_PLUGIN_DIR = Path(__file__).parent
_ASAKUSA_PATH = _PLUGIN_DIR / "Asakusa100.json"

# ── 浅草签数据 ─────────────────────────────────────────────
def _load_asakusa() -> list[str]:
    try:
        with open(_ASAKUSA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("json", [])
    except Exception as e:
        logger.error(f"[divination] 加载浅草签失败: {e}")
        return []

_ASAKUSA_LIST: list[str] = _load_asakusa()

# ── 运势列表 ──────────────────────────────────────────────
_LUCK_LIST = [
    "超吉", "超级上吉", "大吉", "吉", "中吉", "小吉", "吉", "小吉",
    "吉", "吉", "中吉", "吉", "中吉", "吉", "中吉", "小吉", "末吉",
    "吉", "中吉", "小吉", "末吉", "中吉", "小吉", "小吉", "吉", "小吉",
    "末吉", "中吉", "小吉", "凶", "小凶", "没凶", "大凶", "很凶",
    "你不要知道比较好呢", "命运在手中，何必问我",
]

# ── 塔罗牌（含正逆位 + 图片 URL）────────────────────────────
_BASE = "https://raw.githubusercontent.com/hktrpg/TG.line.Discord.Roll.Bot/master/assets/tarot"
_TAROT_LIST = [
    # ── 大阿尔卡纳 正位 ──
    ("愚者 ＋",       f"{_BASE}/00.jpg"),
    ("魔术师 ＋",     f"{_BASE}/01.jpg"),
    ("女祭司 ＋",     f"{_BASE}/02.jpg"),
    ("女皇 ＋",       f"{_BASE}/03.jpg"),
    ("皇帝 ＋",       f"{_BASE}/04.jpg"),
    ("教皇 ＋",       f"{_BASE}/05.jpg"),
    ("恋人 ＋",       f"{_BASE}/06.jpg"),
    ("战车 ＋",       f"{_BASE}/07.jpg"),
    ("力量 ＋",       f"{_BASE}/08.jpg"),
    ("隐者 ＋",       f"{_BASE}/09.jpg"),
    ("命运之轮 ＋",   f"{_BASE}/10.jpg"),
    ("正义 ＋",       f"{_BASE}/11.jpg"),
    ("吊人 ＋",       f"{_BASE}/12.jpg"),
    ("死神 ＋",       f"{_BASE}/13.jpg"),
    ("节制 ＋",       f"{_BASE}/14.jpg"),
    ("恶魔 ＋",       f"{_BASE}/15.jpg"),
    ("高塔 ＋",       f"{_BASE}/16.jpg"),
    ("星星 ＋",       f"{_BASE}/17.jpg"),
    ("月亮 ＋",       f"{_BASE}/18.jpg"),
    ("太阳 ＋",       f"{_BASE}/19.jpg"),
    ("审判 ＋",       f"{_BASE}/20.jpg"),
    ("世界 ＋",       f"{_BASE}/21.jpg"),
    # ── 大阿尔卡纳 逆位 ──
    ("愚者 －",       f"{_BASE}/00-Re.jpg"),
    ("魔术师 －",     f"{_BASE}/01-Re.jpg"),
    ("女祭司 －",     f"{_BASE}/02-Re.jpg"),
    ("女皇 －",       f"{_BASE}/03-Re.jpg"),
    ("皇帝 －",       f"{_BASE}/04-Re.jpg"),
    ("教皇 －",       f"{_BASE}/05-Re.jpg"),
    ("恋人 －",       f"{_BASE}/06-Re.jpg"),
    ("战车 －",       f"{_BASE}/07-Re.jpg"),
    ("力量 －",       f"{_BASE}/08-Re.jpg"),
    ("隐者 －",       f"{_BASE}/09-Re.jpg"),
    ("命运之轮 －",   f"{_BASE}/10-Re.jpg"),
    ("正义 －",       f"{_BASE}/11-Re.jpg"),
    ("吊人 －",       f"{_BASE}/12-Re.jpg"),
    ("死神 －",       f"{_BASE}/13-Re.jpg"),
    ("节制 －",       f"{_BASE}/14-Re.jpg"),
    ("恶魔 －",       f"{_BASE}/15-Re.jpg"),
    ("高塔 －",       f"{_BASE}/16-Re.jpg"),
    ("星星 －",       f"{_BASE}/17-Re.jpg"),
    ("月亮 －",       f"{_BASE}/18-Re.jpg"),
    ("太阳 －",       f"{_BASE}/19-Re.jpg"),
    ("审判 －",       f"{_BASE}/20-Re.jpg"),
    ("世界 －",       f"{_BASE}/21-Re.jpg"),
    # ── 小阿尔卡纳 圣杯 ──
    ("圣杯一 ＋",     f"{_BASE}/CUPS_01.jpg"),
    ("圣杯二 ＋",     f"{_BASE}/CUPS_02.jpg"),
    ("圣杯三 ＋",     f"{_BASE}/CUPS_03.jpg"),
    ("圣杯四 ＋",     f"{_BASE}/CUPS_04.jpg"),
    ("圣杯五 ＋",     f"{_BASE}/CUPS_05.jpg"),
    ("圣杯六 ＋",     f"{_BASE}/CUPS_06.jpg"),
    ("圣杯七 ＋",     f"{_BASE}/CUPS_07.jpg"),
    ("圣杯八 ＋",     f"{_BASE}/CUPS_08.jpg"),
    ("圣杯九 ＋",     f"{_BASE}/CUPS_09.jpg"),
    ("圣杯十 ＋",     f"{_BASE}/CUPS_10.jpg"),
    ("圣杯国王 ＋",   f"{_BASE}/CUPS_KING.jpg"),
    ("圣杯骑士 ＋",   f"{_BASE}/CUPS_KNIGHT.jpg"),
    ("圣杯侍者 ＋",   f"{_BASE}/CUPS_PAGE.jpg"),
    ("圣杯皇后 ＋",   f"{_BASE}/CUPS_QUEEN.jpg"),
    ("圣杯一 －",     f"{_BASE}/CUPS_01-Re.jpg"),
    ("圣杯二 －",     f"{_BASE}/CUPS_02-Re.jpg"),
    ("圣杯三 －",     f"{_BASE}/CUPS_03-Re.jpg"),
    ("圣杯四 －",     f"{_BASE}/CUPS_04-Re.jpg"),
    ("圣杯五 －",     f"{_BASE}/CUPS_05-Re.jpg"),
    ("圣杯六 －",     f"{_BASE}/CUPS_06-Re.jpg"),
    ("圣杯七 －",     f"{_BASE}/CUPS_07-Re.jpg"),
    ("圣杯八 －",     f"{_BASE}/CUPS_08-Re.jpg"),
    ("圣杯九 －",     f"{_BASE}/CUPS_09-Re.jpg"),
    ("圣杯十 －",     f"{_BASE}/CUPS_10-Re.jpg"),
    ("圣杯国王 －",   f"{_BASE}/CUPS_KING-Re.jpg"),
    ("圣杯骑士 －",   f"{_BASE}/CUPS_KNIGHT-Re.jpg"),
    ("圣杯侍者 －",   f"{_BASE}/CUPS_PAGE-Re.jpg"),
    ("圣杯皇后 －",   f"{_BASE}/CUPS_QUEEN-Re.jpg"),
    # ── 小阿尔卡纳 钱币 ──
    ("钱币一 ＋",     f"{_BASE}/PANTA_01.jpg"),
    ("钱币二 ＋",     f"{_BASE}/PANTA_02.jpg"),
    ("钱币三 ＋",     f"{_BASE}/PANTA_03.jpg"),
    ("钱币四 ＋",     f"{_BASE}/PANTA_04.jpg"),
    ("钱币五 ＋",     f"{_BASE}/PANTA_05.jpg"),
    ("钱币六 ＋",     f"{_BASE}/PANTA_06.jpg"),
    ("钱币七 ＋",     f"{_BASE}/PANTA_07.jpg"),
    ("钱币八 ＋",     f"{_BASE}/PANTA_08.jpg"),
    ("钱币九 ＋",     f"{_BASE}/PANTA_09.jpg"),
    ("钱币十 ＋",     f"{_BASE}/PANTA_10.jpg"),
    ("钱币国王 ＋",   f"{_BASE}/PANTA_KING.jpg"),
    ("钱币骑士 ＋",   f"{_BASE}/PANTA_KNIGHT.jpg"),
    ("钱币侍者 ＋",   f"{_BASE}/PANTA_PAGE.jpg"),
    ("钱币皇后 ＋",   f"{_BASE}/PANTA_QUEEN.jpg"),
    ("钱币一 －",     f"{_BASE}/PANTA_01-Re.jpg"),
    ("钱币二 －",     f"{_BASE}/PANTA_02-Re.jpg"),
    ("钱币三 －",     f"{_BASE}/PANTA_03-Re.jpg"),
    ("钱币四 －",     f"{_BASE}/PANTA_04-Re.jpg"),
    ("钱币五 －",     f"{_BASE}/PANTA_05-Re.jpg"),
    ("钱币六 －",     f"{_BASE}/PANTA_06-Re.jpg"),
    ("钱币七 －",     f"{_BASE}/PANTA_07-Re.jpg"),
    ("钱币八 －",     f"{_BASE}/PANTA_08-Re.jpg"),
    ("钱币九 －",     f"{_BASE}/PANTA_09-Re.jpg"),
    ("钱币十 －",     f"{_BASE}/PANTA_10-Re.jpg"),
    ("钱币国王 －",   f"{_BASE}/PANTA_KING-Re.jpg"),
    ("钱币骑士 －",   f"{_BASE}/PANTA_KNIGHT-Re.jpg"),
    ("钱币侍者 －",   f"{_BASE}/PANTA_PAGE-Re.jpg"),
    ("钱币皇后 －",   f"{_BASE}/PANTA_QUEEN-Re.jpg"),
    # ── 小阿尔卡纳 宝剑 ──
    ("宝剑一 ＋",     f"{_BASE}/SWORDS_01.jpg"),
    ("宝剑二 ＋",     f"{_BASE}/SWORDS_02.jpg"),
    ("宝剑三 ＋",     f"{_BASE}/SWORDS_03.jpg"),
    ("宝剑四 ＋",     f"{_BASE}/SWORDS_04.jpg"),
    ("宝剑五 ＋",     f"{_BASE}/SWORDS_05.jpg"),
    ("宝剑六 ＋",     f"{_BASE}/SWORDS_06.jpg"),
    ("宝剑七 ＋",     f"{_BASE}/SWORDS_07.jpg"),
    ("宝剑八 ＋",     f"{_BASE}/SWORDS_08.jpg"),
    ("宝剑九 ＋",     f"{_BASE}/SWORDS_09.jpg"),
    ("宝剑十 ＋",     f"{_BASE}/SWORDS_10.jpg"),
    ("宝剑国王 ＋",   f"{_BASE}/SWORDS_KING.jpg"),
    ("宝剑骑士 ＋",   f"{_BASE}/SWORDS_KNIGHT.jpg"),
    ("宝剑侍者 ＋",   f"{_BASE}/SWORDS_PAGE.jpg"),
    ("宝剑皇后 ＋",   f"{_BASE}/SWORDS_QUEEN.jpg"),
    ("宝剑一 －",     f"{_BASE}/SWORDS_01-Re.jpg"),
    ("宝剑二 －",     f"{_BASE}/SWORDS_02-Re.jpg"),
    ("宝剑三 －",     f"{_BASE}/SWORDS_03-Re.jpg"),
    ("宝剑四 －",     f"{_BASE}/SWORDS_04-Re.jpg"),
    ("宝剑五 －",     f"{_BASE}/SWORDS_05-Re.jpg"),
    ("宝剑六 －",     f"{_BASE}/SWORDS_06-Re.jpg"),
    ("宝剑七 －",     f"{_BASE}/SWORDS_07-Re.jpg"),
    ("宝剑八 －",     f"{_BASE}/SWORDS_08-Re.jpg"),
    ("宝剑九 －",     f"{_BASE}/SWORDS_09-Re.jpg"),
    ("宝剑十 －",     f"{_BASE}/SWORDS_10-Re.jpg"),
    ("宝剑国王 －",   f"{_BASE}/SWORDS_KING-Re.jpg"),
    ("宝剑骑士 －",   f"{_BASE}/SWORDS_KNIGHT-Re.jpg"),
    ("宝剑侍者 －",   f"{_BASE}/SWORDS_PAGE-Re.jpg"),
    ("宝剑皇后 －",   f"{_BASE}/SWORDS_QUEEN-Re.jpg"),
    # ── 小阿尔卡纳 权杖 ──
    ("权杖一 ＋",     f"{_BASE}/WANDS_01.jpg"),
    ("权杖二 ＋",     f"{_BASE}/WANDS_02.jpg"),
    ("权杖三 ＋",     f"{_BASE}/WANDS_03.jpg"),
    ("权杖四 ＋",     f"{_BASE}/WANDS_04.jpg"),
    ("权杖五 ＋",     f"{_BASE}/WANDS_05.jpg"),
    ("权杖六 ＋",     f"{_BASE}/WANDS_06.jpg"),
    ("权杖七 ＋",     f"{_BASE}/WANDS_07.jpg"),
    ("权杖八 ＋",     f"{_BASE}/WANDS_08.jpg"),
    ("权杖九 ＋",     f"{_BASE}/WANDS_09.jpg"),
    ("权杖十 ＋",     f"{_BASE}/WANDS_10.jpg"),
    ("权杖国王 ＋",   f"{_BASE}/WANDS_KING.jpg"),
    ("权杖骑士 ＋",   f"{_BASE}/WANDS_KNIGHT.jpg"),
    ("权杖侍者 ＋",   f"{_BASE}/WANDS_PAGE.jpg"),
    ("权杖皇后 ＋",   f"{_BASE}/WANDS_QUEEN.jpg"),
    ("权杖一 －",     f"{_BASE}/WANDS_01-Re.jpg"),
    ("权杖二 －",     f"{_BASE}/WANDS_02-Re.jpg"),
    ("权杖三 －",     f"{_BASE}/WANDS_03-Re.jpg"),
    ("权杖四 －",     f"{_BASE}/WANDS_04-Re.jpg"),
    ("权杖五 －",     f"{_BASE}/WANDS_05-Re.jpg"),
    ("权杖六 －",     f"{_BASE}/WANDS_06-Re.jpg"),
    ("权杖七 －",     f"{_BASE}/WANDS_07-Re.jpg"),
    ("权杖八 －",     f"{_BASE}/WANDS_08-Re.jpg"),
    ("权杖九 －",     f"{_BASE}/WANDS_09-Re.jpg"),
    ("权杖十 －",     f"{_BASE}/WANDS_10-Re.jpg"),
    ("权杖国王 －",   f"{_BASE}/WANDS_KING-Re.jpg"),
    ("权杖骑士 －",   f"{_BASE}/WANDS_KNIGHT-Re.jpg"),
    ("权杖侍者 －",   f"{_BASE}/WANDS_PAGE-Re.jpg"),
    ("权杖皇后 －",   f"{_BASE}/WANDS_QUEEN-Re.jpg"),
]

# 仅用于多牌展开（时间/大十字），纯文字无图片
_TAROT_NAMES = [name for name, _ in _TAROT_LIST]


# ── 工具函数 ──────────────────────────────────────────────
def _shuffle_draw(lst: list, n: int) -> list:
    """洗牌后取前 n 张"""
    pool = lst.copy()
    random.shuffle(pool)
    return pool[:n]


# ── 指令处理器 ────────────────────────────────────────────

@Client.on_message(filters.regex(r"^每日(塔罗|塔羅)"))
async def tarot_daily_handler(client: Client, message: Message):
    """每日塔罗：抽一张牌，显示牌名及图片"""
    name, img_url = random.choice(_TAROT_LIST)
    caption = f"🔮 **每日塔罗**\n\n{name}"
    try:
        await message.reply_photo(photo=img_url, caption=caption)
    except Exception as e:
        logger.warning(f"[divination] 发送塔罗图片失败，改为文字: {e}")
        await message.reply(f"🔮 **每日塔罗**\n\n{name}\n{img_url}")


@Client.on_message(filters.regex(r"^(时间|時間)(塔罗|塔羅)"))
async def tarot_time_handler(client: Client, message: Message):
    """时间塔罗：过去 / 现在 / 未来 三张牌"""
    parts = message.text.split(None, 1)
    topic = f"；{parts[1]}" if len(parts) > 1 else ""
    cards = _shuffle_draw(_TAROT_NAMES, 3)
    text = (
        f"🕰️ **时间塔罗**{topic}\n\n"
        f"过去：{cards[0]}\n"
        f"现在：{cards[1]}\n"
        f"未来：{cards[2]}"
    )
    await message.reply(text)


@Client.on_message(filters.regex(r"^大十字(塔罗|塔羅)"))
async def tarot_cross_handler(client: Client, message: Message):
    """大十字塔罗：十张牌展开"""
    parts = message.text.split(None, 1)
    topic = f"；{parts[1]}" if len(parts) > 1 else ""
    cards = _shuffle_draw(_TAROT_NAMES, 10)
    text = (
        f"✝️ **大十字塔罗**{topic}\n\n"
        f"现况：{cards[0]}\n"
        f"助力：{cards[1]}\n"
        f"目标：{cards[2]}\n"
        f"基础：{cards[3]}\n"
        f"过去：{cards[4]}\n"
        f"未来：{cards[5]}\n"
        f"自我：{cards[6]}\n"
        f"环境：{cards[7]}\n"
        f"恐惧：{cards[8]}\n"
        f"结论：{cards[9]}"
    )
    await message.reply(text)


@Client.on_message(filters.regex(r"^每日(浅草签|淺草簽)"))
async def asakusa_handler(client: Client, message: Message):
    """每日浅草签：从百签中随机抽取"""
    if not _ASAKUSA_LIST:
        await message.reply("⚠️ 浅草签数据加载失败，请检查 Asakusa100.json")
        return
    result = random.choice(_ASAKUSA_LIST)
    await message.reply(f"🎋 **浅草签**\n\n{result}")


@Client.on_message(filters.regex(r"(运势|運勢)"))
async def luck_handler(client: Client, message: Message):
    """运势：为对象随机判断运势等级"""
    args = message.text.split()[1:]  # 去掉触发词本身
    if not args:
        # 无参数时为发送者占卜
        name = message.from_user.first_name if message.from_user else "你"
        result = f"{name}：{random.choice(_LUCK_LIST)}"
    elif len(args) == 1:
        result = f"{args[0]}：{random.choice(_LUCK_LIST)}"
    else:
        # 多个对象，每行两个，最多 20 个
        targets = args[:20]
        lines = []
        for i in range(0, len(targets), 2):
            left = f"{targets[i]}：{random.choice(_LUCK_LIST)}"
            if i + 1 < len(targets):
                right = f"{targets[i+1]}：{random.choice(_LUCK_LIST)}"
                lines.append(f"{left}\t{right}")
            else:
                lines.append(left)
        result = "\n".join(lines)
    await message.reply(f"🎯 **运势**\n\n{result}")


# ── 星座数据 ───────────────────────────────────────────────
# 别名 → API 查询名（简体）
_ZODIAC_MAP: dict[str, str] = {
    "白羊": "白羊", "牡羊": "白羊",
    "金牛": "金牛",
    "双子": "双子", "雙子": "双子",
    "巨蟹": "巨蟹",
    "狮子": "狮子", "獅子": "狮子",
    "处女": "处女", "處女": "处女",
    "天秤": "天秤", "天平": "天秤",
    "天蝎": "天蝎", "天蠍": "天蝎",
    "射手": "射手", "人马": "射手", "人馬": "射手",
    "摩羯": "摩羯", "山羊": "摩羯",
    "水瓶": "水瓶", "宝瓶": "水瓶", "寶瓶": "水瓶",
    "双鱼": "双鱼", "雙魚": "双鱼",
}

# click108 星座编号（0-11）
_ZODIAC_CODES: dict[str, int] = {
    "白羊": 0, "金牛": 1, "双子": 2, "巨蟹": 3,
    "狮子": 4, "处女": 5, "天秤": 6, "天蝎": 7,
    "射手": 8, "摩羯": 9, "水瓶": 10, "双鱼": 11,
}

_ZODIAC_PATTERN = (
    r"^每日(白羊|牡羊|金牛|双子|雙子|巨蟹|狮子|獅子|处女|處女"
    r"|天秤|天平|天蝎|天蠍|射手|人马|人馬|摩羯|山羊|水瓶|宝瓶|寶瓶|双鱼|雙魚)$"
)


async def _fetch_zodiac(name: str) -> str | None:
    """抓取星座运程，优先 click108，失败后尝试 vvhan API"""
    import re as _re
    from datetime import datetime

    code = _ZODIAC_CODES.get(name)
    if code is not None:
        date = datetime.now().strftime("%Y-%m-%d")
        url = f"https://astro.click108.com.tw/daily_{code}.php?iAcDay={date}&iAstro={code}"
        try:
            async with httpx.AsyncClient(timeout=10, verify=False, follow_redirects=True) as hc:
                resp = await hc.get(url)
                html = resp.text
            content_m = _re.search(
                r'class="TODAY_CONTENT[^"]*"[^>]*>(.*?)</div>', html, _re.DOTALL
            )
            word_m = _re.search(
                r'class="TODAY_WORD[^"]*"[^>]*>(.*?)</div>', html, _re.DOTALL
            )
            if content_m:
                def strip_tags(s: str) -> str:
                    return _re.sub(r"<[^>]+>", "", s).strip()
                raw = strip_tags(content_m.group(1))
                # 清理：去掉 h3 标题行、多余空白，每行对齐
                lines = [l.strip() for l in raw.splitlines()]
                lines = [l for l in lines if l and not _re.match(r"^今日\S+解析$", l)]
                content = "\n".join(lines)
                word = strip_tags(word_m.group(1)) if word_m else ""
                if content:
                    return f"「{word}」\n{content}" if word else content
        except Exception as e:
            logger.warning(f"[divination] click108 请求失败 ({name}): {e}")

    # 备用：lkaa.top（原 ovooa.com 镜像，HTTP）
    for base in ("http://lkaa.top", "https://ovooa.com"):
        try:
            url2 = f"{base}/API/xz/api.php?msg={name}&type=json"
            async with httpx.AsyncClient(timeout=10, verify=False) as hc:
                resp = await hc.get(url2)
                logger.debug(f"[divination] {base} status={resp.status_code} body={resp.text[:200]}")
                if not resp.text.strip():
                    continue
                data = resp.json()
                # 兼容多层嵌套结构：data.data.text / data.text / data.data.Msg
                inner = data.get("data") or {}
                if isinstance(inner, dict):
                    text = (inner.get("text") or inner.get("Msg")
                            or inner.get("title") or "")
                else:
                    text = str(inner) if inner else ""
                if not text:
                    text = data.get("text") or data.get("title") or ""
                text = text.replace("\\r", "\n").replace("\\n", "\n").strip()
                if text and text not in ("获取成功",):
                    return text
        except Exception as e:
            logger.warning(f"[divination] {base} 请求失败 ({name}): {repr(e)}")

    return None


@Client.on_message(filters.regex(_ZODIAC_PATTERN))
async def zodiac_handler(client: Client, message: Message):
    """每日星座运程"""
    import re
    m = re.search(_ZODIAC_PATTERN, message.text or "")
    if not m:
        return
    alias = m.group(1)
    canonical = _ZODIAC_MAP.get(alias, alias)

    text = await _fetch_zodiac(canonical)
    if not text:
        await message.reply(f"⭐ **每日{canonical}座**\n\n暂时无法获取今日运程，请稍后再试喵～")
        return

    await message.reply(f"⭐ **每日{canonical}座**\n\n{text}")
