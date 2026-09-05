"""add user_tokuten table for special reward system

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-09-02 14:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m7n8o9p0q1r2"
down_revision: str = "l6m7n8o9p0q1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 检查表是否已存在
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("user_tokuten", schema="kmua"):
        op.create_table(
            "user_tokuten",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("season_id", sa.Integer(), nullable=False),
            sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["shared.user_data.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "season_id", name="uq_user_tokuten"),
            sa.PrimaryKeyConstraint("id"),
            schema="kmua",
        )

    # 创建索引(带防御检查)
    tokuten_indexes = [idx["name"] for idx in insp.get_indexes("user_tokuten", schema="kmua")]
    if "ix_kmua_user_tokuten_id" not in tokuten_indexes:
        op.create_index("ix_kmua_user_tokuten_id", "user_tokuten", ["id"], schema="kmua")
    if "ix_kmua_user_tokuten_user_id" not in tokuten_indexes:
        op.create_index("ix_kmua_user_tokuten_user_id", "user_tokuten", ["user_id"], schema="kmua")
    if "ix_kmua_user_tokuten_season_id" not in tokuten_indexes:
        op.create_index("ix_kmua_user_tokuten_season_id", "user_tokuten", ["season_id"], schema="kmua")


def downgrade() -> None:
    op.drop_table("user_tokuten", schema="kmua")
