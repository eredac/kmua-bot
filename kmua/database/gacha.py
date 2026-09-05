"""
集换卡牌系统数据库操作层
"""
import random
from datetime import datetime, timedelta, timezone
from typing import Sequence

import sqlalchemy
from sqlalchemy import case as sa_case, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import (
    CardAlbum,
    CardDefinition,
    CardDrawRecord,
    CardSeason,
    CardTradeRequest,
    UserCard,
    UserTokuten,
)

# 稀有度概率配置
RARITY_WEIGHTS = {
    "common": 55,
    "rare": 35,
    "epic": 9,
    "legendary": 1,
}

# 稀有度排序权重 (值越小越靠前)
_RARITY_ORDER = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}


def _rarity_sort_expr():
    """返回按稀有度排序的 SQL CASE 表达式 (legendary first)"""
    return sa_case(
        _RARITY_ORDER,
        value=CardDefinition.rarity,
        else_=99,
    )

RARITY_LABELS = {
    "common": "普通",
    "rare": "稀有",
    "epic": "史诗",
    "legendary": "传说",
}


# ==================== 赛季管理 ====================


@with_session
async def get_active_season(session: AsyncSession | None = None) -> CardSeason | None:
    assert session is not None
    now = datetime.now(timezone.utc)
    stmt = (
        sqlalchemy.select(CardSeason)
        .where(CardSeason.status == "active", CardSeason.starts_at <= now, CardSeason.ends_at > now)
        .order_by(CardSeason.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_session
async def get_current_or_latest_season(session: AsyncSession | None = None) -> CardSeason | None:
    """优先返回活跃赛季，否则返回最近的赛季（用于赛季结束后仍可浏览卡册）"""
    assert session is not None
    now = datetime.now(timezone.utc)
    # 先尝试活跃赛季
    stmt = (
        sqlalchemy.select(CardSeason)
        .where(CardSeason.status == "active", CardSeason.starts_at <= now, CardSeason.ends_at > now)
        .order_by(CardSeason.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    season = result.scalar_one_or_none()
    if season:
        return season
    # 无活跃赛季，取最近一期
    stmt = sqlalchemy.select(CardSeason).order_by(CardSeason.id.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_session
async def get_all_seasons(session: AsyncSession | None = None) -> Sequence[CardSeason]:
    assert session is not None
    stmt = sqlalchemy.select(CardSeason).order_by(CardSeason.id.desc())
    result = await session.execute(stmt)
    return result.scalars().all()
@with_session
async def get_season_by_id(
    season_id: int, session: AsyncSession | None = None
) -> CardSeason | None:
    assert session is not None
    return await session.get(CardSeason, season_id)


@with_session
async def get_season_cards(
    season_id: int, session: AsyncSession | None = None
) -> Sequence[CardDefinition]:
    assert session is not None
    stmt = (
        sqlalchemy.select(CardDefinition)
        .where(CardDefinition.season_id == season_id)
        .order_by(_rarity_sort_expr(), CardDefinition.card_number)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ==================== 抽卡逻辑 ====================


@with_session
async def get_today_free_draw_count(
    user_id: int, chat_id: int, season_id: int, today: str,
    session: AsyncSession | None = None,
) -> int:
    assert session is not None
    stmt = sqlalchemy.select(sa_func.count()).where(
        CardDrawRecord.user_id == user_id,
        CardDrawRecord.chat_id == chat_id,
        CardDrawRecord.season_id == season_id,
        CardDrawRecord.is_free == True,  # noqa: E712
        CardDrawRecord.draw_date == today,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


@with_session
async def get_pity_counters(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> tuple[int, int]:
    """返回 (连续未出传说次数, 去重保底计数)"""
    assert session is not None
    # JOIN CardDefinition 避免 N+1，LIMIT 取最近 max(dedup, legendary) 条足矣
    stmt = (
        sqlalchemy.select(CardDrawRecord, CardDefinition.rarity)
        .join(CardDefinition, CardDrawRecord.card_def_id == CardDefinition.id)
        .where(
            CardDrawRecord.user_id == user_id,
            CardDrawRecord.chat_id == chat_id,
            CardDrawRecord.season_id == season_id,
        )
        .order_by(CardDrawRecord.id.desc())
        .limit(100)
    )
    result = await session.execute(stmt)
    records = result.all()

    legendary_pity = 0
    dedup_pity = 0

    # 计算传说保底：连续未出传说
    for r, rarity in records:
        if rarity == "legendary":
            break
        legendary_pity += 1

    # 计算去重保底：从上次去重保底触发起的连续抽数
    for r, rarity in records:
        if r.pity_triggered == "dedup":
            break
        dedup_pity += 1

    return legendary_pity, dedup_pity


@with_tx
async def perform_draw(
    user_id: int, chat_id: int, season_id: int, is_free: bool, today: str,
    session: AsyncSession | None = None,
) -> tuple[CardDefinition, str | None]:
    """执行一次抽卡，返回 (抽到的卡定义, 触发的保底类型或None)"""
    assert session is not None

    # 获取卡池
    cards_stmt = sqlalchemy.select(CardDefinition).where(
        CardDefinition.season_id == season_id
    )
    cards_result = await session.execute(cards_stmt)
    all_cards = list(cards_result.scalars().all())

    # 获取用户已拥有的卡
    owned_stmt = sqlalchemy.select(UserCard.card_def_id.distinct()).where(
        UserCard.user_id == user_id,
        UserCard.chat_id == chat_id,
        UserCard.season_id == season_id,
    )
    owned_result = await session.execute(owned_stmt)
    owned_set = set(owned_result.scalars().all())

    # 计算保底
    legendary_pity, dedup_pity = await get_pity_counters(
        user_id, chat_id, season_id, session=session
    )

    pity_triggered: str | None = None
    drawn_card: CardDefinition | None = None

    # 获取赛季配置
    season = await session.get(CardSeason, season_id)
    assert season is not None

    # 去重保底优先（80抽）
    if dedup_pity >= season.pity_dedup - 1:
        not_owned = [c for c in all_cards if c.id not in owned_set]
        if not_owned:
            drawn_card = random.choice(not_owned)
            pity_triggered = "dedup"
        else:
            # 全卡已集齐，标记 dedup 重置计数器，走正常抽卡
            pity_triggered = "dedup"

    # 传说保底（50抽）
    if drawn_card is None and legendary_pity >= season.pity_legendary - 1:
        legendaries = [c for c in all_cards if c.rarity == "legendary"]
        if legendaries:
            drawn_card = random.choice(legendaries)
            pity_triggered = "legendary"

    # 正常抽卡
    if drawn_card is None:
        rarity_pool: dict[str, list[CardDefinition]] = {}
        for c in all_cards:
            rarity_pool.setdefault(c.rarity, []).append(c)

        rarities = list(RARITY_WEIGHTS.keys())
        weights = [RARITY_WEIGHTS[r] for r in rarities]
        chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

        pool = rarity_pool.get(chosen_rarity, all_cards)
        drawn_card = random.choice(pool)

    assert drawn_card is not None

    # 记录抽卡
    record = CardDrawRecord(
        user_id=user_id,
        chat_id=chat_id,
        season_id=season_id,
        card_def_id=drawn_card.id,
        is_free=is_free,
        pity_triggered=pity_triggered,
        draw_date=today,
    )
    session.add(record)

    # 添加到用户卡包
    user_card = UserCard(
        user_id=user_id,
        chat_id=chat_id,
        card_def_id=drawn_card.id,
        season_id=season_id,
    )
    session.add(user_card)

    # 记录图鉴
    album_stmt = sqlalchemy.select(CardAlbum).where(
        CardAlbum.user_id == user_id,
        CardAlbum.card_def_id == drawn_card.id,
    )
    album_result = await session.execute(album_stmt)
    if album_result.scalar_one_or_none() is None:
        session.add(CardAlbum(
            user_id=user_id,
            card_def_id=drawn_card.id,
            season_id=season_id,
        ))

    return drawn_card, pity_triggered
# ==================== 背包与持有查询 ====================


@with_session
async def get_user_cards(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> Sequence[tuple]:
    """返回用户在当期的卡牌持有情况: [(CardDefinition, count), ...]"""
    assert session is not None
    stmt = (
        sqlalchemy.select(
            CardDefinition,
            sa_func.count(UserCard.id).label("cnt"),
        )
        .join(CardDefinition, UserCard.card_def_id == CardDefinition.id)
        .where(
            UserCard.user_id == user_id,
            UserCard.chat_id == chat_id,
            UserCard.season_id == season_id,
        )
        .group_by(CardDefinition.id)
        .order_by(_rarity_sort_expr(), CardDefinition.card_number)
    )
    result = await session.execute(stmt)
    return result.all()


@with_session
async def get_user_unique_count(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> int:
    assert session is not None
    stmt = sqlalchemy.select(
        sa_func.count(UserCard.card_def_id.distinct())
    ).where(
        UserCard.user_id == user_id,
        UserCard.chat_id == chat_id,
        UserCard.season_id == season_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


@with_session
async def get_user_card_by_def(
    user_id: int, chat_id: int, season_id: int, card_def_id: int,
    session: AsyncSession | None = None,
) -> UserCard | None:
    """获取用户某张特定卡牌（取第一张）"""
    assert session is not None
    stmt = (
        sqlalchemy.select(UserCard)
        .where(
            UserCard.user_id == user_id,
            UserCard.chat_id == chat_id,
            UserCard.season_id == season_id,
            UserCard.card_def_id == card_def_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_session
async def get_card_def_for_user_card(
    user_card_id: int, session: AsyncSession | None = None
) -> CardDefinition | None:
    """通过 UserCard.id 获取对应的 CardDefinition"""
    assert session is not None
    uc = await session.get(UserCard, user_card_id)
    if not uc:
        return None
    return await session.get(CardDefinition, uc.card_def_id)


@with_session
async def get_card_def_by_id(
    card_def_id: int, session: AsyncSession | None = None
) -> CardDefinition | None:
    assert session is not None
    return await session.get(CardDefinition, card_def_id)


@with_session
async def get_user_duplicate_cards(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> Sequence[tuple]:
    """获取用户持有多于1张的卡牌 [(CardDefinition, count), ...]"""
    assert session is not None
    stmt = (
        sqlalchemy.select(
            CardDefinition,
            sa_func.count(UserCard.id).label("cnt"),
        )
        .join(CardDefinition, UserCard.card_def_id == CardDefinition.id)
        .where(
            UserCard.user_id == user_id,
            UserCard.chat_id == chat_id,
            UserCard.season_id == season_id,
        )
        .group_by(CardDefinition.id)
        .having(sa_func.count(UserCard.id) > 1)
        .order_by(CardDefinition.card_number)
    )
    result = await session.execute(stmt)
    return result.all()


# ==================== 交易操作 ====================


@with_tx
async def create_trade_request(
    chat_id: int, sender_id: int, receiver_id: int,
    sender_card_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> CardTradeRequest | None:
    """创建交易请求，若该卡已有 pending 交易则返回 None"""
    assert session is not None

    # 检查该卡是否已有未完成交易
    existing_stmt = sqlalchemy.select(sa_func.count()).where(
        CardTradeRequest.sender_card_id == sender_card_id,
        CardTradeRequest.status == "pending",
    )
    existing = await session.execute(existing_stmt)
    if existing.scalar_one() > 0:
        return None

    trade = CardTradeRequest(
        chat_id=chat_id,
        sender_id=sender_id,
        receiver_id=receiver_id,
        sender_card_id=sender_card_id,
        receiver_card_id=None,
        season_id=season_id,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    session.add(trade)
    await session.flush()
    return trade


@with_session
async def get_trade_request(
    trade_id: int, session: AsyncSession | None = None
) -> CardTradeRequest | None:
    assert session is not None
    return await session.get(CardTradeRequest, trade_id)


@with_tx
async def accept_trade(
    trade_id: int, receiver_card_id: int,
    session: AsyncSession | None = None,
) -> CardTradeRequest:
    """接受交易：交换卡牌所有权"""
    assert session is not None
    trade = await session.get(CardTradeRequest, trade_id)
    assert trade is not None

    sender_card = await session.get(UserCard, trade.sender_card_id)
    receiver_card = await session.get(UserCard, receiver_card_id)
    assert sender_card is not None and receiver_card is not None

    # 交换 card_def_id
    sender_card.card_def_id, receiver_card.card_def_id = (
        receiver_card.card_def_id,
        sender_card.card_def_id,
    )

    trade.receiver_card_id = receiver_card_id
    trade.status = "completed"
    return trade


@with_tx
async def set_trade_awaiting_sender(
    trade_id: int, receiver_card_id: int, session: AsyncSession | None = None
) -> CardTradeRequest | None:
    """B 选好卡后，保存并进入等待 A 确认状态"""
    assert session is not None
    trade = await session.get(CardTradeRequest, trade_id)
    if not trade:
        return None
    trade.receiver_card_id = receiver_card_id
    trade.status = "awaiting_sender"
    return trade


@with_tx
async def cancel_trade(
    trade_id: int, session: AsyncSession | None = None
) -> None:
    assert session is not None
    trade = await session.get(CardTradeRequest, trade_id)
    if trade:
        trade.status = "cancelled"


# ==================== 兑换操作 ====================


@with_tx
async def redeem_collection(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> bool:
    """兑换全套卡牌换积分，成功返回 True"""
    assert session is not None

    season = await session.get(CardSeason, season_id)
    assert season is not None

    # 检查是否集齐
    unique_count_stmt = sqlalchemy.select(
        sa_func.count(UserCard.card_def_id.distinct())
    ).where(
        UserCard.user_id == user_id,
        UserCard.chat_id == chat_id,
        UserCard.season_id == season_id,
    )
    result = await session.execute(unique_count_stmt)
    unique_count = result.scalar_one()

    if unique_count < season.total_cards:
        return False

    # 获取所有卡定义 ID
    card_defs_stmt = sqlalchemy.select(CardDefinition.id).where(
        CardDefinition.season_id == season_id
    )
    card_defs_result = await session.execute(card_defs_stmt)
    all_card_def_ids = card_defs_result.scalars().all()

    # 每种卡消耗一张
    for card_def_id in all_card_def_ids:
        card_stmt = (
            sqlalchemy.select(UserCard)
            .where(
                UserCard.user_id == user_id,
                UserCard.chat_id == chat_id,
                UserCard.season_id == season_id,
                UserCard.card_def_id == card_def_id,
            )
            .limit(1)
        )
        card_result = await session.execute(card_stmt)
        card = card_result.scalar_one_or_none()
        if card is None:
            return False
        await session.delete(card)

    # 积分奖励通过调用方处理（因为需要 points 模块）
    return True


# ==================== 图鉴查询 ====================


@with_session
async def get_user_album(
    user_id: int, season_id: int | None = None,
    session: AsyncSession | None = None,
) -> Sequence[tuple]:
    """获取用户图鉴 [(CardAlbum, CardDefinition, CardSeason), ...]"""
    assert session is not None
    stmt = (
        sqlalchemy.select(CardAlbum, CardDefinition, CardSeason)
        .join(CardDefinition, CardAlbum.card_def_id == CardDefinition.id)
        .join(CardSeason, CardAlbum.season_id == CardSeason.id)
        .where(CardAlbum.user_id == user_id)
    )
    if season_id is not None:
        stmt = stmt.where(CardAlbum.season_id == season_id)
    stmt = stmt.order_by(CardSeason.id.desc(), _rarity_sort_expr(), CardDefinition.card_number)
    result = await session.execute(stmt)
    return result.all()


@with_session
async def get_user_album_count(
    user_id: int, session: AsyncSession | None = None
) -> int:
    assert session is not None
    stmt = sqlalchemy.select(sa_func.count()).where(CardAlbum.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one()


# ==================== 赛季初始化 ====================


@with_tx
async def create_season_with_cards(
    name: str,
    starts_at: datetime,
    ends_at: datetime,
    card_names: list[tuple[int, str, str]] | None = None,
    session: AsyncSession | None = None,
) -> CardSeason:
    """创建赛季并生成卡牌定义。card_names: [(number, rarity, name), ...]"""
    assert session is not None

    season = CardSeason(
        name=name,
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
    )
    session.add(season)
    await session.flush()

    if card_names is None:
        # 默认32张占位卡
        card_names = _generate_default_cards()

    for number, rarity, card_name in card_names:
        session.add(CardDefinition(
            season_id=season.id,
            card_number=number,
            rarity=rarity,
            name=card_name,
        ))

    return season


def _generate_default_cards() -> list[tuple[int, str, str]]:
    """生成默认32张卡配置: (card_number, rarity, name)"""
    return [
        # === 普通 (12) ===
        (1, "common", "羊角酒馆的甜酿师"),
        (2, "common", "月蓝狼契"),
        (3, "common", "血月霜羽术士"),
        (6, "common", "墓园蓝焰骑士"),
        (7, "common", "月下触魂妖"),
        (9, "common", "灵灯炼金师"),
        (10, "common", "晴穹弦歌者"),
        (11, "common", "龙骸余烬侍女"),
        (12, "common", "赤潮回旋女巫"),
        (13, "common", "金瞳酒窖游荡者"),
        (14, "common", "寒星秘仪导师"),
        (27, "common", "霜刃酒歌剑士"),
        # === 稀有 (11) ===
        (4, "rare", "月灯蜜誓"),
        (5, "rare", "赤喉龙灾下的远征"),
        (15, "rare", "绯樱狐巫"),
        (16, "rare", "星渊蓝焰术士"),
        (17, "rare", "霓虹酒窖魅影"),
        (18, "rare", "云上百花猎手"),
        (19, "rare", "锁链圣痕天使"),
        (20, "rare", "静默白袍牧师"),
        (21, "rare", "倒悬囚笼的献祭者"),
        (22, "rare", "冰晶秘典师"),
        (23, "rare", "深海宝箱怪"),
        # === 史诗 (6) ===
        (8, "epic", "千眼玻璃囚徒"),
        (24, "epic", "熔脉斩首者"),
        (25, "epic", "赤晶锁座女王"),
        (26, "epic", "焚心赤刃魔女"),
        (28, "epic", "三相幻胶"),
        (29, "epic", "翡翠星矢德鲁伊"),
        # === 传说 (3) ===
        (30, "legendary", "暗炉三人密会"),
        (31, "legendary", "血月亡军统领"),
        (32, "legendary", "倒悬霜翼"),
    ]


# ==================== 特典奖励 ====================


@with_session
async def check_tokuten_unlocked(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> bool:
    """检查特典是否已解锁"""
    assert session is not None
    stmt = sqlalchemy.select(sa_func.count()).where(
        UserTokuten.user_id == user_id,
        UserTokuten.chat_id == chat_id,
        UserTokuten.season_id == season_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one() > 0


@with_tx
async def unlock_tokuten(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> UserTokuten:
    """解锁特典奖励（集齐32张卡后自动触发）"""
    assert session is not None
    tokuten = UserTokuten(
        user_id=user_id,
        chat_id=chat_id,
        season_id=season_id,
    )
    session.add(tokuten)
    await session.flush()
    return tokuten


@with_session
async def get_user_tokuten(
    user_id: int, chat_id: int, season_id: int,
    session: AsyncSession | None = None,
) -> UserTokuten | None:
    """获取用户特典记录"""
    assert session is not None
    stmt = sqlalchemy.select(UserTokuten).where(
        UserTokuten.user_id == user_id,
        UserTokuten.chat_id == chat_id,
        UserTokuten.season_id == season_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

