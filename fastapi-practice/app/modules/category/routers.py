# Standard library
import uuid

# Third-party
from fastapi import APIRouter, Depends, Response, status

# Local application
# core
from app.core.deps import get_category_service, require_admin
from app.core.schemas import Page, PaginationParams

# category
from app.modules.category.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.modules.category.services import CategoryService

# user
from app.modules.user.schemas import UserRead

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=Page[CategoryRead])
def list_all(
    pagination: PaginationParams = Depends(PaginationParams),
    service: CategoryService = Depends(get_category_service),
) -> Page[CategoryRead]:
    return service.list(pagination)


@router.get("/{category_id}", response_model=CategoryRead)
def get(
    category_id: uuid.UUID,
    service: CategoryService = Depends(get_category_service),
) -> CategoryRead:
    return service.get(category_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CategoryRead)
def create(
    data: CategoryCreate,
    _current_user: UserRead = Depends(require_admin),
    service: CategoryService = Depends(get_category_service),
) -> CategoryRead:
    return service.create(data)


@router.patch("/{category_id}", response_model=CategoryRead)
def update(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    _current_user: UserRead = Depends(require_admin),
    service: CategoryService = Depends(get_category_service),
) -> CategoryRead:
    return service.update(category_id, data)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    category_id: uuid.UUID,
    _current_user: UserRead = Depends(require_admin),
    service: CategoryService = Depends(get_category_service),
) -> Response:
    service.delete(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
