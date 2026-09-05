"""更新数据库中的卡牌名和稀有度"""
import asyncio
import sys
sys.path.insert(0, "/kmua")

from kmua.database.db import engine
from kmua.database.models import CardDefinition
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# (card_number, rarity, name)
CARDS = [
    (1, "common", "羊角酒馆的甜酿师"),
    (2, "common", "月蓝狼契"),
    (3, "common", "血月霜羽术士"),
    (4, "rare", "月灯蜜誓"),
    (5, "rare", "赤喉龙灾下的远征"),
    (6, "common", "墓园蓝焰骑士"),
    (7, "common", "月下触魂妖"),
    (8, "epic", "千眼玻璃囚徒"),
    (9, "common", "灵灯炼金师"),
    (10, "common", "晴穹弦歌者"),
    (11, "common", "龙骸余烬侍女"),
    (12, "common", "赤潮回旋女巫"),
    (13, "common", "金瞳酒窖游荡者"),
    (14, "common", "寒星秘仪导师"),
    (15, "rare", "绯樱狐巫"),
    (16, "rare", "星渊蓝焰术士"),
    (17, "rare", "霓虹酒窖魅影"),
    (18, "rare", "云上百花猎手"),
    (19, "rare", "锁链圣痕天使"),
    (20, "rare", "静默白袍牧师"),
    (21, "rare", "倒悬囚笼的献祭者"),
    (22, "rare", "冰晶秘典师"),
    (23, "rare", "深海宝箱怪"),
    (24, "epic", "熔脉斩首者"),
    (25, "epic", "赤晶锁座女王"),
    (26, "epic", "焚心赤刃魔女"),
    (27, "common", "霜刃酒歌剑士"),
    (28, "epic", "三相幻胶"),
    (29, "epic", "翡翠星矢德鲁伊"),
    (30, "legendary", "暗炉三人密会"),
    (31, "legendary", "血月亡军统领"),
    (32, "legendary", "倒悬霜翼"),
]

CARD_MAP = {num: (rarity, name) for num, rarity, name in CARDS}


async def main():
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        stmt = select(CardDefinition).where(CardDefinition.season_id == 1).order_by(CardDefinition.card_number)
        result = await session.execute(stmt)
        cards = result.scalars().all()

        for card in cards:
            if card.card_number in CARD_MAP:
                new_rarity, new_name = CARD_MAP[card.card_number]
                old_name, old_rarity = card.name, card.rarity
                card.name = new_name
                card.rarity = new_rarity
                changed = []
                if old_name != new_name:
                    changed.append(f"name: {old_name} -> {new_name}")
                if old_rarity != new_rarity:
                    changed.append(f"rarity: {old_rarity} -> {new_rarity}")
                if changed:
                    print(f"  #{card.card_number:02d} {', '.join(changed)}")
                else:
                    print(f"  #{card.card_number:02d} (unchanged)")

        await session.commit()
        print(f"Updated {len(cards)} cards")


if __name__ == "__main__":
    asyncio.run(main())
