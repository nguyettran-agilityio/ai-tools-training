"""Category schema validation tests. No DB involved."""

import pytest
from pydantic import ValidationError

from app.modules.category.schemas import CategoryCreate, CategoryUpdate


class TestCategorySchemas:
    def test_create_strips_and_rejects_whitespace_only_name(self):
        category = CategoryCreate(name="  Fiction  ")
        assert category.name == "Fiction"

        with pytest.raises(ValidationError):
            CategoryCreate(name="   ")

    def test_update_strips_and_rejects_whitespace_only_name(self):
        category = CategoryUpdate(name="  Fiction  ")
        assert category.name == "Fiction"

        with pytest.raises(ValidationError):
            CategoryUpdate(name="   ")

    def test_update_allows_name_untouched(self):
        # Omitting name (e.g. updating only description) must not be
        # coerced or rejected — None means "leave it alone".
        category = CategoryUpdate(description="New description")
        assert category.name is None
