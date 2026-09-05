#!/usr/bin/env python3
"""
生成正面→背面的翻转动画
基于原始的 flip.gif（背面→正面），生成相反方向的动画
"""
from pathlib import Path
from PIL import Image


def generate_front_to_back_flip(card_number: int, season_dir: Path):
    """生成正面→背面的翻转动画"""
    card_full = season_dir / f"card_{card_number:02d}_full.png"
    card_back = season_dir / f"card_{card_number:02d}_back.png"
    output_path = season_dir / f"card_{card_number:02d}_flip_reverse.gif"

    if not card_full.exists() or not card_back.exists():
        print(f"跳过 card_{card_number:02d}: 缺少 full.png 或 back.png")
        return

    # 加载图片并获取实际尺寸
    front_img = Image.open(card_full).convert("RGBA")
    back_img = Image.open(card_back).convert("RGBA")

    # 使用实际图片的尺寸，而不是硬编码
    CARD_W, CARD_H = front_img.size

    frames = []
    total_frames = 20
    flip_frames = 20  # 所有帧都作为 flip 动画生成，不再单独设置 pause

    # 生成 20 帧的翻转动画（正面 → 背面）
    # 使用与原始脚本完全对称的逻辑
    mid = flip_frames // 2

    for i in range(flip_frames):
        # 反转原始脚本的 progress 计算
        # 原始: progress = i / (flip_frames - 1)  # 从 0 到 1
        # 反转: progress = 1 - (i / (flip_frames - 1))  # 从 1 到 0
        progress = 1.0 - (i / (flip_frames - 1)) if flip_frames > 1 else 0.0
        new_w = max(4, int(CARD_W * max(0.05, progress)))

        if i < mid:
            # 前半段：正面缩小
            src = front_img
        else:
            # 后半段：背面放大
            src = back_img

        resized = src.resize((new_w, CARD_H), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        x_offset = (CARD_W - new_w) // 2
        frame.paste(resized, (x_offset, 0))
        frames.append(frame)

    # DEBUG: 打印帧数信息
    print(f"  DEBUG - total_frames={total_frames}, flip_frames={flip_frames}")
    print(f"  DEBUG - frames array length: {len(frames)}")

    # 合成背景并转换为 RGB（与原始脚本一致）
    gif_frames = []
    for f in frames:
        bg = Image.new("RGBA", (CARD_W, CARD_H), (30, 30, 30, 255))
        bg.paste(f, mask=f)
        gif_frames.append(bg.convert("RGB"))

    print(f"  DEBUG - gif_frames length: {len(gif_frames)}")

    # 构建 duration 数组 - 匹配原始 flip.gif 的结构：1个pause帧 + 18个flip帧 + 1个pause帧
    # 原始格式：[720] + [80]*18 + [30080] = 20个时间值对应20帧
    duration_array = [720] + [80] * 18 + [30080]
    print(f"  DEBUG - duration array length: {len(duration_array)}")
    print(f"  DEBUG - duration array: {duration_array}")

    # 保存 GIF - 禁用优化，保留所有帧
    gif_frames[0].save(
        output_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=duration_array,
        loop=0,
        optimize=False,  # 禁用优化，防止帧合并
    )

    print(f"✅ 生成 {output_path.name}")


def main():
    season_dir = Path("/kmua/data/cards/season_1")

    if not season_dir.exists():
        print(f"❌ 目录不存在: {season_dir}")
        return

    # 查找所有卡片
    card_files = sorted(season_dir.glob("card_*_full.png"))
    print(f"找到 {len(card_files)} 张卡片")

    for card_file in card_files:
        # 提取卡片编号
        card_number = int(card_file.stem.split("_")[1])
        generate_front_to_back_flip(card_number, season_dir)

    print("\n✨ 所有正面→背面动画生成完成！")


if __name__ == "__main__":
    main()
