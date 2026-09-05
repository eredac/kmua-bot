"""
创建新赛季（在Docker容器内运行）
用法: python -m scripts.init_season --name "第一期·测试" --days 30
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone


async def main():
    parser = argparse.ArgumentParser(description="创建卡牌赛季")
    parser.add_argument("--name", required=True, help="赛季名称")
    parser.add_argument("--days", type=int, default=30, help="持续天数")
    args = parser.parse_args()

    from kmua.database.db import engine, AsyncSessionFactory
    from kmua.database.gacha import create_season_with_cards

    now = datetime.now(timezone.utc)
    ends = now + timedelta(days=args.days)

    season = await create_season_with_cards(
        name=args.name,
        starts_at=now,
        ends_at=ends,
    )
    print(f"赛季创建成功！ID={season.id}, 名称={season.name}")
    print(f"  开始: {now.isoformat()}")
    print(f"  结束: {ends.isoformat()}")
    print(f"  卡牌数: {season.total_cards}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
