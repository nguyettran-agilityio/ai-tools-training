# Standard library
import uuid

# Third-party
from fastapi import APIRouter, Depends, Query, Response, status

# Local application
# core
from app.core.deps import get_user_service, require_admin
from app.core.schemas import Page, PaginationParams

# user
from app.modules.user.enums import UserRole
from app.modules.user.schemas import AdminUserCreate, UserRead, UserUpdate
from app.modules.user.services import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead])
def list_all(
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None, alias="isActive"),
    pagination: PaginationParams = Depends(PaginationParams),
    _current_user: UserRead = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> Page[UserRead]:
    return service.list(role, is_active, pagination)


@router.get("/{user_id}", response_model=UserRead)
def get(
    user_id: uuid.UUID,
    _current_user: UserRead = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    return service.get(user_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
def create(
    data: AdminUserCreate,
    _current_user: UserRead = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    return service.create(data, role=data.role)


@router.patch("/{user_id}", response_model=UserRead)
def update(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: UserRead = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    return service.update(user_id, data, acting_user_id=current_user.id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    user_id: uuid.UUID,
    current_user: UserRead = Depends(require_admin),
    service: UserService = Depends(get_user_service),
) -> Response:
    service.delete(user_id, acting_user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
