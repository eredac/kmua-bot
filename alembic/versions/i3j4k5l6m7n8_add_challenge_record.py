"""add challenge_record table

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-03-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, None] = "h2i3j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "challenge_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("challenger_id", sa.BigInteger(), nullable=False),
        sa.Column("challengee_id", sa.BigInteger(), nullable=True),
        sa.Column("bet_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "challenger_commission",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "challengee_commission",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("challenger_choice", sa.String(length=10), nullable=True),
        sa.Column("challengee_choice", sa.String(length=10), nullable=True),
        sa.Column("winner_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["shared.chat_data.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["challenger_id"],
            ["shared.user_data.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["challengee_id"],
            ["shared.user_data.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="shared",
    )
    op.create_index(
        "ix_shared_challenge_record_id",
        "challenge_record",
        ["id"],
        schema="shared",
    )
    op.create_index(
        "ix_shared_challenge_record_chat_id",
        "challenge_record",
        ["chat_id"],
        schema="shared",
    )
    op.create_index(
        "ix_shared_challenge_record_challenger_id",
        "challenge_record",
        ["challenger_id"],
        schema="shared",
    )
    op.create_index(
        "ix_shared_challenge_record_challengee_id",
        "challenge_record",
        ["challengee_id"],
        schema="shared",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shared_challenge_record_challengee_id",
        table_name="challenge_record",
        schema="shared",
    )
    op.drop_index(
        "ix_shared_challenge_record_challenger_id",
        table_name="challenge_record",
        schema="shared",
    )
    op.drop_index(
        "ix_shared_challenge_record_chat_id",
        table_name="challenge_record",
        schema="shared",
    )
    op.drop_index(
        "ix_shared_challenge_record_id",
        table_name="challenge_record",
        schema="shared",
    )
    op.drop_table("challenge_record", schema="shared")
