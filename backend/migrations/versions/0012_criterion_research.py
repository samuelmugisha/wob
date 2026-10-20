"""External research by award criterion.

Revision ID: 0012
Revises: 0011
"""

from app.migration_utils import run_sql_file

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0012_criterion_research.up.sql")


def downgrade() -> None:
    run_sql_file("0012_criterion_research.down.sql")
