"""Coordinator document uploads.

Revision ID: 0002
Revises: 0001
"""

from app.migration_utils import run_sql_file

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0002_document_uploads.up.sql")


def downgrade() -> None:
    run_sql_file("0002_document_uploads.down.sql")
