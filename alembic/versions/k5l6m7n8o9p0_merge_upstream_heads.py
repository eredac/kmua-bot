"""merge upstream heads

Revision ID: k5l6m7n8o9p0
Revises: f5e6g7h8i9j0, j4k5l6m7n8o9
Create Date: 2026-03-30 18:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "k5l6m7n8o9p0"
down_revision: tuple[str, str] = ("f5e6g7h8i9j0", "j4k5l6m7n8o9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
