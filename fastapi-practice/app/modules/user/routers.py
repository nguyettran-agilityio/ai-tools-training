# Third-party
from fastapi import APIRouter, Depends, Response, status

# Local application
# core
from app.core.deps import get_auth_service, get_bearer_token, get_current_user, rate_limit_auth
from app.core.security import decode_access_token

# user
from app.modules.user.schemas import LoginRequest, TokenResponse, UserCreate, UserRead
from app.modules.user.services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserRead)
def register(
    data: UserCreate,
    _rate_limit: None = Depends(rate_limit_auth),
    service: AuthService = Depends(get_auth_service),
) -> UserRead:
    return service.register(data)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    _rate_limit: None = Depends(rate_limit_auth),
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    token = service.login(data)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    token: str = Depends(get_bearer_token),
    _current_user: UserRead = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    # `get_current_user` (via `get_bearer_token`) already validated the token
    # is present, unexpired, not denylisted, and belongs to an active user —
    # decoding again here (cheap; pure `jwt.decode`) is simpler than a
    # dependency that hands back both the user and the raw payload.
    payload = decode_access_token(token)
    service.logout(payload)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead)
def me(current_user: UserRead = Depends(get_current_user)) -> UserRead:
    return current_user
