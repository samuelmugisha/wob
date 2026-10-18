"""Reviewer verification of claims.

Revision ID: 0005
Revises: 0004
"""

from app.migration_utils import run_sql_file

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0005_claim_verification.up.sql")


def downgrade() -> None:
    run_sql_file("0005_claim_verification.down.sql")
