"""Standard API error shape: {code, message, errors}. Success responses
have no envelope — routers return the schema object directly (via
`response_model`) and rely on the HTTP status code; errors rely on the
HTTP status code too (set on the response itself), so the body doesn't
repeat it — only `code`/`message`/`errors` are built globally by
`error_handlers.py`.
"""

# Third-party
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str
    errors: list | None = None
