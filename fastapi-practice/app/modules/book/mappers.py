"""Book mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Local application
# book
from app.modules.book.models import Book
from app.modules.book.schemas import BookRead


def to_book_read(book: Book) -> BookRead:
    # `BookRead.status` is a @computed_field derived from available_copies,
    # so model_validate (from_attributes) picks it up automatically.
    return BookRead.model_validate(book)
