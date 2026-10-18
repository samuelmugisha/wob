"""Calibration of AI ratings.

Revision ID: 0010
Revises: 0009
"""

from app.migration_utils import run_sql_file

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0010_calibration.up.sql")


def downgrade() -> None:
    run_sql_file("0010_calibration.down.sql")
