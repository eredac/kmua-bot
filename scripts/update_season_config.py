"""更新赛季配置: daily_free_draws=10, redeem_reward=150, trade_fee=5"""
import asyncio
import sys
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
        print(f"  daily_free_draws: {season.daily_free_draws}")
        print(f"  redeem_reward: {season.redeem_reward}")
        print(f"  trade_fee: {season.trade_fee}")
        print(f"  draw_price: {season.draw_price}")
        print(f"  pity_dedup: {season.pity_dedup}")
        print(f"  pity_legendary: {season.pity_legendary}")

        season.daily_free_draws = 10
        season.redeem_reward = 150
        season.trade_fee = 5
        await session.commit()

        print("\n=== 更新后 ===")
        print(f"  daily_free_draws: 10")
        print(f"  redeem_reward: 150")
        print(f"  trade_fee: 5")
        print(f"  draw_price: {season.draw_price} (不变)")
        print(f"  pity_dedup: {season.pity_dedup} (不变)")
        print(f"  pity_legendary: {season.pity_legendary} (不变)")


if __name__ == "__main__":
    asyncio.run(main())
