"""
User service for Whop embedded app.

Handles user-related operations including profile management
and user data retrieval from Whop API.

In Whop's system:
- Users are global across all companies
- Users can have memberships to multiple products/companies
- User ID format: user_xxxxx
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from core.config import settings
from core.whop_auth import WhopUser

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """
    Extended user profile with additional details.

    Contains more information than basic WhopUser auth object.
    """

    user_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    profile_pic_url: Optional[str] = None

    # Social links (if provided by user)
    twitter: Optional[str] = None
    discord: Optional[str] = None
    instagram: Optional[str] = None

    # Custom app-specific data (stored in local DB if configured)
    custom_data: dict = field(default_factory=dict)


class UserServiceError(Exception):
    """Custom exception for user service errors."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def get_user_profile(user_id: str) -> Optional[UserProfile]:
    """
    Get detailed user profile from Whop.

    Fetches user information including profile details and social links.

    Args:
        user_id: Whop user ID

    Returns:
        Optional[UserProfile]: User profile or None if not found
    """
    async with httpx.AsyncClient() as client:
        try:
            # NOTE: Verify exact endpoint with Whop API documentation
            response = await client.get(
                f"{settings.WHOP_API_BASE_URL}/users/{user_id}",
                headers={"Authorization": f"Bearer {settings.WHOP_API_KEY}"},
                timeout=5.0,
            )

            if response.status_code == 404:
                return None

            if response.status_code != 200:
                logger.error(f"Failed to get user profile: {response.status_code}")
                return None

            data = response.json()
            return _parse_user_profile(data)

        except Exception as e:
            logger.error(f"Error getting user profile: {e}")
            return None


async def get_current_user_profile(whop_user: WhopUser) -> UserProfile:
    """
    Get profile for currently authenticated user.

    Uses the authenticated user context to fetch their full profile.

    Args:
        whop_user: Authenticated user from request

    Returns:
        UserProfile: Full user profile

    Raises:
        UserServiceError: If profile cannot be retrieved
    """
    profile = await get_user_profile(whop_user.user_id)

    if profile is None:
        # Create minimal profile from auth data
        return UserProfile(
            user_id=whop_user.user_id,
            email=whop_user.email,
            username=whop_user.username,
            profile_pic_url=whop_user.profile_pic_url,
        )

    return profile


async def update_user_custom_data(user_id: str, data: dict) -> bool:
    """
    Update custom app-specific data for a user.

    This data is stored locally (requires database) and is not
    sent to Whop. Use for app-specific preferences, settings, etc.

    Args:
        user_id: Whop user ID
        data: Custom data dictionary to merge with existing

    Returns:
        bool: True if update successful

    NOTE: Requires database to be configured.
    """
    from core.database import get_db_session, is_database_configured

    if not is_database_configured():
        logger.warning("Database not configured, cannot store custom user data")
        return False

    # Implementation depends on your database schema
    # This is a placeholder showing the pattern
    try:
        async with get_db_session() as session:
            # TODO: Implement actual database update
            # Example with a User model:
            # user = await session.get(UserModel, user_id)
            # if user:
            #     user.custom_data = {**user.custom_data, **data}
            #     await session.commit()
            pass

        return True

    except Exception as e:
        logger.error(f"Error updating user custom data: {e}")
        return False


async def on_user_first_seen(user_id: str, membership_id: Optional[str] = None) -> None:
    """
    Handle first-time user event.

    Called when a user accesses the app for the first time.
    Use for:
    - Creating local user record
    - Sending welcome notification
    - Initializing default settings

    Args:
        user_id: Whop user ID
        membership_id: Optional membership ID that granted access
    """
    logger.info(f"First-time user access: {user_id}, membership: {membership_id}")

    # Placeholder for first-time user logic
    # Example actions:
    # - Create user record in database
    # - Initialize default preferences
    # - Trigger welcome email via external service
    pass


def _parse_user_profile(data: dict) -> UserProfile:
    """
    Parse user profile from Whop API response.

    Args:
        data: Raw user data from API

    Returns:
        UserProfile: Parsed profile object

    NOTE: Adjust field mappings based on actual Whop API response.
    """
    return UserProfile(
        user_id=data.get("id", data.get("user_id", "")),
        email=data.get("email"),
        username=data.get("username"),
        profile_pic_url=data.get("profile_pic_url"),
        twitter=data.get("twitter"),
        discord=data.get("discord"),
        instagram=data.get("instagram"),
    )
