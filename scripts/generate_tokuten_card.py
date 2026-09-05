"""
生成特典卡 (横版卡片 720×512)
特典卡在用户集齐32张卡后自动解锁

使用参考图片生成特典卡面
输出到 data/cards/tokuten/ 目录
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 横版尺寸
TOKUTEN_W, TOKUTEN_H = 720, 512
BORDER = 16
BASE_DIR = Path("/kmua/data/cards")
TOKUTEN_DIR = BASE_DIR / "tokuten"

# 特典卡专属样式 (金色主题)
TOKUTEN_STYLE = {
    "bg_gradient_start": (230, 180, 30),
    "bg_gradient_end": (200, 150, 10),
    "border": (180, 130, 10),
    "glow": (255, 220, 60),
    "label": "特典",
    "label_color": (255, 255, 255),
}


def _load_font(size):
    """加载字体"""
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
    """绘制圆角矩形"""
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)


def create_gradient_background(width, height, color_start, color_end):
    """创建垂直渐变背景"""
    base = Image.new("RGB", (width, height), color_start)
    top = Image.new("RGB", (width, height), color_end)
    mask = Image.new("L", (width, height))
    mask_data = []
    for y in range(height):
        alpha = int(255 * (y / height))
        mask_data.extend([alpha] * width)
    mask.putdata(mask_data)
    base.paste(top, (0, 0), mask)
    return base


def generate_tokuten_card(source_image_path: Path, season_id: int) -> Image.Image:
    """
    生成特典卡面

    Args:
        source_image_path: 参考图片路径
        season_id: 赛季ID

    Returns:
        PIL Image 对象
    """
    # 创建画布
    img = Image.new("RGBA", (TOKUTEN_W, TOKUTEN_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 加载源图片并调整大小
    try:
        source = Image.open(source_image_path)
        # 保持比例缩放到适合卡片内容区域
        content_w = TOKUTEN_W - BORDER * 4
        content_h = TOKUTEN_H - BORDER * 4 - 60  # 预留底部标签空间

        # 计算缩放比例
        source_ratio = source.width / source.height
        target_ratio = content_w / content_h

        if source_ratio > target_ratio:
            # 图片更宽，以宽度为准
            new_w = content_w
            new_h = int(content_w / source_ratio)
        else:
            # 图片更高，以高度为准
            new_h = content_h
            new_w = int(content_h * source_ratio)

        source_resized = source.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception as e:
        print(f"Warning: 无法加载源图片 {source_image_path}: {e}")
        # 创建占位图
        source_resized = Image.new("RGB", (content_w, content_h), (100, 100, 100))
        new_w, new_h = content_w, content_h

    # 绘制渐变背景边框
    gradient_bg = create_gradient_background(
        TOKUTEN_W, TOKUTEN_H,
        TOKUTEN_STYLE["bg_gradient_start"],
        TOKUTEN_STYLE["bg_gradient_end"]
    )
    img.paste(gradient_bg, (0, 0))

    # 绘制发光边框效果
    for i in range(4):
        glow_color = (*TOKUTEN_STYLE["glow"], 100 - i * 20)
        _draw_rounded_rect(
            draw,
            [BORDER - 6 + i, BORDER - 6 + i, TOKUTEN_W - BORDER + 5 - i, TOKUTEN_H - BORDER + 5 - i],
            20, fill=None, outline=glow_color, width=3
        )

    # 绘制主边框
    _draw_rounded_rect(
        draw,
        [BORDER, BORDER, TOKUTEN_W - BORDER, TOKUTEN_H - BORDER],
        18, fill=None, outline=TOKUTEN_STYLE["border"], width=5
    )

    # 粘贴内容图片 (居中)
    x_offset = (TOKUTEN_W - new_w) // 2
    y_offset = (TOKUTEN_H - new_h - 60) // 2 + BORDER

    # 创建白色背景区域
    white_bg = Image.new("RGB", (new_w + 8, new_h + 8), (255, 255, 255))
    img.paste(white_bg, (x_offset - 4, y_offset - 4))
    img.paste(source_resized, (x_offset, y_offset))

    # 绘制底部标签区域
    label_y = TOKUTEN_H - 70
    label_height = 50
    label_bg = Image.new("RGBA", (TOKUTEN_W - BORDER * 2, label_height), (*TOKUTEN_STYLE["border"], 220))
    img.paste(label_bg, (BORDER, label_y), label_bg)

    # 绘制"特典"标签
    font_large = _load_font(36)
    font_small = _load_font(20)

    label_text = f"✦ {TOKUTEN_STYLE['label']} ✦"
    bbox = draw.textbbox((0, 0), label_text, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((TOKUTEN_W - tw) / 2, label_y + 8),
        label_text,
        fill=TOKUTEN_STYLE["label_color"],
        font=font_large,
    )

    # 绘制赛季信息
    season_text = f"Season {season_id} 完成奖励"
    bbox2 = draw.textbbox((0, 0), season_text, font=font_small)
    sw = bbox2[2] - bbox2[0]
    draw.text(
        ((TOKUTEN_W - sw) / 2, BORDER + 8),
        season_text,
        fill=(255, 255, 255, 230),
        font=font_small,
    )

    # 四角装饰星星
    star_font = _load_font(24)
    for pos in [
        (BORDER + 10, BORDER + 10),
        (TOKUTEN_W - BORDER - 40, BORDER + 10),
        (BORDER + 10, TOKUTEN_H - BORDER - 35),
        (TOKUTEN_W - BORDER - 40, TOKUTEN_H - BORDER - 35)
    ]:
        draw.text(pos, "✦", fill=(255, 255, 220), font=star_font)

    return img


def generate_tokuten_back() -> Image.Image:
    """生成特典卡背 (横版)"""
    img = Image.new("RGBA", (TOKUTEN_W, TOKUTEN_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 深色背景
    _draw_rounded_rect(draw, [0, 0, TOKUTEN_W - 1, TOKUTEN_H - 1], 20, fill=(40, 40, 60))
    _draw_rounded_rect(
        draw,
        [BORDER, BORDER, TOKUTEN_W - BORDER, TOKUTEN_H - BORDER],
        18, fill=None, outline=(80, 80, 120), width=4
    )

    # 中央纹理
    font = _load_font(48)
    draw.text((TOKUTEN_W // 2 - 24, TOKUTEN_H // 2 - 30), "🃏", font=font)

    font_s = _load_font(20)
    txt = "TOKUTEN"
    bb = draw.textbbox((0, 0), txt, font=font_s)
    draw.text(
        ((TOKUTEN_W - bb[2] + bb[0]) / 2, TOKUTEN_H // 2 + 30),
        txt,
        fill=(120, 120, 160),
        font=font_s
    )

    return img


def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成特典卡")
    parser.add_argument("--season", type=int, default=1, help="赛季ID")
    parser.add_argument(
        "--source",
        type=Path,
        default=BASE_DIR / "photo_2026-09-02_14-40-22.jpg",
        help="源图片路径"
    )
    args = parser.parse_args()

    # 创建输出目录
    season_tokuten_dir = TOKUTEN_DIR / f"season_{args.season}"
    season_tokuten_dir.mkdir(parents=True, exist_ok=True)

    # 生成特典卡背
    back = generate_tokuten_back()
    back_rgb = Image.new("RGB", (TOKUTEN_W, TOKUTEN_H), (30, 30, 30))
    back_rgb.paste(back, mask=back)
    back_path = season_tokuten_dir / "tokuten_back.png"
    back_rgb.save(back_path, "PNG")
    print(f"✓ 生成特典卡背: {back_path}")

    # 生成特典卡面
    tokuten = generate_tokuten_card(args.source, args.season)
    tokuten_rgb = Image.new("RGB", (TOKUTEN_W, TOKUTEN_H), (30, 30, 30))
    tokuten_rgb.paste(tokuten, mask=tokuten)
    tokuten_path = season_tokuten_dir / "tokuten.png"
    tokuten_rgb.save(tokuten_path, "PNG")
    print(f"✓ 生成特典卡面: {tokuten_path}")

    print(f"\n✦ 特典卡生成完成! Season {args.season}")
    print(f"   尺寸: {TOKUTEN_W}×{TOKUTEN_H} (横版)")
    print(f"   输出目录: {season_tokuten_dir}")


if __name__ == "__main__":
    main()
