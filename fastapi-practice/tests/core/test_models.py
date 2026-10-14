"""Smoke test that every module's models.py registers on SQLModel.metadata.
Per-module round-trip/constraint tests live in each module's own
`tests/modules/<name>/test_models.py`.
"""

from sqlmodel import SQLModel

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)


class TestTableCreation:
    def test_all_tables_are_created(self, db_engine):
        table_names = set(SQLModel.metadata.tables.keys())
        assert {"user", "category", "book", "borrowing", "reservation"} <= table_names
