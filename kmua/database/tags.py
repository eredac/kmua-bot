import datetime
from typing import Sequence

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import UserTag

_TZ_UTC = datetime.timezone.utc


@with_session
async def get_user_tag(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> UserTag | None:
    """查询用户在指定群组的标签，不存在则返回 None"""
    assert session is not None
    return await session.get(UserTag, (user_id, chat_id))


@with_tx
async def upsert_user_tag(
    user_id: int,
    chat_id: int,
    tag_text: str,
    duration_days: int = 30,
    session: AsyncSession | None = None,
) -> UserTag:
    """新建或续费标签（expires_at = now + duration_days），不含扣积分操作"""
    assert session is not None
    tag = await session.get(UserTag, (user_id, chat_id))
    now = datetime.datetime.now(_TZ_UTC)
    if tag is None:
        tag = UserTag(
            user_id=user_id,
            chat_id=chat_id,
            tag_text=tag_text,
            expires_at=now + datetime.timedelta(days=duration_days),
        )
        session.add(tag)
    else:
        # 续费：始终以当前时间起算，不叠加旧剩余时间
        tag.tag_text = tag_text
        tag.expires_at = now + datetime.timedelta(days=duration_days)
    return tag


@with_tx
async def delete_user_tag(
    user_id: int,
    chat_id: int,
    session: AsyncSession | None = None,
) -> None:
    """删除用户在指定群组的标签记录"""
    assert session is not None
    tag = await session.get(UserTag, (user_id, chat_id))
    if tag is not None:
        await session.delete(tag)


@with_session
async def get_expiring_tags(
    within_hours: int = 24,
    session: AsyncSession | None = None,
) -> Sequence[UserTag]:
    """查询即将到期的标签（expires_at 在 now ~ now+within_hours 之间）"""
    assert session is not None
    now = datetime.datetime.now(_TZ_UTC)
    deadline = now + datetime.timedelta(hours=within_hours)
    stmt = sqlalchemy.select(UserTag).where(
        UserTag.expires_at > now,
        UserTag.expires_at <= deadline,
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@with_session
async def get_expired_tags(
    session: AsyncSession | None = None,
) -> Sequence[UserTag]:
    """查询已过期的标签（expires_at < now）"""
    assert session is not None
    now = datetime.datetime.now(_TZ_UTC)
    stmt = sqlalchemy.select(UserTag).where(UserTag.expires_at < now)
    result = await session.execute(stmt)
    return result.scalars().all()
