"""Initial schema (spec §8).

Revision ID: 0001
Revises:
"""

from app.migration_utils import run_sql_file

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0001_initial_schema.up.sql")


def downgrade() -> None:
    run_sql_file("0001_initial_schema.down.sql")
