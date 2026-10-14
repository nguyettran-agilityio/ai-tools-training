"""Category mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Local application
# category
from app.modules.category.models import Category
from app.modules.category.schemas import CategoryRead


def to_category_read(category: Category) -> CategoryRead:
    return CategoryRead.model_validate(category)
