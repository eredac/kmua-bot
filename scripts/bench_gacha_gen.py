"""压测卡牌图片生成性能"""
import asyncio
import sys
import time
import random
import concurrent.futures

sys.path.insert(0, "/kmua")

from kmua.plugins.gacha import (
    _generate_multi_draw_png,
    _generate_multi_draw_mp4,
    _generate_card_grid,
)


def bench_single_png():
    """单次十连 PNG 生成"""
    cards = random.sample(range(1, 33), 10)
    t0 = time.time()
    data = _generate_multi_draw_png(cards, 1)
    elapsed = time.time() - t0
    return elapsed, len(data)


def bench_single_mp4():
    """单次十连 MP4 生成"""
    cards = random.sample(range(1, 33), 10)
    t0 = time.time()
    data = _generate_multi_draw_mp4(cards, 1)
    elapsed = time.time() - t0
    return elapsed, len(data)


def bench_card_grid():
    """单次 3x3 网格生成"""
    infos = []
    for i in range(1, 10):
        infos.append({
            "card_number": i,
            "owned": random.choice([True, False]),
            "count": random.randint(1, 5),
            "name": f"测试卡{i}",
            "rarity": "common",
        })
    t0 = time.time()
    data = _generate_card_grid(infos, 1)
    elapsed = time.time() - t0
    return elapsed, len(data)


def run_concurrent(fn, n, label):
    """并发执行 n 次 fn"""
    print(f"\n{'='*50}")
    print(f"  {label}: 并发 {n} 次")
    print(f"{'='*50}")

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(fn) for _ in range(n)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    wall_time = time.time() - t0

    times = [r[0] for r in results]
    sizes = [r[1] for r in results]
    print(f"  墙钟时间: {wall_time:.2f}s")
    print(f"  单次耗时: min={min(times):.2f}s  max={max(times):.2f}s  avg={sum(times)/len(times):.2f}s")
    print(f"  文件大小: avg={sum(sizes)//len(sizes)//1024}KB")
    print(f"  吞吐量: {n/wall_time:.1f} req/s")
    return wall_time


def main():
    print("=" * 60)
    print("  卡牌图片生成压测")
    print("=" * 60)

    # 预热
    print("\n[预热] ...")
    bench_single_png()
    bench_card_grid()

    # 1. 单次基准
    print("\n--- 单次基准 ---")
    t, s = bench_single_png()
    print(f"  十连 PNG: {t:.3f}s, {s//1024}KB")

    t, s = bench_card_grid()
    print(f"  9宫格 PNG: {t:.3f}s, {s//1024}KB")

    t, s = bench_single_mp4()
    print(f"  十连 MP4: {t:.3f}s, {s//1024}KB")

    # 2. 并发压测 PNG
    for n in [2, 5, 10]:
        run_concurrent(bench_single_png, n, "十连 PNG")

    # 3. 并发压测 9宫格
    for n in [2, 5, 10]:
        run_concurrent(bench_card_grid, n, "9宫格 PNG")

    # 4. 并发压测 MP4 (重负载)
    for n in [2, 3, 5]:
        run_concurrent(bench_single_mp4, n, "十连 MP4")

    # 5. 混合负载：同时生成 PNG + MP4（模拟十连实际场景）
    print(f"\n{'='*50}")
    print(f"  混合负载: 5x(PNG+MP4) 同时")
    print(f"{'='*50}")
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futs = []
        for _ in range(5):
            futs.append(pool.submit(bench_single_png))
            futs.append(pool.submit(bench_single_mp4))
        results = [f.result() for f in concurrent.futures.as_completed(futs)]
    wall = time.time() - t0
    png_times = [r[0] for r in results[:5]]
    mp4_times = [r[0] for r in results[5:]]
    print(f"  总墙钟: {wall:.2f}s")
    print(f"  吞吐: {10/wall:.1f} 任务/s")


if __name__ == "__main__":
    main()
