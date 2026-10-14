"""SQLModel-backed concrete `CategoryRepositoryInterface` — the only file in
this module allowed to import `Category` or `sqlmodel` itself.
"""

# Third-party
from sqlmodel import select

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend

# category
from app.modules.category.mappers import to_category_read
from app.modules.category.models import Category
from app.modules.category.repositories import CategoryRepositoryInterface, CategoryUpdateFields
from app.modules.category.schemas import CategoryRead


class CategoryRepository(CategoryRepositoryInterface):
    # Narrows the inherited `backend: CrudBackend[Any, ReadT, UpdateT]` to the
    # concrete SQLModel type for this file only, so mypy knows
    # `self.backend.session` exists here without leaking that knowledge
    # into the ORM-agnostic interface.
    backend: SQLModelBackend[Category, CategoryRead, CategoryUpdateFields]

    def get_by_name(self, name: str) -> CategoryRead | None:
        category = self.backend.session.exec(select(Category).where(Category.name == name)).first()
        return to_category_read(category) if category is not None else None
