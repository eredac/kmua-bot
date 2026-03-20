from typing import Sequence

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import PointsTransaction, UserPoints


@with_session
async def get_user_points(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> UserPoints | None:
    """获取用户在指定群组的积分余额，不存在则返回 None"""
    assert session is not None
    return await session.get(UserPoints, (user_id, chat_id))


@with_tx
async def get_or_create_user_points(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> UserPoints:
    """获取用户积分，不存在则初始化为 0"""
    assert session is not None
    user_points = await session.get(UserPoints, (user_id, chat_id))
    if user_points is None:
        user_points = UserPoints(user_id=user_id, chat_id=chat_id, points=0)
        session.add(user_points)
    return user_points


@with_tx
async def add_points(
    user_id: int,
    chat_id: int,
    amount: int,
    reason: str | None = None,
    operator_id: int | None = None,
    session: AsyncSession | None = None,
) -> UserPoints:
    """给用户增加积分并记录流水。amount 必须为正数"""
    assert session is not None
    if amount <= 0:
        raise ValueError(f"amount 必须为正数，got {amount}")

    user_points = await session.get(UserPoints, (user_id, chat_id))
    if user_points is None:
        user_points = UserPoints(user_id=user_id, chat_id=chat_id, points=0)
        session.add(user_points)

    user_points.points += amount
    session.add(
        PointsTransaction(
            user_id=user_id,
            chat_id=chat_id,
            amount=amount,
            reason=reason,
            operator_id=operator_id,
        )
    )
    return user_points


@with_tx
async def cost_points(
    user_id: int,
    chat_id: int,
    amount: int,
    reason: str | None = None,
    operator_id: int | None = None,
    session: AsyncSession | None = None,
) -> UserPoints:
    """扣除用户积分并记录流水。amount 必须为正数，余额不足时抛出 ValueError"""
    assert session is not None
    if amount <= 0:
        raise ValueError(f"amount 必须为正数，got {amount}")

    user_points = await session.get(UserPoints, (user_id, chat_id))
    if user_points is None:
        user_points = UserPoints(user_id=user_id, chat_id=chat_id, points=0)
        session.add(user_points)

    if user_points.points < amount:
        raise ValueError(
            f"积分不足：当前 {user_points.points}，需要 {amount}"
        )

    user_points.points -= amount
    session.add(
        PointsTransaction(
            user_id=user_id,
            chat_id=chat_id,
            amount=-amount,
            reason=reason,
            operator_id=operator_id,
        )
    )
    return user_points


@with_tx
async def set_points(
    user_id: int,
    chat_id: int,
    points: int,
    reason: str | None = None,
    operator_id: int | None = None,
    session: AsyncSession | None = None,
) -> UserPoints:
    """直接设置用户积分（管理员操作），并记录差值流水"""
    assert session is not None

    user_points = await session.get(UserPoints, (user_id, chat_id))
    if user_points is None:
        user_points = UserPoints(user_id=user_id, chat_id=chat_id, points=0)
        session.add(user_points)

    delta = points - user_points.points
    user_points.points = points
    if delta != 0:
        session.add(
            PointsTransaction(
                user_id=user_id,
                chat_id=chat_id,
                amount=delta,
                reason=reason,
                operator_id=operator_id,
            )
        )
    return user_points


@with_session
async def get_transactions(
    user_id: int,
    chat_id: int,
    limit: int = 20,
    session: AsyncSession | None = None,
) -> Sequence[PointsTransaction]:
    """获取用户在指定群组的积分流水，按时间倒序"""
    assert session is not None
    stmt = (
        sqlalchemy.select(PointsTransaction)
        .where(
            PointsTransaction.user_id == user_id,
            PointsTransaction.chat_id == chat_id,
        )
        .order_by(PointsTransaction.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@with_session
async def get_all_user_points(
    user_id: int,
    session: AsyncSession | None = None,
) -> Sequence[UserPoints]:
    """获取用户在所有群组的积分，按积分从高到低"""
    assert session is not None
    stmt = (
        sqlalchemy.select(UserPoints)
        .where(UserPoints.user_id == user_id)
        .order_by(UserPoints.points.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@with_session
async def get_chat_leaderboard(
    chat_id: int,
    limit: int = 10,
    session: AsyncSession | None = None,
) -> Sequence[UserPoints]:
    """获取群组积分排行榜，按积分从高到低"""
    assert session is not None
    stmt = (
        sqlalchemy.select(UserPoints)
        .where(UserPoints.chat_id == chat_id)
        .order_by(UserPoints.points.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@with_session
async def get_chat_leaderboard_page(
    chat_id: int,
    page: int = 0,
    page_size: int = 10,
    session: AsyncSession | None = None,
) -> Sequence:
    """获取群组积分排行榜（分页），返回 (UserPoints, full_name) Row 序列"""
    assert session is not None
    from .models import UserData

    stmt = (
        sqlalchemy.select(UserPoints, UserData.full_name)
        .join(UserData, UserPoints.user_id == UserData.id)
        .where(UserPoints.chat_id == chat_id)
        .order_by(UserPoints.points.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return result.all()


@with_session
async def get_leaderboard_total(
    chat_id: int,
    session: AsyncSession | None = None,
) -> int:
    """获取群组积分排行榜总人数"""
    assert session is not None
    stmt = sqlalchemy.select(sqlalchemy.func.count()).where(
        UserPoints.chat_id == chat_id
    )
    result = await session.execute(stmt)
    return result.scalar_one()
