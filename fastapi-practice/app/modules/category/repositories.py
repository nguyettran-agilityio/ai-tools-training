"""Category repository interface — zero ORM imports. Concrete implementation
lives in `repositories_sqlmodel.py`; services depend only on this interface.
"""

# Standard library
import abc
from typing import TypedDict

# Local application
# core
from app.core.repository_interface import CrudRepositoryInterface

# category
from app.modules.category.schemas import CategoryRead


class CategoryUpdateFields(TypedDict, total=False):
    """Every field `update()` may be asked to change — mirrors `CategoryUpdate`
    exactly (category has no service-computed fields beyond what the client sends)."""

    name: str
    description: str | None


class CategoryRepositoryInterface(CrudRepositoryInterface[CategoryRead, CategoryUpdateFields]):
    @abc.abstractmethod
    def get_by_name(self, name: str) -> CategoryRead | None: ...
