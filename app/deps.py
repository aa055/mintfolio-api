"""FastAPI dependencies — auth, db session, etc."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.services.jwt_verifier import JWTVerificationError, verify_supabase_jwt


class CurrentUser(BaseModel):
    id: str  # Supabase user UUID (the `sub` claim)
    email: str | None = None


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Verify a Supabase access token and return the current user.

    Frontend sends `Authorization: Bearer <supabase_access_token>`.
    Verification is JWKS-based (ES256/RS256 for modern Supabase projects,
    HS256 with the shared JWT_SECRET for legacy ones).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.split(" ", 1)[1]

    try:
        payload = await verify_supabase_jwt(token)
    except JWTVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    return CurrentUser(id=user_id, email=payload.get("email"))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
