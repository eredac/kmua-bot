"""更新赛季结束日期: 2026-09-30"""
import asyncio
import sys
from datetime import datetime, timezone
sys.path.insert(0, "/kmua")

from kmua.database.db import engine
from kmua.database.models import CardSeason
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select


async def main():
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(select(CardSeason).where(CardSeason.id == 1))
        season = result.scalar_one()
        print("=== 更新前 ===")
        print(f"  name: {season.name}")
        print(f"  starts_at: {season.starts_at}")
        print(f"  ends_at: {season.ends_at}")

        # 设置结束日期为 2026-09-30 23:59:59 UTC
        new_end_date = datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc)
        season.ends_at = new_end_date
        await session.commit()

        print("\n=== 更新后 ===")
        print(f"  name: {season.name}")
        print(f"  starts_at: {season.starts_at} (不变)")
        print(f"  ends_at: {new_end_date}")


if __name__ == "__main__":
    asyncio.run(main())
