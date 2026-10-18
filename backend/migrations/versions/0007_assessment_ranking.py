"""Criterion assessment and provisional ranking.

Revision ID: 0007
Revises: 0006
"""

from app.migration_utils import run_sql_file

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0007_assessment_ranking.up.sql")


def downgrade() -> None:
    run_sql_file("0007_assessment_ranking.down.sql")
