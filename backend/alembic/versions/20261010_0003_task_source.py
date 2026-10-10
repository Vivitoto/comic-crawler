"""Default legacy task sources to WNACG.

Revision ID: 20261010_0003
Revises: 20260527_0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261010_0003"
down_revision: str | None = "20260527_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite does not support ALTER COLUMN; the model already supplies the
    # application-level default. Only normalize legacy rows here.
    op.execute(
        "UPDATE download_task SET source = 'wnacg' "
        "WHERE source IS NULL OR source NOT IN ('wnacg', 'jmcomic')"
    )


def downgrade() -> None:
    pass
