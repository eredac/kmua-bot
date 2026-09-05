from datetime import datetime, timedelta, timezone
from typing import Sequence

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import ChallengeRecord

_TZ_CST = timezone(timedelta(hours=8))


def _today_cst_start() -> datetime:
    """返回今日 CST 00:00:00（含时区）"""
    now_cst = datetime.now(_TZ_CST)
    return now_cst.replace(hour=0, minute=0, second=0, microsecond=0)


@with_session
async def get_challenge(
    challenge_id: int,
    session: AsyncSession | None = None,
) -> ChallengeRecord | None:
    """按主键获取挑战记录"""
    assert session is not None
    return await session.get(ChallengeRecord, challenge_id)


@with_tx
async def create_challenge(
    chat_id: int,
    challenger_id: int,
    challengee_id: int | None,
    bet_amount: int,
    challenger_commission: int,
    challengee_commission: int,
    expires_at: datetime | None = None,
    session: AsyncSession | None = None,
) -> ChallengeRecord:
    """创建新挑战记录（状态 pending），flush 后返回含 id 的对象"""
    assert session is not None
    record = ChallengeRecord(
        chat_id=chat_id,
        challenger_id=challenger_id,
        challengee_id=challengee_id,
        bet_amount=bet_amount,
        challenger_commission=challenger_commission,
        challengee_commission=challengee_commission,
        status="pending",
        expires_at=expires_at,
    )
    session.add(record)
    await session.flush()  # 让数据库分配 id
    return record


@with_tx
async def update_challenge_message_id(
    challenge_id: int,
    message_id: int,
    session: AsyncSession | None = None,
) -> None:
    """发送挑战消息后回填 message_id"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record:
        record.message_id = message_id


@with_tx
async def update_challenge_expires_at(
    challenge_id: int,
    expires_at: datetime,
    session: AsyncSession | None = None,
) -> None:
    """更新挑战的截止时间（接受后切换为出拳倒计时）"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record:
        record.expires_at = expires_at


@with_session
async def get_daily_challenge_count(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> int:
    """获取用户今日（CST）在指定群组参与的有效挑战次数（发起+已接受，排除已过期/取消的）
    作为发起者：所有非过期/取消的都计入
    作为接受者：仅计入已实际接受的（pending_rps/completed）
    """
    assert session is not None
    today_start = _today_cst_start()
    # 作为发起者
    as_challenger = sqlalchemy.select(sqlalchemy.func.count()).where(
        ChallengeRecord.challenger_id == user_id,
        ChallengeRecord.chat_id == chat_id,
        ChallengeRecord.created_at >= today_start,
        ChallengeRecord.status.not_in(["expired", "cancelled"]),
    )
    # 作为接受者（仅已接受的）
    as_challengee = sqlalchemy.select(sqlalchemy.func.count()).where(
        ChallengeRecord.challengee_id == user_id,
        ChallengeRecord.chat_id == chat_id,
        ChallengeRecord.created_at >= today_start,
        ChallengeRecord.status.in_(["pending_rps", "completed"]),
    )
    r1 = await session.execute(as_challenger)
    r2 = await session.execute(as_challengee)
    return r1.scalar_one() + r2.scalar_one()


@with_tx
async def accept_challenge(
    challenge_id: int,
    accepter_id: int,
    new_expires_at: datetime | None = None,
    session: AsyncSession | None = None,
) -> ChallengeRecord:
    """接受挑战：更新 challengee_id（开放挑战），状态改为 pending_rps"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record is None:
        raise ValueError(f"挑战记录 #{challenge_id} 不存在")
    if record.status != "pending":
        raise ValueError("该挑战已不处于等待接受状态")
    record.challengee_id = accepter_id
    record.status = "pending_rps"
    record.expires_at = new_expires_at
    return record


@with_tx
async def set_challenge_choice(
    challenge_id: int,
    user_id: int,
    choice: str,
    session: AsyncSession | None = None,
) -> ChallengeRecord:
    """记录出拳选择；返回更新后的记录"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record is None:
        raise ValueError(f"挑战记录 #{challenge_id} 不存在")
    if record.status != "pending_rps":
        raise ValueError("该挑战当前不在出拳阶段")
    if user_id == record.challenger_id:
        if record.challenger_choice is not None:
            raise ValueError("already_chosen")
        record.challenger_choice = choice
    elif user_id == record.challengee_id:
        if record.challengee_choice is not None:
            raise ValueError("already_chosen")
        record.challengee_choice = choice
    else:
        raise ValueError("not_participant")
    return record


@with_tx
async def complete_challenge(
    challenge_id: int,
    winner_id: int,  # 0 = 平局
    session: AsyncSession | None = None,
) -> ChallengeRecord:
    """标记挑战完成，记录胜者。status 不是 pending_rps 时抛出 ValueError（防并发重复结算）"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record is None:
        raise ValueError(f"挑战记录 #{challenge_id} 不存在")
    if record.status != "pending_rps":
        raise ValueError("already_completed")
    record.status = "completed"
    record.winner_id = winner_id
    return record


@with_tx
async def expire_challenge(
    challenge_id: int,
    session: AsyncSession | None = None,
) -> ChallengeRecord | None:
    """将 pending 状态挑战标记为 expired（超时取消）。已非 pending 则静默忽略"""
    assert session is not None
    record = await session.get(ChallengeRecord, challenge_id)
    if record and record.status == "pending":
        record.status = "expired"
    return record


@with_session
async def get_expired_challenges(
    status: str,
    session: AsyncSession | None = None,
) -> Sequence[ChallengeRecord]:
    """获取指定状态且已超时的挑战列表（用于启动时恢复）"""
    assert session is not None
    now = datetime.now(timezone.utc)
    stmt = sqlalchemy.select(ChallengeRecord).where(
        ChallengeRecord.status == status,
        ChallengeRecord.expires_at.is_not(None),
        ChallengeRecord.expires_at <= now,
    )
    result = await session.execute(stmt)
    return result.scalars().all()
