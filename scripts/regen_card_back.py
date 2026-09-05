"""
单独重新生成 card_back.png —— 精美牌背设计
在 Docker 容器内执行: docker exec kmua-bot uv run python scripts/regen_card_back.py [season_id]
"""
import asyncio
import math
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw, ImageFont

CARD_W, CARD_H = 512, 720
BASE_DIR = Path("/kmua/data/cards")


def _load_font(size, bold=True):
    paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_diamond(draw, cx, cy, r, **kw):
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    draw.polygon(pts, **kw)


def generate_card_back(season_name: str = "集换卡") -> Image.Image:
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # === 1. 深色渐变底色（用多层矩形模拟纵向渐变） ===
    steps = 60
    for i in range(steps):
        y0 = int(CARD_H * i / steps)
        y1 = int(CARD_H * (i + 1) / steps)
        t = i / steps
        r = int(18 + 14 * t)
        g = int(16 + 10 * t)
        b = int(38 + 18 * t)
        draw.rectangle([0, y0, CARD_W, y1], fill=(r, g, b))

    # 圆角遮罩
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], radius=16, fill=255)
    img.putalpha(mask)

    draw = ImageDraw.Draw(img)

    # === 2. 多层边框 ===
    # 外边框 - 金色
    draw.rounded_rectangle(
        [0, 0, CARD_W - 1, CARD_H - 1],
        radius=16, outline=(180, 150, 80), width=3
    )
    # 内边框 - 细金线
    draw.rounded_rectangle(
        [8, 8, CARD_W - 9, CARD_H - 9],
        radius=12, outline=(140, 115, 60, 160), width=1
    )
    # 第二内边框 - 更细的装饰线
    draw.rounded_rectangle(
        [14, 14, CARD_W - 15, CARD_H - 15],
        radius=10, outline=(100, 85, 50, 100), width=1
    )

    # === 3. 四角装饰 ===
    corner_r = 6
    corner_offsets = [
        (24, 24), (CARD_W - 25, 24),
        (24, CARD_H - 25), (CARD_W - 25, CARD_H - 25),
    ]
    for cx, cy in corner_offsets:
        _draw_diamond(draw, cx, cy, corner_r, fill=(180, 150, 80, 140))
        _draw_diamond(draw, cx, cy, corner_r - 2, outline=(220, 190, 100, 180), width=1)

    # === 4. 中心菱形纹理网格 ===
    grid_margin_x, grid_margin_y = 40, 60
    spacing = 36
    cols = (CARD_W - 2 * grid_margin_x) // spacing
    rows = (CARD_H - 2 * grid_margin_y) // spacing

    center_x = CARD_W / 2
    center_y = CARD_H / 2
    max_dist = math.hypot(CARD_W / 2, CARD_H / 2)

    for row in range(rows + 1):
        for col in range(cols + 1):
            x = grid_margin_x + col * spacing
            y = grid_margin_y + row * spacing
            dist = math.hypot(x - center_x, y - center_y)
            fade = max(0.0, 1.0 - dist / (max_dist * 0.55))
            alpha = int(35 * fade)
            if alpha < 5:
                continue
            r_size = int(4 + 4 * fade)
            _draw_diamond(draw, x, y, r_size, outline=(160, 140, 90, alpha), width=1)

    # === 5. 中央大菱形装饰框 ===
    big_r = 120
    _draw_diamond(draw, CARD_W // 2, CARD_H // 2, big_r,
                  outline=(180, 150, 80, 180), width=2)
    _draw_diamond(draw, CARD_W // 2, CARD_H // 2, big_r - 8,
                  outline=(140, 115, 60, 120), width=1)

    # === 6. 中央圆形光晕 ===
    glow_layer = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    for i in range(40, 0, -1):
        alpha = int(3 * (40 - i) / 40)
        r = 60 + i * 2
        glow_draw.ellipse(
            [CARD_W // 2 - r, CARD_H // 2 - r,
             CARD_W // 2 + r, CARD_H // 2 + r],
            fill=(200, 170, 100, alpha)
        )
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img)

    # === 7. 中央菱形图标（PIL绘制，替代不支持的 ✦ 字符） ===
    icon_r = 18
    icon_cy = int(CARD_H / 2 - 35)
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r, fill=(220, 190, 100))
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r - 4, fill=(240, 215, 130))
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r - 8, fill=(255, 240, 170))

    # === 8. 赛季/系列标识 ===
    season_font = _load_font(18, bold=False)
    season_text = f"—— {season_name} ——"
    sb = draw.textbbox((0, 0), season_text, font=season_font)
    sw = sb[2] - sb[0]
    draw.text(
        ((CARD_W - sw) / 2, CARD_H / 2 + 5),
        season_text, fill=(160, 145, 100, 220), font=season_font
    )

    # === 10. 上下装饰分隔线 ===
    line_y_top = 50
    line_y_bot = CARD_H - 51
    line_margin = 50
    draw.line(
        [(line_margin, line_y_top), (CARD_W - line_margin, line_y_top)],
        fill=(140, 115, 60, 80), width=1
    )
    draw.line(
        [(line_margin, line_y_bot), (CARD_W - line_margin, line_y_bot)],
        fill=(140, 115, 60, 80), width=1
    )

    # 分隔线中央小菱形
    for ly in [line_y_top, line_y_bot]:
        _draw_diamond(draw, CARD_W // 2, ly, 4, fill=(180, 150, 80, 140))

    return img


def main():
    season_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    async def get_season_name():
        from kmua.database import gacha as database
        season = await database.get_season_by_id(season_id)
        if not season:
            print(f"❌ 找不到赛季 {season_id}")
            sys.exit(1)
        return season.name

    season_name = asyncio.run(get_season_name())
    print(f"Generating card_back.png for season {season_id}: {season_name} ...")

    back = generate_card_back(season_name)
    back_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
    back_rgb.paste(back, mask=back)

    # 保存到对应赛季目录
    season_dir = BASE_DIR / f"season_{season_id}"
    season_dir.mkdir(parents=True, exist_ok=True)
    out = season_dir / "card_back.png"
    back_rgb.save(out, "PNG")
    print(f"✅ Saved to {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
