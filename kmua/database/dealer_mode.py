"""荷官模式配置数据访问层"""
import sqlalchemy
import sqlalchemy.dialects.postgresql
import sqlalchemy.dialects.mysql
import sqlalchemy.dialects.sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from kmua.config import runtime_config

from .db import with_session, with_tx
from .models import DealerModeConfig


@with_session
async def get_dealer_mode_config(
    chat_id: int,
    session: AsyncSession | None = None,
) -> DealerModeConfig | None:
    """获取荷官模式配置"""
    assert session is not None

    stmt = sqlalchemy.select(DealerModeConfig).where(DealerModeConfig.chat_id == chat_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@with_tx
async def upsert_dealer_mode_config(
    chat_id: int,
    enabled: bool | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    late_players: dict | None = None,
    session: AsyncSession | None = None,
) -> DealerModeConfig:
    """创建或更新荷官模式配置"""
    assert session is not None

    values = {"chat_id": chat_id}
    if enabled is not None:
        values["enabled"] = enabled
    if start_time is not None:
        values["start_time"] = start_time
    if end_time is not None:
        values["end_time"] = end_time
    if late_players is not None:
        values["late_players"] = late_players

    if runtime_config.db_is_postgres:
        stmt = (
            sqlalchemy.dialects.postgresql.insert(DealerModeConfig)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={k: v for k, v in values.items() if k != "chat_id"},
            )
            .returning(DealerModeConfig)
        )
    elif runtime_config.db_is_mysql:
        stmt = (
            sqlalchemy.dialects.mysql.insert(DealerModeConfig)
            .values(**values)
            .on_duplicate_key_update(**{k: v for k, v in values.items() if k != "chat_id"})
        )
        await session.execute(stmt)
        return await get_dealer_mode_config(chat_id, session=session)  # type: ignore
    else:  # SQLite
        stmt = (
            sqlalchemy.dialects.sqlite.insert(DealerModeConfig)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["chat_id"],
                set_={k: v for k, v in values.items() if k != "chat_id"},
            )
            .returning(DealerModeConfig)
        )

    result = await session.execute(stmt)
    config = result.scalar_one()
    return config


@with_tx
async def clear_late_players(
    chat_id: int,
    session: AsyncSession | None = None,
) -> None:
    """清空迟到玩家列表"""
    assert session is not None

    stmt = (
        sqlalchemy.update(DealerModeConfig)
        .where(DealerModeConfig.chat_id == chat_id)
        .values(late_players={})
    )
    await session.execute(stmt)


@with_tx
async def add_late_player(
    chat_id: int,
    user_id: int,
    username: str | None,
    first_name: str,
    session: AsyncSession | None = None,
) -> None:
    """添加迟到玩家"""
    assert session is not None

    config = await get_dealer_mode_config(chat_id, session=session)
    if not config:
        # 如果配置不存在，创建默认配置
        config = await upsert_dealer_mode_config(
            chat_id=chat_id,
            enabled=False,
            late_players={},
            session=session,
        )

    late_players = config.late_players.copy()
    user_id_str = str(user_id)

    if user_id_str in late_players:
        # 增加计数
        late_players[user_id_str]["roll_count"] += 1
    else:
        # 新增玩家
        late_players[user_id_str] = {
            "username": username,
            "first_name": first_name,
            "roll_count": 1,
        }

    stmt = (
        sqlalchemy.update(DealerModeConfig)
        .where(DealerModeConfig.chat_id == chat_id)
        .values(late_players=late_players)
    )
    await session.execute(stmt)


@with_session
async def get_all_dealer_mode_chats(
    session: AsyncSession | None = None,
) -> list[DealerModeConfig]:
    """获取所有启用了荷官模式的群组配置"""
    assert session is not None

    stmt = sqlalchemy.select(DealerModeConfig).where(DealerModeConfig.enabled == True)
    result = await session.execute(stmt)
    return list(result.scalars().all())
