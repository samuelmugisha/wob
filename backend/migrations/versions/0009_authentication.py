"""Authentication.

Revision ID: 0009
Revises: 0008
"""

from app.migration_utils import run_sql_file

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0009_authentication.up.sql")


def downgrade() -> None:
    run_sql_file("0009_authentication.down.sql")
