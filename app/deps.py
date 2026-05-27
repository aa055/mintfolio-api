"""FastAPI dependencies — auth, db session, etc.

Stubs only for Phase 1 scaffold. Real implementation lands when we wire
up the first authenticated endpoint.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings


class CurrentUser(BaseModel):
    id: str  # Supabase user UUID
    email: str | None = None


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Verify a Supabase access token and return the current user.

    Frontend should send `Authorization: Bearer <supabase_access_token>`.
    The JWT is signed with the project's JWT secret (HS256).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.split(" ", 1)[1]
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    return CurrentUser(id=user_id, email=payload.get("email"))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
