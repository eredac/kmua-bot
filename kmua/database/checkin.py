import datetime

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import DailyCheckIn, PointsTransaction, UserPoints

# 与 waifu 重置保持一致：UTC+8 凌晨 4 点为每日分界线
_TZ_CST = datetime.timezone(datetime.timedelta(hours=8))
_RESET_HOUR = 4


def get_checkin_date() -> str:
    """返回当前签到日期字符串（YYYY-MM-DD），以 UTC+8 凌晨4点为日期分界"""
    now = datetime.datetime.now(_TZ_CST)
    if now.hour < _RESET_HOUR:
        d = (now - datetime.timedelta(days=1)).date()
    else:
        d = now.date()
    return d.strftime("%Y-%m-%d")


@with_session
async def get_user_checkin_type_count_today(
    user_id: int,
    checkin_type: str,
    session: AsyncSession | None = None,
) -> int:
    """返回用户今日在所有群指定类型的签到总次数（用于 inline query 阶段无 chat_id 的场景）"""
    assert session is not None
    today = get_checkin_date()
    stmt = sqlalchemy.select(sqlalchemy.func.count()).where(
        DailyCheckIn.user_id == user_id,
        DailyCheckIn.checkin_date == today,
        DailyCheckIn.checkin_type == checkin_type,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


@with_session
async def has_any_checkin_today(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> bool:
    """检查用户今日在该群是否有任意类型的签到记录"""
    assert session is not None
    today = get_checkin_date()
    stmt = sqlalchemy.select(sqlalchemy.func.count()).where(
        DailyCheckIn.user_id == user_id,
        DailyCheckIn.chat_id == chat_id,
        DailyCheckIn.checkin_date == today,
    )
    result = await session.execute(stmt)
    return result.scalar_one() > 0


@with_session
async def get_checkin_count_today(
    user_id: int,
    chat_id: int,
    checkin_type: str,
    session: AsyncSession | None = None,
) -> int:
    """返回用户今日在该群指定类型的签到次数"""
    assert session is not None
    today = get_checkin_date()
    stmt = sqlalchemy.select(sqlalchemy.func.count()).where(
        DailyCheckIn.user_id == user_id,
        DailyCheckIn.chat_id == chat_id,
        DailyCheckIn.checkin_date == today,
        DailyCheckIn.checkin_type == checkin_type,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


@with_session
async def get_consecutive_streak(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> int:
    """计算用户在该群的连续签到天数（以当前签到日期为基准）"""
    assert session is not None
    stmt = (
        sqlalchemy.select(sqlalchemy.func.distinct(DailyCheckIn.checkin_date))
        .where(
            DailyCheckIn.user_id == user_id,
            DailyCheckIn.chat_id == chat_id,
        )
        .order_by(DailyCheckIn.checkin_date.desc())
        .limit(400)
    )
    result = await session.execute(stmt)
    dates_str = [row[0] for row in result.all()]

    if not dates_str:
        return 0

    today = get_checkin_date()
    today_date = datetime.date.fromisoformat(today)
    dates = sorted(
        [datetime.date.fromisoformat(d) for d in dates_str],
        reverse=True,
    )

    # 最近签到距今超过 1 天，连续中断
    if dates[0] < today_date - datetime.timedelta(days=1):
        return 0

    streak = 1
    for i in range(1, len(dates)):
        if dates[i] == dates[i - 1] - datetime.timedelta(days=1):
            streak += 1
        else:
            break
    return streak


@with_tx
async def record_checkin_and_add_points(
    user_id: int,
    chat_id: int,
    checkin_type: str,
    points: int,
    session: AsyncSession | None = None,
) -> UserPoints:
    """记录签到并增加积分（同一事务）。调用方须先通过计数检查保证不超限。"""
    assert session is not None
    today = get_checkin_date()

    session.add(
        DailyCheckIn(
            user_id=user_id,
            chat_id=chat_id,
            checkin_date=today,
            checkin_type=checkin_type,
            points_earned=points,
        )
    )

    user_points = await session.get(UserPoints, (user_id, chat_id))
    if user_points is None:
        user_points = UserPoints(user_id=user_id, chat_id=chat_id, points=0)
        session.add(user_points)
    user_points.points += points

    session.add(
        PointsTransaction(
            user_id=user_id,
            chat_id=chat_id,
            amount=points,
            reason=f"签到奖励（{checkin_type}）",
        )
    )

    return user_points
