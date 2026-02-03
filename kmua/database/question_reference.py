"""参考提问数据访问层"""
import random
import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import QuestionReference


@with_tx
async def add_question_reference(
    chat_id: int,
    question_text: str,
    winner_id: int,
    loser_ids: list[int],
    embedding_hash: str | None = None,
    session: AsyncSession | None = None,
) -> QuestionReference:
    """添加参考提问"""
    assert session is not None

    loser_ids_str = ",".join(str(uid) for uid in loser_ids)

    question = QuestionReference(
        chat_id=chat_id,
        question_text=question_text,
        embedding_hash=embedding_hash,
        winner_id=winner_id,
        loser_ids=loser_ids_str,
        used_count=0,
    )

    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


@with_session
async def get_question_by_hash(
    embedding_hash: str,
    chat_id: int,
    session: AsyncSession | None = None,
) -> QuestionReference | None:
    """根据向量哈希查找是否有相似提问"""
    assert session is not None

    stmt = (
        sqlalchemy.select(QuestionReference)
        .where(
            QuestionReference.chat_id == chat_id,
            QuestionReference.embedding_hash == embedding_hash,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_session
async def get_random_question(
    chat_id: int,
    session: AsyncSession | None = None,
) -> QuestionReference | None:
    """随机获取一个历史提问"""
    assert session is not None

    # 先获取总数
    count_stmt = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(QuestionReference)
        .where(QuestionReference.chat_id == chat_id)
    )
    result = await session.execute(count_stmt)
    total_count = result.scalar() or 0

    if total_count == 0:
        return None

    # 随机偏移
    random_offset = random.randint(0, total_count - 1)

    stmt = (
        sqlalchemy.select(QuestionReference)
        .where(QuestionReference.chat_id == chat_id)
        .offset(random_offset)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_session
async def get_top_questions(
    chat_id: int,
    limit: int = 5,
    session: AsyncSession | None = None,
) -> list[QuestionReference]:
    """获取使用次数最多的提问"""
    assert session is not None

    stmt = (
        sqlalchemy.select(QuestionReference)
        .where(QuestionReference.chat_id == chat_id)
        .order_by(QuestionReference.used_count.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@with_tx
async def increment_question_used_count(
    question_id: int,
    session: AsyncSession | None = None,
) -> None:
    """增加提问使用次数"""
    assert session is not None

    stmt = (
        sqlalchemy.update(QuestionReference)
        .where(QuestionReference.id == question_id)
        .values(used_count=QuestionReference.used_count + 1)
    )
    await session.execute(stmt)
    await session.commit()


@with_session
async def get_question_count(
    chat_id: int,
    session: AsyncSession | None = None,
) -> int:
    """获取提问总数"""
    assert session is not None

    stmt = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(QuestionReference)
        .where(QuestionReference.chat_id == chat_id)
    )
    result = await session.execute(stmt)
    return result.scalar() or 0
