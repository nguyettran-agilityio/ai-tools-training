"""Tests for app.core.schemas — CamelModel/PaginationParams/Page base classes.
No DB involved. Per-module schema shape/computed-field tests live in each
module's own `tests/modules/<name>/test_schemas.py`.
"""

import pytest
from pydantic import ValidationError

from app.core.schemas import PaginationParams


class TestPaginationParams:
    def test_rejects_page_zero(self):
        with pytest.raises(ValidationError):
            PaginationParams(page=0)

    def test_rejects_page_size_over_100(self):
        with pytest.raises(ValidationError):
            PaginationParams(page_size=101)

    def test_accepts_defaults(self):
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 10
