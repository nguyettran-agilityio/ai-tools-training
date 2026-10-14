# Standard library
import uuid

# Third-party
from fastapi import APIRouter, Depends, Query, Response, status

# Local application
# core
from app.core.deps import get_book_service, require_admin
from app.core.schemas import Page, PaginationParams

# book
from app.modules.book.schemas import BookCreate, BookRead, BookUpdate
from app.modules.book.services import BookService

# user
from app.modules.user.schemas import UserRead

router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=Page[BookRead])
def list_all(
    q: str | None = Query(default=None, description="Case-insensitive search over title/author"),
    category_id: uuid.UUID | None = Query(default=None, alias="categoryId"),
    available_only: bool = Query(default=False, alias="availableOnly"),
    pagination: PaginationParams = Depends(PaginationParams),
    service: BookService = Depends(get_book_service),
) -> Page[BookRead]:
    return service.list(q, category_id, available_only, pagination)


@router.get("/{book_id}", response_model=BookRead)
def get(
    book_id: uuid.UUID,
    service: BookService = Depends(get_book_service),
) -> BookRead:
    return service.get(book_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=BookRead)
def create(
    data: BookCreate,
    _current_user: UserRead = Depends(require_admin),
    service: BookService = Depends(get_book_service),
) -> BookRead:
    return service.create(data)


@router.patch("/{book_id}", response_model=BookRead)
def update(
    book_id: uuid.UUID,
    data: BookUpdate,
    _current_user: UserRead = Depends(require_admin),
    service: BookService = Depends(get_book_service),
) -> BookRead:
    return service.update(book_id, data)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    book_id: uuid.UUID,
    _current_user: UserRead = Depends(require_admin),
    service: BookService = Depends(get_book_service),
) -> Response:
    service.delete(book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
