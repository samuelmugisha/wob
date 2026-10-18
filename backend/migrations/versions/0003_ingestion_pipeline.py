"""Ingestion worker bookkeeping and knowledge base view.

Revision ID: 0003
Revises: 0002
"""

from app.migration_utils import run_sql_file

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0003_ingestion_pipeline.up.sql")


def downgrade() -> None:
    run_sql_file("0003_ingestion_pipeline.down.sql")
