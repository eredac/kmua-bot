"""add chat_id to user_tokuten for per-group tokuten unlock tracking

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-09-02 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n8o9p0q1r2s3"
down_revision: str = "m7n8o9p0q1r2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add chat_id column (nullable for existing data)
    op.add_column(
        "user_tokuten",
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        schema="kmua",
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_user_tokuten_chat_id",
        "user_tokuten",
        "chat_data",
        ["chat_id"],
        ["id"],
        source_schema="kmua",
        referent_schema="shared",
        ondelete="CASCADE",
    )

    # Add index on chat_id
    op.create_index(
        "ix_kmua_user_tokuten_chat_id",
        "user_tokuten",
        ["chat_id"],
        schema="kmua",
    )

    # Drop old unique constraint
    op.drop_constraint(
        "uq_user_tokuten",
        "user_tokuten",
        schema="kmua",
        type_="unique",
    )

    # Create new unique constraint with chat_id
    op.create_unique_constraint(
        "uq_user_tokuten_chat",
        "user_tokuten",
        ["user_id", "chat_id", "season_id"],
        schema="kmua",
    )


def downgrade() -> None:
    # Drop new unique constraint
    op.drop_constraint(
        "uq_user_tokuten_chat",
        "user_tokuten",
        schema="kmua",
        type_="unique",
    )

    # Recreate old unique constraint
    op.create_unique_constraint(
        "uq_user_tokuten",
        "user_tokuten",
        ["user_id", "season_id"],
        schema="kmua",
    )

    # Drop index
    op.drop_index(
        "ix_kmua_user_tokuten_chat_id",
        "user_tokuten",
        schema="kmua",
    )

    # Drop foreign key constraint
    op.drop_constraint(
        "fk_user_tokuten_chat_id",
        "user_tokuten",
        schema="kmua",
        type_="foreignkey",
    )

    # Drop chat_id column
    op.drop_column("user_tokuten", "chat_id", schema="kmua")
