"""add affection histogram (skipped - table not used in this fork)

Revision ID: aa1bb2cc3dd4
Revises: d327932d860e
Create Date: 2025-12-25 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa1bb2cc3dd4"
down_revision: str | None = "d327932d860e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Skipped: affection_histogram is not used in this fork."""
    pass


def downgrade() -> None:
    """Skipped: affection_histogram is not used in this fork."""
    pass
