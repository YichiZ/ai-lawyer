import os
from pathlib import Path

import psycopg
import pytest

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
ADMIN_URL = os.environ.get("DATABASE_ADMIN_URL", "postgresql://postgres:dev@localhost:5432/postgres")
TEST_DB = "ai_lawyer_test"
TEST_URL = os.environ.get("TEST_DATABASE_URL", f"postgresql://postgres:dev@localhost:5432/{TEST_DB}")


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())


@pytest.fixture(scope="session")
def test_db() -> str:
    """Fresh test database with the schema applied once."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        apply_schema(conn)
    return TEST_URL


@pytest.fixture
def conn(test_db):
    """Per-test connection; everything rolls back afterwards."""
    with psycopg.connect(test_db) as c:
        yield c
        c.rollback()
