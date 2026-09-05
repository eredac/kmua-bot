#!/usr/bin/env python3
"""
预生成所有单抽动画（MP4）
用于优化：避免实时调用 ffmpeg，直接读取预生成的缓存
"""
import subprocess
import tempfile
import time
from pathlib import Path
import math
import io

from PIL import Image


def generate_single_draw_mp4(card_number: int, season_id: int, output_path: Path) -> bool:
    """
    生成单抽翻牌 MP4 动画（单卡居中，流式编码）

    Args:
        card_number: 卡片编号 (1-32)
        season_id: 赛季 ID
        output_path: 输出文件路径

    Returns:
        是否成功生成
    """
    t0 = time.time()

    base = f"/kmua/data/cards/season_{season_id}"
    personal_back = f"{base}/card_{card_number:02d}_back.png"
    generic_back = "/kmua/data/cards/card_back.png"

    import os
    back_path = personal_back if os.path.exists(personal_back) else generic_back

    try:
        back_img = Image.open(back_path).convert("RGB")
        face_img = Image.open(f"{base}/card_{card_number:02d}.png").convert("RGB")
    except Exception as e:
        print(f"[ERROR] Failed to load images for card {card_number}: {e}")
        return False

    card_w, card_h = 384, 538
    pad = 20
    canvas_w = card_w + pad * 2
    canvas_h = card_h + pad * 2
    bg_color = (25, 25, 30)

    back_cell = back_img.resize((card_w, card_h), Image.Resampling.BILINEAR)
    face_cell = face_img.resize((card_w, card_h), Image.Resampling.BILINEAR)

    fps = 15
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    frame_count = 0
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{canvas_w}x{canvas_h}", "-pix_fmt", "rgb24", "-r", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            tmp_path,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pipe = proc.stdin

        canvas = Image.new("RGB", (canvas_w, canvas_h), bg_color)
        canvas.paste(back_cell, (pad, pad))

        # 开场卡背静止: 10帧 (667ms)
        static_bytes = canvas.tobytes()
        for _ in range(10):
            pipe.write(static_bytes)
            frame_count += 1

        # 翻转动画: 20帧 (1.33s)
        flip_count = 20
        for i in range(flip_count):
            t = i / (flip_count - 1)
            width_ratio = abs(math.cos(t * math.pi))
            width_ratio = max(0.08, width_ratio)
            src = back_cell if i < flip_count // 2 else face_cell
            squeeze_w = max(4, int(card_w * width_ratio))
            squeezed = src.resize((squeeze_w, card_h), Image.Resampling.NEAREST)

            canvas_frame = Image.new("RGB", (canvas_w, canvas_h), bg_color)
            x_offset = pad + (card_w - squeeze_w) // 2
            canvas_frame.paste(squeezed, (x_offset, pad))
            pipe.write(canvas_frame.tobytes())
            frame_count += 1

        # 卡面定格: 20帧 (1.33s)
        canvas.paste(face_cell, (pad, pad))
        static_bytes = canvas.tobytes()
        for _ in range(20):
            pipe.write(static_bytes)
            frame_count += 1

        pipe.close()
        proc.wait()

        if proc.returncode != 0:
            err = proc.stderr.read().decode(errors="replace")
            print(f"[ERROR] ffmpeg failed for card {card_number}: {err[:300]}")
            return False

        # 移动到目标位置
        import shutil
        shutil.move(tmp_path, str(output_path))

        file_size = output_path.stat().st_size // 1024
        print(f"[OK] Card {card_number:02d}: {time.time()-t0:.2f}s, {frame_count} frames, {file_size}KB")
        return True

    except Exception as e:
        print(f"[ERROR] Failed to generate card {card_number}: {e}")
        try:
            import os
            os.unlink(tmp_path)
        except:
            pass
        return False


def main():
    """预生成所有单抽动画"""
    season_id = 1  # 当前赛季
    base_path = Path(f"/kmua/data/cards/season_{season_id}")

    if not base_path.exists():
        print(f"[ERROR] Season {season_id} directory not found: {base_path}")
        return

    print(f"🎴 Pregenerating single-draw animations for season {season_id}...")
    print("=" * 60)

    total_start = time.time()
    success_count = 0
    fail_count = 0

    for card_num in range(1, 33):  # 32张卡
        output_path = base_path / f"card_{card_num:02d}_single_draw.mp4"

        # 跳过已存在的文件
        if output_path.exists():
            print(f"[SKIP] Card {card_num:02d}: already exists")
            success_count += 1
            continue

        if generate_single_draw_mp4(card_num, season_id, output_path):
            success_count += 1
        else:
            fail_count += 1

    total_time = time.time() - total_start
    print("=" * 60)
    print(f"✅ Complete: {success_count}/32 success, {fail_count}/32 failed")
    print(f"⏱️  Total time: {total_time:.2f}s (avg {total_time/32:.2f}s per card)")


if __name__ == "__main__":
    main()
