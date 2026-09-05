#!/usr/bin/env python3
"""为未拥有的卡片生成灰度翻转动画（MP4 格式）"""

import asyncio
import sys
import subprocess
import tempfile
from pathlib import Path
from PIL import Image

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from kmua.database import gacha as database


def convert_mp4_to_grayscale(input_path: Path, output_path: Path):
    """将 MP4 动画转换为灰度版本（使用 ffmpeg 硬件加速）"""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", "format=gray",  # 灰度滤镜
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")
        print(f"❌ ffmpeg error: {err[:300]}")
        return False
    return True


async def main():
    if len(sys.argv) < 2:
        print("用法: python generate_grayscale_flips.py <season_id>")
        sys.exit(1)

    season_id = int(sys.argv[1])

    # 获取赛季信息
    season = await database.get_season_by_id(season_id)
    if not season:
        print(f"❌ 赛季 {season_id} 不存在")
        sys.exit(1)

    # 获取所有卡片
    cards = await database.get_season_cards(season_id)
    season_dir = Path(f"/kmua/data/cards/season_{season_id}")

    print(f"正在为赛季 {season_id}「{season.name}」生成 {len(cards)} 张灰度翻转动画...")

    for card in cards:
        card_num = card.card_number

        # 处理背面→正面翻转动画
        flip_clean = season_dir / f"card_{card_num:02d}_flip_clean.mp4"
        flip_gray = season_dir / f"card_{card_num:02d}_flip_clean_gray.mp4"

        if flip_clean.exists():
            if convert_mp4_to_grayscale(flip_clean, flip_gray):
                print(f"✅ card_{card_num:02d}_flip_clean_gray.mp4 - {card.name}")
            else:
                print(f"❌ card_{card_num:02d}_flip_clean_gray.mp4 转换失败")
        else:
            print(f"⚠️  card_{card_num:02d}_flip_clean.mp4 不存在，跳过")

        # 处理正面→背面翻转动画
        flip_reverse = season_dir / f"card_{card_num:02d}_flip_reverse_clean.mp4"
        flip_reverse_gray = season_dir / f"card_{card_num:02d}_flip_reverse_clean_gray.mp4"

        if flip_reverse.exists():
            if convert_mp4_to_grayscale(flip_reverse, flip_reverse_gray):
                print(f"✅ card_{card_num:02d}_flip_reverse_clean_gray.mp4 - {card.name}")
            else:
                print(f"❌ card_{card_num:02d}_flip_reverse_clean_gray.mp4 转换失败")
        else:
            print(f"⚠️  card_{card_num:02d}_flip_reverse_clean.mp4 不存在，跳过")

    print("\n✨ 所有灰度 MP4 动画生成完成！")


if __name__ == "__main__":
    asyncio.run(main())
