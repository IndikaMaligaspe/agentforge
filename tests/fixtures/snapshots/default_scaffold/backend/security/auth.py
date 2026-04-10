"""
API key authentication dependency for FastAPI routes.

Usage
-----
Set the environment variable ``API_SECRET_KEY`` to a strong random secret.
Clients must include the header ``X-API-Key: <key>`` in every request.

If ``API_SECRET_KEY`` is **not** set the server falls back to an open/dev
mode and logs a warning on every request — suitable for local development only.

Example
-------
.. code-block:: python

    from fastapi import Depends
    from security.auth import get_api_key

    @app.post("/query")
    def handle_query(req: QueryRequest, _key: str = Depends(get_api_key)):
        ...
"""
import os
import secrets
import logging
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from observability.logging import get_logger

logger = get_logger(__name__)

# The HTTP header name clients must use to pass the API key
_API_KEY_HEADER_NAME = "X-API-Key"
_api_key_header = APIKeyHeader(name=_API_KEY_HEADER_NAME, auto_error=False)


def get_api_key(api_key: str = Security(_api_key_header)) -> str:
    """
    FastAPI dependency that validates the ``X-API-Key`` request header.

    Parameters
    ----------
    api_key:
        Value extracted from the ``X-API-Key`` header by FastAPI's
        ``APIKeyHeader`` security scheme (``None`` if absent).

    Returns
    -------
    str
        The validated key, or ``"dev-mode"`` when auth is disabled.

    Raises
    ------
    HTTPException
        ``401 Unauthorized`` when the key is missing or does not match.
    """
    expected_key = os.getenv("API_SECRET_KEY", "").strip()

    if not expected_key:
        # No key configured — allow all traffic in development mode
        logger.warning(
            "API_SECRET_KEY is not configured. "
            "The API is running without authentication. "
            "Set this environment variable before deploying to production."
        )
        return "dev-mode"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Supply the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Constant-time comparison to prevent timing-oracle attacks
    if not secrets.compare_digest(
        api_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key
