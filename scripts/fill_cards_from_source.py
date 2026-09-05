"""
用 source 目录的图片随机铺满32张卡，加稀有度边框，生成翻牌GIF
用法: python scripts/fill_cards_from_source.py --season 1
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_W, CARD_H = 512, 720
BORDER = 4
BASE_DIR = Path("/kmua/data/cards")
SOURCE_DIR = BASE_DIR / "source"

RARITY_STYLE = {
    "common": {
        "border_color": (160, 160, 160),
        "glow": None,
        "label": "普通",
        "label_bg": (60, 60, 60, 180),
    },
    "rare": {
        "border_color": (60, 130, 220),
        "glow": (80, 160, 255, 60),
        "label": "稀有",
        "label_bg": (20, 60, 150, 180),
    },
    "epic": {
        "border_color": (150, 50, 200),
        "glow": (180, 80, 255, 60),
        "label": "史诗",
        "label_bg": (80, 20, 130, 180),
    },
    "legendary": {
        "border_color": (220, 170, 30),
        "glow": (255, 220, 60, 60),
        "label": "传说",
        "label_bg": (140, 100, 0, 200),
    },
}

# 卡牌配置: (card_number, source_filename, rarity, card_name, character_name)
CARD_CONFIG = [
    # === 普通 (12) ===
    (1, "羊角酒馆的甜酿师／玛卡巴卡.jpg", "common", "羊角酒馆的甜酿师", "玛卡巴卡"),
    (2, "月蓝狼契／熊猫.jpg", "common", "月蓝狼契", "熊猫"),
    (3, "血月霜羽术士／莹.jpg", "common", "血月霜羽术士", "莹"),
    (6, "墓园蓝焰骑士／匠爱.jpg", "common", "墓园蓝焰骑士", "匠爱"),
    (7, "月下触魂妖／唯.jpg", "common", "月下触魂妖", "唯"),
    (9, "灵灯炼金师／小岛.jpg", "common", "灵灯炼金师", "小岛"),
    (10, "晴穹弦歌者／小林.jpg", "common", "晴穹弦歌者", "小林"),
    (11, "龙骸余烬侍女／月落.jpg", "common", "龙骸余烬侍女", "月落"),
    (12, "赤潮回旋女巫／江祁.jpg", "common", "赤潮回旋女巫", "江祁"),
    (13, "金瞳酒窖游荡者／睦头人.jpg", "common", "金瞳酒窖游荡者", "睦头人"),
    (14, "寒星秘仪导师／饼干.jpg", "common", "寒星秘仪导师", "饼干"),
    (27, "霜刃酒歌剑士／霜寒.jpg", "common", "霜刃酒歌剑士", "霜寒"),
    # === 稀有 (11) ===
    (4, "月灯蜜誓／nim&萤.jpg", "rare", "月灯蜜誓", "nim&萤"),
    (5, "赤喉龙灾下的远征／cz&克兰.jpg", "rare", "赤喉龙灾下的远征", "cz&克兰"),
    (15, "绯樱狐巫／月绪.jpg", "rare", "绯樱狐巫", "月绪"),
    (16, "星渊蓝焰术士／星林.jpg", "rare", "星渊蓝焰术士", "星林"),
    (17, "霓虹酒窖魅影／染水.jpg", "rare", "霓虹酒窖魅影", "染水"),
    (18, "云上百花猎手／苏彍.jpg", "rare", "云上百花猎手", "苏彍"),
    (19, "锁链圣痕天使／墨雪.jpg", "rare", "锁链圣痕天使", "墨雪"),
    (20, "静默白袍牧师／辞白.jpg", "rare", "静默白袍牧师", "辞白"),
    (21, "倒悬囚笼的献祭者／熙饯.jpg", "rare", "倒悬囚笼的献祭者", "熙饯"),
    (22, "冰晶秘典师／米拉.jpg", "rare", "冰晶秘典师", "米拉"),
    (23, "深海宝箱怪／麟鲤.jpg", "rare", "深海宝箱怪", "麟鲤"),
    # === 史诗 (6) ===
    (8, "千眼玻璃囚徒／唯.jpg", "epic", "千眼玻璃囚徒", "唯"),
    (24, "熔脉斩首者／雪大王.jpg", "epic", "熔脉斩首者", "雪大王"),
    (25, "赤晶锁座女王／迦百璃.jpg", "epic", "赤晶锁座女王", "迦百璃"),
    (26, "焚心赤刃魔女／莉莉娅.jpg", "epic", "焚心赤刃魔女", "莉莉娅"),
    (28, "三相幻胶／梦&五&蕾米莉亚.jpg", "epic", "三相幻胶", "梦&五&蕾米莉亚"),
    (29, "翡翠星矢德鲁伊／玲.jpg", "epic", "翡翠星矢德鲁伊", "玲"),
    # === 传说 (3) ===
    (30, "暗炉三人密会／玛卡&熊猫&萤.jpg", "legendary", "暗炉三人密会", "玛卡&熊猫&萤"),
    (31, "血月亡军统领／简拉基茨德.jpg", "legendary", "血月亡军统领", "简拉基茨德"),
    (32, "倒悬霜翼／寒酥.jpg", "legendary", "倒悬霜翼", "寒酥"),
]


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


def _make_rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def generate_card_face(number: int, rarity: str, source_img: Image.Image, card_name: str = "", no_border: bool = False) -> Image.Image:
    style = RARITY_STYLE[rarity]
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角卡片底色
    draw.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], radius=12, fill=(20, 20, 20))

    # 素材图铺满卡面（仅留边框宽度）
    inner_x, inner_y = BORDER, BORDER
    inner_w, inner_h = CARD_W - 2 * BORDER, CARD_H - 2 * BORDER

    src = source_img.copy()
    src_ratio = src.width / src.height
    target_ratio = inner_w / inner_h

    if src_ratio > target_ratio:
        new_h = src.height
        new_w = int(new_h * target_ratio)
        left = (src.width - new_w) // 2
        src = src.crop((left, 0, left + new_w, new_h))
    else:
        new_w = src.width
        new_h = int(new_w / target_ratio)

        # Detect black borders at top and bottom edges (threshold: RGB < 20)
        import numpy as np
        arr = np.array(src)

        # Check top 5% rows for black content
        top_sample_height = max(1, int(src.height * 0.05))
        top_sample = arr[:top_sample_height, :, :]
        top_black_ratio = np.mean((top_sample < 20).all(axis=2))

        # Check bottom 5% rows for black content
        bot_sample = arr[-top_sample_height:, :, :]
        bot_black_ratio = np.mean((bot_sample < 20).all(axis=2))

        # If top has significantly more black (>30% black pixels), prefer bottom alignment
        if top_black_ratio > 0.3 and top_black_ratio > bot_black_ratio * 1.5:
            # Crop from bottom to preserve top content area
            top = max(0, src.height - new_h)
        elif bot_black_ratio > 0.3 and bot_black_ratio > top_black_ratio * 1.5:
            # Crop from top to preserve bottom content area
            top = 0
        else:
            # No significant black borders - use center crop
            top = (src.height - new_h) // 2

        src = src.crop((0, top, new_w, top + new_h))

    src = src.resize((inner_w, inner_h), Image.Resampling.LANCZOS).convert("RGBA")

    # 圆角遮罩
    mask = _make_rounded_mask((inner_w, inner_h), 8)
    img.paste(src, (inner_x, inner_y), mask)

    # 底部半透明标签条（叠加在图片上）— 仅带边框版
    if not no_border:
        label_h = 40
        label_y = CARD_H - BORDER - label_h
        overlay = Image.new("RGBA", (inner_w, label_h), style["label_bg"])
        img.paste(overlay, (BORDER, label_y), overlay)

        # 卡牌名文字（替代稀有度）
        font = _load_font(22)
        label_text = card_name if card_name else style["label"]
        bbox = draw.textbbox((0, 0), label_text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((CARD_W - tw) / 2, label_y + 8),
            label_text, fill="white", font=font
        )

    # 边框（细线）— 仅带边框版
    if not no_border:
        draw.rounded_rectangle(
            [0, 0, CARD_W - 1, CARD_H - 1],
            radius=12, outline=style["border_color"], width=BORDER
        )

    # 发光效果（稀有+）— 仅带边框版
    if style["glow"] and not no_border:
        for i in range(2):
            glow_color = style["glow"][:3] + (style["glow"][3] - i * 20,)
            draw.rounded_rectangle(
                [BORDER + i, BORDER + i, CARD_W - BORDER - 1 - i, CARD_H - BORDER - 1 - i],
                radius=9, outline=glow_color, width=1
            )

    return img


def _draw_diamond(draw, cx, cy, r, **kw):
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    draw.polygon(pts, **kw)


def generate_card_back(character_name: str = "", season_name: str = "龙与地下城") -> Image.Image:
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 深色渐变底色
    steps = 60
    for i in range(steps):
        y0 = int(CARD_H * i / steps)
        y1 = int(CARD_H * (i + 1) / steps)
        t = i / steps
        r = int(18 + 14 * t)
        g = int(16 + 10 * t)
        b = int(38 + 18 * t)
        draw.rectangle([0, y0, CARD_W, y1], fill=(r, g, b))

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], radius=16, fill=255)
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)

    # 多层金色边框
    draw.rounded_rectangle(
        [0, 0, CARD_W - 1, CARD_H - 1],
        radius=16, outline=(180, 150, 80), width=3
    )
    draw.rounded_rectangle(
        [8, 8, CARD_W - 9, CARD_H - 9],
        radius=12, outline=(140, 115, 60, 160), width=1
    )
    draw.rounded_rectangle(
        [14, 14, CARD_W - 15, CARD_H - 15],
        radius=10, outline=(100, 85, 50, 100), width=1
    )

    # 四角菱形装饰
    corner_r = 6
    corner_offsets = [
        (24, 24), (CARD_W - 25, 24),
        (24, CARD_H - 25), (CARD_W - 25, CARD_H - 25),
    ]
    for cx, cy in corner_offsets:
        _draw_diamond(draw, cx, cy, corner_r, fill=(180, 150, 80, 140))
        _draw_diamond(draw, cx, cy, corner_r - 2, outline=(220, 190, 100, 180), width=1)

    # 中心菱形纹理网格
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

    # 中央大菱形装饰框
    big_r = 120
    _draw_diamond(draw, CARD_W // 2, CARD_H // 2, big_r,
                  outline=(180, 150, 80, 180), width=2)
    _draw_diamond(draw, CARD_W // 2, CARD_H // 2, big_r - 8,
                  outline=(140, 115, 60, 120), width=1)

    # 中央圆形光晕
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

    # 中央菱形图标（PIL绘制，替代不支持的 ✦ 字符）
    icon_r = 18
    icon_cy = int(CARD_H / 2 - 35)
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r, fill=(220, 190, 100))
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r - 4, fill=(240, 215, 130))
    _draw_diamond(draw, CARD_W // 2, icon_cy, icon_r - 8, fill=(255, 240, 170))

    # 角色名（主要文字，醒目金色）
    if character_name:
        char_font = _load_font(28, bold=True)
        cb = draw.textbbox((0, 0), character_name, font=char_font)
        cw = cb[2] - cb[0]
        if cw > CARD_W - 2 * BORDER - 60:
            char_font = _load_font(22, bold=True)
            cb = draw.textbbox((0, 0), character_name, font=char_font)
            cw = cb[2] - cb[0]
        draw.text(
            ((CARD_W - cw) / 2, CARD_H / 2 + 5),
            character_name, fill=(230, 205, 130), font=char_font,
        )
        # 赛季标识
        season_font = _load_font(16, bold=False)
        season_text = f"—— {season_name} ——"
        sb = draw.textbbox((0, 0), season_text, font=season_font)
        sw = sb[2] - sb[0]
        draw.text(
            ((CARD_W - sw) / 2, CARD_H / 2 + 42),
            season_text, fill=(150, 135, 95, 220), font=season_font
        )
    else:
        # 无角色名时，仅显示赛季标识
        season_font = _load_font(18, bold=False)
        season_text = f"—— {season_name} ——"
        sb = draw.textbbox((0, 0), season_text, font=season_font)
        sw = sb[2] - sb[0]
        draw.text(
            ((CARD_W - sw) / 2, CARD_H / 2 + 5),
            season_text, fill=(160, 145, 100, 220), font=season_font
        )

    # 上下装饰分隔线
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
    for ly in [line_y_top, line_y_bot]:
        _draw_diamond(draw, CARD_W // 2, ly, 4, fill=(180, 150, 80, 140))

    return img


def generate_flip_gif(number: int, card_face: Image.Image, card_back: Image.Image, output_dir: Path) -> None:
    frames = []

    # 卡背静止展示 8 帧 × 80ms = 640ms
    for _ in range(8):
        frames.append(card_back.copy().convert("RGBA"))

    # 翻转动画 20 帧 × 80ms = 1600ms，余弦缓动
    flip_count = 20
    for i in range(flip_count):
        t = i / (flip_count - 1)
        width_ratio = abs(math.cos(t * math.pi))
        width_ratio = max(0.08, width_ratio)

        src = card_back if i < flip_count // 2 else card_face

        new_w = max(6, int(CARD_W * width_ratio))
        resized = src.resize((new_w, CARD_H), Image.Resampling.LANCZOS)

        frame = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        x_offset = (CARD_W - new_w) // 2
        frame.paste(resized, (x_offset, 0))
        frames.append(frame)

    # 卡面定格 1 帧，超长时长模拟停止（Telegram 会在此帧停住）
    frames.append(card_face.copy().convert("RGBA"))

    # 帧时长: 前面统一 80ms，最后一帧 30s 定格
    durations = [80] * (len(frames) - 1) + [30000]

    gif_frames = []
    for f in frames:
        bg = Image.new("RGBA", (CARD_W, CARD_H), (30, 30, 30, 255))
        bg.paste(f, mask=f)
        gif_frames.append(bg.convert("RGB"))

    out_path = output_dir / f"card_{number:02d}_flip.gif"
    gif_frames[0].save(
        out_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=durations,
        loop=1,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=1, help="赛季ID")
    args = parser.parse_args()

    output_dir = BASE_DIR / f"season_{args.season}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 校验素材文件是否齐全
    missing = []
    for number, src_file, rarity, card_name, char_name in CARD_CONFIG:
        if not (SOURCE_DIR / src_file).exists():
            missing.append(src_file)
    if missing:
        print(f"ERROR: Missing {len(missing)} source images in {SOURCE_DIR}:")
        for f in missing:
            print(f"  - {f}")
        raise SystemExit(1)

    print(f"All {len(CARD_CONFIG)} source images found, generating cards...")

    # 生成通用卡背
    back = generate_card_back()
    back_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
    back_rgb.paste(back, mask=back)
    back_rgb.save(BASE_DIR / "card_back.png", "PNG")
    print("Generated card_back.png")

    for number, src_file, rarity, card_name, char_name in CARD_CONFIG:
        src_path = SOURCE_DIR / src_file
        src_img = Image.open(src_path).convert("RGBA")
        face = generate_card_face(number, rarity, src_img, card_name)

        # 保存PNG（带边框，用于缩略图/网格）
        face_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
        face_rgb.paste(face, mask=face)
        face_rgb.save(output_dir / f"card_{number:02d}.png", "PNG")

        # 保存无边框版本（用于详情查看）
        face_noframe = generate_card_face(number, rarity, src_img, card_name, no_border=True)
        nf_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
        nf_rgb.paste(face_noframe, mask=face_noframe)
        nf_rgb.save(output_dir / f"card_{number:02d}_full.png", "PNG")

        # 生成带人物名的个性化卡背用于翻牌GIF
        card_back_personal = generate_card_back(char_name, "龙与地下城")
        generate_flip_gif(number, face, card_back_personal, output_dir)

        # 保存个性化卡背PNG（供MP4动画使用）
        back_personal_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
        back_personal_rgb.paste(card_back_personal, mask=card_back_personal)
        back_personal_rgb.save(output_dir / f"card_{number:02d}_back.png", "PNG")

        print(f"  #{number:02d} ({rarity}) {card_name} [{char_name}] <- {src_file}")

    print(f"Done! {len(CARD_CONFIG)} cards generated to {output_dir}")


if __name__ == "__main__":
    main()
