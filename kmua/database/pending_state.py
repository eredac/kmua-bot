"""待提问状态持久化（重启恢复，5分钟 TTL）"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import sqlalchemy
import sqlalchemy.dialects.postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import PendingQuestionState

_TTL_SECONDS = 300  # 5 分钟


def _serialize(pending) -> dict:
    """将 PendingQuestion dataclass 序列化为 dict"""
    return {
        "chat_id": pending.chat_id,
        "thread_id": pending.thread_id,
        "winner_id": pending.winner_id,
        "loser_ids": pending.loser_ids,
        "winner_mentions": pending.winner_mentions,
        "loser_mentions": pending.loser_mentions,
        "timestamp": pending.timestamp,
    }


def _deserialize(data: dict):
    """将 dict 反序列化为 PendingQuestion（延迟导入避免循环依赖）"""
    from kmua.plugins.dice_game import PendingQuestion
    return PendingQuestion(
        chat_id=data["chat_id"],
        thread_id=data.get("thread_id"),
        winner_id=data["winner_id"],
        loser_ids=data["loser_ids"],
        winner_mentions=data["winner_mentions"],
        loser_mentions=data["loser_mentions"],
        timestamp=data["timestamp"],
    )


@with_tx
async def upsert_pending_question(
    user_id: int,
    pending,
    ttl_seconds: int = _TTL_SECONDS,
    session: AsyncSession | None = None,
) -> None:
    """写入或更新待提问状态"""
    assert session is not None
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    state_dict = _serialize(pending)

    stmt = (
        sqlalchemy.dialects.postgresql.insert(PendingQuestionState)
        .values(user_id=user_id, state=state_dict, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={"state": state_dict, "expires_at": expires_at},
        )
    )
    await session.execute(stmt)


@with_tx
async def delete_pending_question(
    user_id: int,
    session: AsyncSession | None = None,
) -> None:
    """删除待提问状态（提问完成后调用）"""
    assert session is not None
    await session.execute(
        sqlalchemy.delete(PendingQuestionState).where(
            PendingQuestionState.user_id == user_id
        )
    )


@with_session
async def load_valid_pending_questions(
    session: AsyncSession | None = None,
) -> dict:
    """启动时加载所有未过期的待提问状态"""
    assert session is not None
    now = datetime.now(timezone.utc)
    stmt = sqlalchemy.select(PendingQuestionState).where(
        PendingQuestionState.expires_at > now
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    pending_map = {}
    for row in rows:
        try:
            pending_map[row.user_id] = _deserialize(row.state)
        except Exception:
            pass  # 反序列化失败的记录跳过
    return pending_map


@with_tx
async def cleanup_expired_pending_questions(
    session: AsyncSession | None = None,
) -> None:
    """清理已过期的记录"""
    assert session is not None
    now = datetime.now(timezone.utc)
    await session.execute(
        sqlalchemy.delete(PendingQuestionState).where(
            PendingQuestionState.expires_at <= now
        )
    )
