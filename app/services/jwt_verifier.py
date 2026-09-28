"""Supabase JWT verification.

Supports both legacy HS256 projects (using `SUPABASE_JWT_SECRET`) and
modern projects that sign user access tokens with asymmetric keys
(ES256 / RS256) — the latter is the default for any project created in
mid-2024 or later. Public keys are fetched from the JWKS endpoint
`/auth/v1/.well-known/jwks.json` and cached in-process.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import get_settings

# Cache lifetime for the JWKS document. Supabase rotates these keys
# manually, and a fresh fetch happens automatically when a token's kid
# isn't found in the current cache — so an hour is a fine baseline.
JWKS_TTL_SECONDS = 3600

# Algorithms we'll trust if the JWT header says so. Anything outside
# this list gets rejected. Don't add 'none' under any circumstances.
SUPPORTED_ALGORITHMS = {"HS256", "ES256", "RS256"}


class JWTVerificationError(Exception):
    """Raised when a token can't be verified for any reason."""


# Per-process cache + a lock so concurrent first-fetches don't stampede.
_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_jwks_lock = asyncio.Lock()


def _jwks_url() -> str:
    return f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"


async def _fetch_jwks() -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            _jwks_url(),
            headers={"apikey": settings.supabase_anon_key},
        )
        resp.raise_for_status()
        return resp.json()


async def _get_jwks(*, force_refresh: bool = False) -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at

    if (
        not force_refresh
        and _jwks_cache is not None
        and time.time() - _jwks_fetched_at < JWKS_TTL_SECONDS
    ):
        return _jwks_cache

    async with _jwks_lock:
        # Re-check after acquiring the lock — another coroutine may have
        # already refreshed while we waited.
        if (
            not force_refresh
            and _jwks_cache is not None
            and time.time() - _jwks_fetched_at < JWKS_TTL_SECONDS
        ):
            return _jwks_cache
        _jwks_cache = await _fetch_jwks()
        _jwks_fetched_at = time.time()
        return _jwks_cache


def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    keys = jwks.get("keys", [])
    if kid is None:
        # No kid in header — return the sole key if there's only one.
        return keys[0] if len(keys) == 1 else None
    for k in keys:
        if k.get("kid") == kid:
            return k
    return None


async def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify a Supabase access token and return its claims.

    Raises `JWTVerificationError` on any failure (malformed, wrong signature,
    unknown algorithm, expired, wrong audience, missing kid, etc.). Callers
    should turn this into a 401 response.
    """
    settings = get_settings()

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise JWTVerificationError(f"Malformed JWT header: {exc}") from exc

    alg = header.get("alg")
    if alg not in SUPPORTED_ALGORITHMS:
        raise JWTVerificationError(f"Unsupported JWT algorithm: {alg!r}")

    kid = header.get("kid")

    # ---- HS256 path ----
    # Symmetric tokens are signed with the project's shared JWT secret.
    # Supabase may stamp a `kid` on them too, but JWKS never publishes
    # symmetric keys — so the secret is the only thing that can verify them.
    if alg == "HS256":
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except JWTError as exc:
            raise JWTVerificationError(f"HS256 verify failed: {exc}") from exc

    # ---- Asymmetric / JWKS path ----
    jwks = await _get_jwks()
    key = _find_key(jwks, kid)

    if key is None:
        # The kid may be new — force a refresh and try once more.
        jwks = await _get_jwks(force_refresh=True)
        key = _find_key(jwks, kid)

    if key is None:
        raise JWTVerificationError(
            f"No JWKS key found for kid={kid!r} (alg={alg!r})"
        )

    try:
        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience="authenticated",
        )
    except JWTError as exc:
        raise JWTVerificationError(f"{alg} verify failed: {exc}") from exc
