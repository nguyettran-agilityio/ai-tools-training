"""Domain exceptions — plain Python, no `fastapi` dependency. Services and
repositories raise these instead of `HTTPException`; `error_handlers.py`
translates them into HTTP responses.
"""


class AppError(Exception):
    """Base class for all application-level errors: `status_code`, machine-
    readable `code`, client-safe `message`, optional field-level `errors`."""

    status_code: int = 500
    code: str = "INTERNAL_SERVER_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, errors: list | None = None) -> None:
        self.message = message or self.default_message
        self.errors = errors
        super().__init__(self.message)


class BadRequestError(AppError):
    """Raised when the request is malformed or fails a business precondition."""

    status_code = 400
    code = "BAD_REQUEST"
    default_message = "Bad request."


class UnauthorizedError(AppError):
    """Raised when authentication is missing or invalid."""

    status_code = 401
    code = "UNAUTHORIZED"
    default_message = "Authentication required."


class ForbiddenError(AppError):
    """Raised when the authenticated user lacks permission for the action."""

    status_code = 403
    code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    status_code = 404
    code = "NOT_FOUND"
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    """Raised when the request conflicts with the current state of a resource
    (e.g. duplicate creation, deleting a still-referenced record)."""

    status_code = 409
    code = "CONFLICT"
    default_message = "The request conflicts with the current state of the resource."


class AlreadyExistsError(ConflictError):
    """Raised when attempting to create a resource that already exists."""

    default_message = "The resource already exists."


class TooManyRequestsError(AppError):
    """Raised when a client exceeds a rate limit (see `core/rate_limiter.py`)."""

    status_code = 429
    code = "TOO_MANY_REQUESTS"
    default_message = "Too many requests. Please try again later."
