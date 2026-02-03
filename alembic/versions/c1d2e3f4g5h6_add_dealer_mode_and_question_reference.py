"""add_dealer_mode_and_question_reference

Revision ID: c1d2e3f4g5h6
Revises: b1c2d3e4f5g6
Create Date: 2026-02-03 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4g5h6"
down_revision: Union[str, None] = "b1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 创建 dealer_mode_config 表
    table_name = "dealer_mode_config"
    if not insp.has_table(table_name):
        op.create_table(
            "dealer_mode_config",
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, default=False),
            sa.Column("start_time", sa.String(length=5), nullable=False, default="20:00"),
            sa.Column("end_time", sa.String(length=5), nullable=False, default="22:00"),
            sa.Column("late_players", sa.JSON(), nullable=False, default={}),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("chat_id"),
        )
        op.create_index(op.f("ix_dealer_mode_config_chat_id"), "dealer_mode_config", ["chat_id"], unique=False)

    # 创建 question_reference 表
    table_name = "question_reference"
    if not insp.has_table(table_name):
        op.create_table(
            "question_reference",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("question_text", sa.String(length=4096), nullable=False),
            sa.Column("embedding_hash", sa.String(length=64), nullable=True),
            sa.Column("winner_id", sa.BigInteger(), nullable=False),
            sa.Column("loser_ids", sa.String(length=256), nullable=False),
            sa.Column("used_count", sa.Integer(), nullable=False, default=0),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_question_reference_id"), "question_reference", ["id"], unique=False)
        op.create_index(op.f("ix_question_reference_chat_id"), "question_reference", ["chat_id"], unique=False)
        op.create_index(op.f("ix_question_reference_embedding_hash"), "question_reference", ["embedding_hash"], unique=False)
        op.create_index(op.f("ix_question_reference_winner_id"), "question_reference", ["winner_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 删除 question_reference 表
    op.drop_index(op.f("ix_question_reference_winner_id"), table_name="question_reference")
    op.drop_index(op.f("ix_question_reference_embedding_hash"), table_name="question_reference")
    op.drop_index(op.f("ix_question_reference_chat_id"), table_name="question_reference")
    op.drop_index(op.f("ix_question_reference_id"), table_name="question_reference")
    op.drop_table("question_reference")

    # 删除 dealer_mode_config 表
    op.drop_index(op.f("ix_dealer_mode_config_chat_id"), table_name="dealer_mode_config")
    op.drop_table("dealer_mode_config")
