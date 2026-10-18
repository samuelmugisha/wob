"""Claim extraction runs.

Revision ID: 0004
Revises: 0003
"""

from app.migration_utils import run_sql_file

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0004_claim_extraction.up.sql")


def downgrade() -> None:
    run_sql_file("0004_claim_extraction.down.sql")
