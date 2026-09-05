#!/usr/bin/env python3
"""
生成卡册专用的纯净翻转动画（MP4 格式，流式编码）
基于 card_XX_full.png（无装饰正面）和 card_XX_back.png（卡背）
完全复刻 gacha.py 单抽动画的生成方式
"""
import math
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter


def generate_flip_animation_mp4(
    card_number: int,
    season_dir: Path,
    direction: str = "back_to_front"
):
    """生成单个卡片的翻转动画（MP4 格式，ffmpeg 流式编码）

    Args:
        card_number: 卡片编号
        season_dir: 季度目录路径
        direction: "back_to_front" 或 "front_to_back"
    """
    # 加载图片
    front_path = season_dir / f"card_{card_number:02d}_full.png"
    back_path = season_dir / f"card_{card_number:02d}_back.png"

    if not front_path.exists() or not back_path.exists():
        print(f"⚠️ 跳过 card_{card_number:02d}: 缺少 full.png 或 back.png")
        return

    # 转换为 RGB（复刻单抽动画）
    front_img = Image.open(front_path).convert("RGB")
    back_img = Image.open(back_path).convert("RGB")

    card_w, card_h = front_img.size

    # 根据方向设置起始和结束图片
    if direction == "back_to_front":
        start_img = back_img
        end_img = front_img
        output_suffix = "flip_clean"
    else:
        start_img = front_img
        end_img = back_img
        output_suffix = "flip_reverse_clean"

    output_path = season_dir / f"card_{card_number:02d}_{output_suffix}.mp4"

    # ffmpeg 参数（复刻单抽动画）
    fps = 15
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{card_w}x{card_h}", "-pix_fmt", "rgb24", "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "slow", "-tune", "stillimage",
            "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            tmp_path,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pipe = proc.stdin

        # 1. 开场静止: 5帧 (333ms) - 缩短等待时间
        static_bytes = start_img.tobytes()
        for _ in range(5):
            pipe.write(static_bytes)

        # 2. 翻转动画: 18帧 (1.2s)，余弦缓动
        flip_count = 18

        for i in range(flip_count):
            t = i / (flip_count - 1)
            width_ratio = abs(math.cos(t * math.pi))
            width_ratio = max(0.08, width_ratio)

            # 优化逻辑：
            # - 前半段宽帧（i < flip_count//2 且 width_ratio >= 0.60）：显示起始图
            # - 中间窄帧（width_ratio < 0.60）：显示目标图（避免复杂图压缩失真）
            # - 后半段（i >= flip_count//2）：始终显示目标图（完成翻转）
            if i >= flip_count // 2:
                # 后半段始终显示目标图（翻转已完成）
                src = end_img
            elif width_ratio < 0.60:
                # 前半段的窄帧提前显示目标图
                src = end_img
            else:
                # 前半段的宽帧显示起始图
                src = start_img

            squeeze_w = max(4, int(card_w * width_ratio))
            # 使用 LANCZOS 高质量重采样
            squeezed = src.resize((squeeze_w, card_h), Image.Resampling.LANCZOS)

            # 创建黑色背景帧
            frame = Image.new("RGB", (card_w, card_h), (0, 0, 0))
            x_offset = (card_w - squeeze_w) // 2
            frame.paste(squeezed, (x_offset, 0))
            pipe.write(frame.tobytes())

        # 3. 定格结束帧: 7帧 (467ms) - 缩短定格时间
        static_bytes = end_img.tobytes()
        for _ in range(7):
            pipe.write(static_bytes)

        pipe.close()
        proc.wait()

        if proc.returncode != 0:
            err = proc.stderr.read().decode(errors="replace")
            print(f"❌ ffmpeg error for card_{card_number:02d}: {err[:300]}")
            return

        # 移动到最终位置
        import shutil
        shutil.move(tmp_path, output_path)
        print(f"✅ {output_path.name}")

    except Exception as e:
        print(f"❌ card_{card_number:02d} 生成失败: {e}")
        try:
            import os
            os.unlink(tmp_path)
        except OSError:
            pass


def main():
    season_dir = Path("/kmua/data/cards/season_1")

    if not season_dir.exists():
        print(f"❌ 目录不存在: {season_dir}")
        return

    # 查找所有卡片
    card_files = sorted(season_dir.glob("card_*_full.png"))
    print(f"找到 {len(card_files)} 张卡片\n")

    print("生成背面→正面动画（card_XX_flip_clean.mp4）:")
    for card_file in card_files:
        card_number = int(card_file.stem.split("_")[1])
        generate_flip_animation_mp4(card_number, season_dir, "back_to_front")

    print("\n生成正面→背面动画（card_XX_flip_reverse_clean.mp4）:")
    for card_file in card_files:
        card_number = int(card_file.stem.split("_")[1])
        generate_flip_animation_mp4(card_number, season_dir, "front_to_back")

    print("\n✨ 所有 MP4 翻转动画生成完成！")


if __name__ == "__main__":
    main()
