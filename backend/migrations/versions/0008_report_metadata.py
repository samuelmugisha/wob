"""Report provenance.

Revision ID: 0008
Revises: 0007
"""

from app.migration_utils import run_sql_file

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0008_report_metadata.up.sql")


def downgrade() -> None:
    run_sql_file("0008_report_metadata.down.sql")
