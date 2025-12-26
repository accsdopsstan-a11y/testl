"""
Whop authentication module.

Handles user authentication for the embedded app using Whop's token system.

According to Whop docs:
- Embedded apps receive JWT token in `x-whop-user-token` header
- The token is automatically included by Whop iframe for same-origin requests
- Token contains user_id and can be validated via Whop API
- In dev mode, token comes as `whop-dev-user-token` query parameter

References:
    https://docs.whop.com/developer/guides/authentication
"""

import base64
import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException, Request, status

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WhopUser:
    """
    Authenticated Whop user.

    Represents a user that has been validated through Whop's authentication system.
    """

    user_id: str
    # Additional fields that may be returned by Whop API
    # NOTE: Exact fields depend on Whop API response - check docs for updates
    email: Optional[str] = None
    username: Optional[str] = None
    profile_pic_url: Optional[str] = None

    # Membership context (if available)
    membership_id: Optional[str] = None
    company_id: Optional[str] = None
    experience_id: Optional[str] = None


class WhopAuthError(Exception):
    """Custom exception for authentication errors."""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def decode_jwt_payload(token: str) -> Optional[dict]:
    """
    Decode JWT payload without verification.

    Used for dev tokens where we trust the source (Whop dev proxy).
    In production, tokens should be validated via Whop API.

    Args:
        token: JWT token string

    Returns:
        Optional[dict]: Decoded payload or None if invalid
    """
    try:
        # JWT format: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (second part)
        payload = parts[1]
        # Add padding if needed
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Failed to decode JWT: {e}")
        return None


def is_dev_token(token: str) -> bool:
    """
    Check if token is a Whop dev token.

    Dev tokens have `isDev: true` in their payload and are issued
    by Whop's experience proxy for local development.

    Args:
        token: JWT token string

    Returns:
        bool: True if this is a dev token
    """
    payload = decode_jwt_payload(token)
    if payload is None:
        return False
    return payload.get("isDev", False) is True


async def validate_token_with_whop(token: str) -> dict:
    """
    Validate token with Whop API.

    Makes an authenticated request to Whop API to validate the user token
    and retrieve user information.

    Args:
        token: JWT token from x-whop-user-token header

    Returns:
        dict: User data from Whop API

    Raises:
        WhopAuthError: If token validation fails

    NOTE: The exact endpoint for token validation may vary.
    According to docs, you can use the SDK's validateToken method,
    or make a request to /me endpoint with the user token.
    Update this endpoint based on actual Whop API documentation.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Using /me endpoint to validate token and get user info
            # The user token should be passed to get the current user's details
            # NOTE: Verify this endpoint with official Whop API docs
            response = await client.get(
                f"{settings.WHOP_API_BASE_URL}/me",
                headers={
                    "Authorization": f"Bearer {settings.WHOP_API_KEY}",
                    # Pass user token for user context
                    "x-whop-user-token": token,
                },
                timeout=5.0,
            )

            if response.status_code == 401:
                raise WhopAuthError("Invalid or expired token", 401)

            if response.status_code == 403:
                raise WhopAuthError("Access forbidden", 403)

            if response.status_code != 200:
                logger.error(f"Whop API error: {response.status_code} - {response.text}")
                raise WhopAuthError(
                    f"Whop API error: {response.status_code}",
                    response.status_code,
                )

            return response.json()

        except httpx.TimeoutException:
            logger.error("Timeout while validating token with Whop API")
            raise WhopAuthError("Authentication service timeout", 503)

        except httpx.RequestError as e:
            logger.error(f"Request error during token validation: {e}")
            raise WhopAuthError("Authentication service unavailable", 503)


def extract_token_from_request(request: Request) -> Optional[str]:
    """
    Extract authentication token from request.

    Token extraction priority:
    1. x-whop-user-token header (production - from Whop iframe)
    2. Authorization: Bearer header (alternative method)
    3. Query parameter 'whop-dev-user-token' (Whop dev mode)
    4. Query parameter 'token' (legacy dev mode)

    Args:
        request: FastAPI request object

    Returns:
        Optional[str]: Extracted token or None if not found
    """
    # Primary method: Whop iframe passes token in this header
    whop_token = request.headers.get("x-whop-user-token")
    if whop_token:
        return whop_token

    # Alternative: Standard Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix

    # Whop dev mode: Token passed as query parameter
    # This is used when testing embedded apps locally
    dev_token = request.query_params.get("whop-dev-user-token")
    if dev_token:
        logger.info("Using whop-dev-user-token from query params")
        return dev_token

    # Legacy dev mode: Accept token from query params
    if settings.DEV_MODE:
        query_token = request.query_params.get("token")
        if query_token:
            logger.warning("Using token from query params (DEV_MODE only)")
            return query_token

    return None


async def get_current_user(request: Request) -> WhopUser:
    """
    Get and validate current user from request.

    This is the main authentication function to use in route dependencies.
    It extracts the token, validates it with Whop API, and returns user info.

    For dev tokens (isDev=true), the token is decoded locally without API call.
    For production tokens, the token is validated via Whop API.

    Args:
        request: FastAPI request object

    Returns:
        WhopUser: Authenticated user object

    Raises:
        HTTPException: 401 if authentication fails
    """
    token = extract_token_from_request(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Whop user token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Check if this is a dev token - can be decoded locally
        if is_dev_token(token):
            payload = decode_jwt_payload(token)
            if payload is None:
                raise WhopAuthError("Invalid dev token", 401)

            logger.info(f"Authenticated dev user: {payload.get('sub')}")

            # Dev token payload structure:
            # {
            #   "isDev": true,
            #   "sub": "user_xxxxx",  # user ID
            #   "aud": "app_xxxxx",   # app ID
            #   "iss": "urn:whopcom:exp-proxy",
            #   "iat": ..., "exp": ...
            # }
            return WhopUser(
                user_id=payload.get("sub", ""),
                # Dev tokens don't include email/username, only user ID
                email=None,
                username=None,
                profile_pic_url=None,
                membership_id=None,
                company_id=None,
                experience_id=None,
            )

        # Production token - validate via Whop API
        user_data = await validate_token_with_whop(token)

        # Build WhopUser from API response
        # NOTE: Field names depend on actual Whop API response structure
        # Update these field mappings based on actual API docs
        return WhopUser(
            user_id=user_data.get("id", user_data.get("user_id", "")),
            email=user_data.get("email"),
            username=user_data.get("username"),
            profile_pic_url=user_data.get("profile_pic_url"),
            membership_id=user_data.get("membership_id"),
            company_id=user_data.get("company_id"),
            experience_id=user_data.get("experience_id"),
        )

    except WhopAuthError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_user(request: Request) -> Optional[WhopUser]:
    """
    Get current user if authenticated, None otherwise.

    Use this for routes that work both with and without authentication.

    Args:
        request: FastAPI request object

    Returns:
        Optional[WhopUser]: User if authenticated, None otherwise
    """
    try:
        return await get_current_user(request)
    except HTTPException:
        return None
