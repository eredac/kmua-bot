"""
生成32张占位卡牌图片（在Docker容器内运行）
用法: python scripts/generate_placeholder_cards.py

生成到 assets/cards/ 目录，按稀有度分色：
- 普通(1-14): 灰色
- 稀有(15-23): 蓝色
- 史诗(24-29): 紫色
- 传说(30-32): 金色
"""
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要 Pillow: pip install Pillow")
    raise SystemExit(1)

CARD_WIDTH = 300
CARD_HEIGHT = 420
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "cards"

RARITY_CONFIG = {
    "common": {"bg": (180, 180, 180), "border": (120, 120, 120), "label": "普通"},
    "rare": {"bg": (70, 130, 200), "border": (40, 80, 160), "label": "稀有"},
    "epic": {"bg": (150, 60, 200), "border": (100, 30, 160), "label": "史诗"},
    "legendary": {"bg": (220, 170, 40), "border": (180, 130, 20), "label": "传说"},
}

CARDS = []
n = 1
for i in range(14):
    CARDS.append((n, "common"))
    n += 1
for i in range(9):
    CARDS.append((n, "rare"))
    n += 1
for i in range(6):
    CARDS.append((n, "epic"))
    n += 1
for i in range(3):
    CARDS.append((n, "legendary"))
    n += 1


def generate_card(number: int, rarity: str) -> None:
    config = RARITY_CONFIG[rarity]
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), config["bg"])
    draw = ImageDraw.Draw(img)

    # 边框
    border_w = 8
    draw.rectangle(
        [border_w, border_w, CARD_WIDTH - border_w, CARD_HEIGHT - border_w],
        outline=config["border"],
        width=border_w,
    )

    # 中央大号数字
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # 卡号
    text = f"#{number}"
    bbox = draw.textbbox((0, 0), text, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((CARD_WIDTH - tw) / 2, (CARD_HEIGHT - th) / 2 - 30),
        text, fill="white", font=font_large,
    )

    # 稀有度标签
    label = config["label"]
    bbox2 = draw.textbbox((0, 0), label, font=font_small)
    lw = bbox2[2] - bbox2[0]
    draw.text(
        ((CARD_WIDTH - lw) / 2, CARD_HEIGHT - 60),
        label, fill="white", font=font_small,
    )

    output_path = OUTPUT_DIR / f"card_{number:02d}.png"
    img.save(output_path, "PNG")
    print(f"  生成: {output_path.name} ({rarity})")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"生成 {len(CARDS)} 张占位卡牌到 {OUTPUT_DIR}/")
    for number, rarity in CARDS:
        generate_card(number, rarity)
    print("完成！")


if __name__ == "__main__":
    main()
