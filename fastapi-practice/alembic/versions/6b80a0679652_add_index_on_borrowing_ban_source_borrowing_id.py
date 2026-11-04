"""Add index on borrowing_ban.source_borrowing_id

Revision ID: 6b80a0679652
Revises: 2445c20e0ab5
Create Date: 2026-11-02 15:08:11.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b80a0679652"
down_revision: str | Sequence[str] | None = "2445c20e0ab5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        op.f("ix_borrowing_ban_source_borrowing_id"),
        "borrowing_ban",
        ["source_borrowing_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_borrowing_ban_source_borrowing_id"), table_name="borrowing_ban")
