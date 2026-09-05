import datetime
from typing import Sequence

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import PendingTagGift, UserTag

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
        # 续费：在当前到期时间基础上叠加，已过期则从 now 起算
        base = max(tag.expires_at.replace(tzinfo=_TZ_UTC), now)
        tag.tag_text = tag_text
        tag.expires_at = base + datetime.timedelta(days=duration_days)
    return tag


@with_tx
async def update_tag_text_only(
    user_id: int,
    chat_id: int,
    tag_text: str,
    session: AsyncSession | None = None,
) -> UserTag:
    """仅修改标签文字，不改变到期时间。标签不存在或已过期时抛出 ValueError"""
    assert session is not None
    tag = await session.get(UserTag, (user_id, chat_id))
    if tag is None:
        raise ValueError("您在本群还没有标签，请先使用 /settag 购买")
    now = datetime.datetime.now(_TZ_UTC)
    if tag.expires_at.replace(tzinfo=_TZ_UTC) <= now:
        raise ValueError("您的标签已过期，请使用 /settag 续费后再修改")
    tag.tag_text = tag_text
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


# ─── PendingTagGift CRUD ─────────────────────────────────


@with_tx
async def create_pending_gift(
    sender_id: int,
    sender_name: str,
    target_id: int,
    target_name: str,
    chat_id: int,
    tag_text: str,
    expires_at: datetime.datetime,
    session: AsyncSession | None = None,
) -> PendingTagGift:
    assert session is not None
    gift = PendingTagGift(
        sender_id=sender_id,
        sender_name=sender_name,
        target_id=target_id,
        target_name=target_name,
        chat_id=chat_id,
        tag_text=tag_text,
        expires_at=expires_at,
    )
    session.add(gift)
    await session.flush()
    return gift


@with_tx
async def update_gift_message_id(
    gift_id: int, message_id: int, session: AsyncSession | None = None
) -> None:
    assert session is not None
    stmt = (
        sqlalchemy.update(PendingTagGift)
        .where(PendingTagGift.id == gift_id)
        .values(message_id=message_id)
    )
    await session.execute(stmt)


@with_session
async def get_pending_gift(
    gift_id: int, session: AsyncSession | None = None
) -> PendingTagGift | None:
    assert session is not None
    return await session.get(PendingTagGift, gift_id)


@with_tx
async def complete_pending_gift(
    gift_id: int, status: str = "accepted", session: AsyncSession | None = None
) -> None:
    assert session is not None
    stmt = (
        sqlalchemy.update(PendingTagGift)
        .where(PendingTagGift.id == gift_id, PendingTagGift.status == "pending")
        .values(status=status)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise ValueError("gift_not_pending")


@with_session
async def get_expired_pending_gifts(
    session: AsyncSession | None = None,
) -> Sequence[PendingTagGift]:
    assert session is not None
    now = datetime.datetime.now(_TZ_UTC)
    stmt = sqlalchemy.select(PendingTagGift).where(
        PendingTagGift.status == "pending",
        PendingTagGift.expires_at < now,
    )
    result = await session.execute(stmt)
    return result.scalars().all()
