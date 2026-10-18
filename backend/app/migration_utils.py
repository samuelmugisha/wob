from pathlib import Path

from alembic import op

from app.config import get_settings

SQL_DIR = Path(__file__).resolve().parent.parent / "migrations" / "sql"


def run_sql_file(name: str) -> None:
    sql = (SQL_DIR / name).read_text()
    sql = sql.replace("__EMBEDDING_DIM__", str(get_settings().embedding_dim))
    # Execute on the raw psycopg connection: without parameters psycopg accepts multiple
    # statements and leaves the '%' in PL/pgSQL RAISE formats alone.
    with op.get_bind().connection.dbapi_connection.cursor() as cursor:
        cursor.execute(sql)
