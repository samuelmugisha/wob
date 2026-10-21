"""Administrators may unfreeze rubrics and amend approved ones.

Revision ID: 0013
Revises: 0012
"""

from app.migration_utils import run_sql_file

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0013_rubric_admin_changes.up.sql")


def downgrade() -> None:
    run_sql_file("0013_rubric_admin_changes.down.sql")
