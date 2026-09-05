#!/usr/bin/env python3
"""反转卡牌翻转动画的帧序列，生成正面→背面的动画"""
import os
from pathlib import Path
from PIL import Image

def reverse_gif(input_path: str, output_path: str):
    """反转 GIF 动画的帧序列，并重建正确的时间数组"""
    with Image.open(input_path) as img:
        frames = []

        # 只提取帧，不提取 duration（因为 duration 会和帧绑定）
        try:
            while True:
                # 创建新的副本，清除原有的元数据
                frame = img.copy().convert("RGB")
                frames.append(frame)
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        # 反转帧序列
        frames.reverse()

        # 重建标准时间数组结构: [720ms 短停, 80ms×18 翻转, 30080ms 长定格]
        # 这个数组是为反转后的帧设计的，不受原数组影响
        correct_durations = [720] + [80] * 18 + [30080]

        # 保存为新的 GIF
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=correct_durations,
            loop=0,
            optimize=False
        )

def main():
    cards_dir = Path("/kmua/data/cards/season_1")

    # 查找所有 flip.gif 文件
    flip_files = sorted(cards_dir.glob("card_*_flip.gif"))

    print(f"找到 {len(flip_files)} 个翻转动画文件")

    for flip_file in flip_files:
        # 生成反向文件名
        reverse_file = flip_file.parent / flip_file.name.replace("_flip.gif", "_flip_reverse.gif")

        if reverse_file.exists():
            print(f"跳过 {flip_file.name}（反向文件已存在）")
            continue

        print(f"处理 {flip_file.name} → {reverse_file.name}")
        reverse_gif(str(flip_file), str(reverse_file))

    print("✅ 所有动画反转完成！")

if __name__ == "__main__":
    main()
