"""External research of public sources.

Revision ID: 0006
Revises: 0005
"""

from app.migration_utils import run_sql_file

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0006_external_research.up.sql")


def downgrade() -> None:
    run_sql_file("0006_external_research.down.sql")
