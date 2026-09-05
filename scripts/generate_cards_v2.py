"""
生成32张卡牌PNG + 翻牌GIF动画
输出到 data/cards/ 目录（通过 Docker volume 持久化）

每张卡生成:
  - card_{nn}.png  (静态卡面)
  - card_{nn}_flip.gif (翻牌动画)
  - card_back.png (卡背，共用)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_W, CARD_H = 300, 420
BORDER = 12
BASE_DIR = Path("/kmua/data/cards")

RARITY_STYLE = {
    "common": {
        "bg": (200, 200, 200),
        "border": (140, 140, 140),
        "glow": None,
        "label": "普通",
    },
    "rare": {
        "bg": (50, 120, 210),
        "border": (30, 80, 180),
        "glow": (80, 160, 255),
        "label": "稀有",
    },
    "epic": {
        "bg": (130, 40, 190),
        "border": (100, 20, 160),
        "glow": (180, 80, 255),
        "label": "史诗",
    },
    "legendary": {
        "bg": (230, 180, 30),
        "border": (200, 150, 10),
        "glow": (255, 220, 60),
        "label": "传说",
    },
}

CARDS = []
n = 1
for _ in range(14):
    CARDS.append((n, "common")); n += 1
for _ in range(9):
    CARDS.append((n, "rare")); n += 1
for _ in range(6):
    CARDS.append((n, "epic")); n += 1
for _ in range(3):
    CARDS.append((n, "legendary")); n += 1

# PLACEHOLDER_CONTENT


def _load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=0):
    x0, y0, x1, y1 = bbox
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)


def generate_card_face(number: int, rarity: str) -> Image.Image:
    style = RARITY_STYLE[rarity]
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角卡片背景
    _draw_rounded_rect(draw, [0, 0, CARD_W - 1, CARD_H - 1], 16, fill=style["bg"])

    # 稀有度发光边框
    if style["glow"]:
        for i in range(3):
            glow_color = (*style["glow"], 80 - i * 20)
            _draw_rounded_rect(
                draw,
                [BORDER - 4 + i, BORDER - 4 + i, CARD_W - BORDER + 3 - i, CARD_H - BORDER + 3 - i],
                12, fill=None, outline=glow_color, width=2
            )

    # 内边框
    _draw_rounded_rect(
        draw,
        [BORDER, BORDER, CARD_W - BORDER, CARD_H - BORDER],
        10, fill=None, outline=style["border"], width=4
    )

    # 中央大号数字
    font_large = _load_font(72)
    font_small = _load_font(22)

    text = f"#{number}"
    bbox = draw.textbbox((0, 0), text, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((CARD_W - tw) / 2, (CARD_H - th) / 2 - 30),
        text, fill="white", font=font_large,
    )

    # 稀有度标签
    label = style["label"]
    bbox2 = draw.textbbox((0, 0), label, font=font_small)
    lw = bbox2[2] - bbox2[0]
    draw.text(
        ((CARD_W - lw) / 2, CARD_H - 55),
        label, fill=(255, 255, 255, 200), font=font_small,
    )

    return img


def generate_card_back() -> Image.Image:
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    _draw_rounded_rect(draw, [0, 0, CARD_W - 1, CARD_H - 1], 16, fill=(40, 40, 60))
    _draw_rounded_rect(draw, [BORDER, BORDER, CARD_W - BORDER, CARD_H - BORDER],
                       10, fill=None, outline=(80, 80, 120), width=3)

    # 菱形纹理
    font = _load_font(36)
    draw.text((CARD_W // 2 - 18, CARD_H // 2 - 25), "🃏", font=font)

    font_s = _load_font(16)
    txt = "GACHA"
    bb = draw.textbbox((0, 0), txt, font=font_s)
    draw.text(((CARD_W - bb[2] + bb[0]) / 2, CARD_H // 2 + 25), txt, fill=(120, 120, 160), font=font_s)

    return img


def generate_flip_gif(number: int, rarity: str, card_face: Image.Image, card_back: Image.Image, output_dir: Path) -> None:
    frames = []
    total_frames = 12
    pause_frames = 3

    for _ in range(pause_frames):
        frames.append(card_back.copy().convert("RGBA"))

    flip_frames = total_frames - pause_frames
    mid = flip_frames // 2

    for i in range(flip_frames):
        if i < mid:
            progress = 1.0 - (i / mid)
            src = card_back
        else:
            progress = (i - mid) / (flip_frames - mid - 1) if flip_frames - mid > 1 else 1.0
            src = card_face

        new_w = max(4, int(CARD_W * max(0.05, progress)))
        resized = src.resize((new_w, CARD_H), Image.Resampling.LANCZOS)

        frame = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        x_offset = (CARD_W - new_w) // 2
        frame.paste(resized, (x_offset, 0))
        frames.append(frame)

    for _ in range(pause_frames):
        frames.append(card_face.copy().convert("RGBA"))

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
        duration=[300] * pause_frames + [60] * flip_frames + [800] * pause_frames,
        loop=0,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=1, help="赛季ID")
    args = parser.parse_args()

    OUTPUT = BASE_DIR / f"season_{args.season}"
    OUTPUT.mkdir(parents=True, exist_ok=True)

    back = generate_card_back()
    back_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
    back_rgb.paste(back, mask=back)
    back_rgb.save(BASE_DIR / "card_back.png", "PNG")
    print("Generated card_back.png")

    for number, rarity in CARDS:
        face = generate_card_face(number, rarity)

        face_rgb = Image.new("RGB", (CARD_W, CARD_H), (30, 30, 30))
        face_rgb.paste(face, mask=face)
        face_rgb.save(OUTPUT / f"card_{number:02d}.png", "PNG")

        generate_flip_gif(number, rarity, face, back, OUTPUT)
        print(f"  #{number:02d} ({rarity}) - png + gif")

    print(f"Done! {len(CARDS)} cards generated to {OUTPUT}")


if __name__ == "__main__":
    main()
