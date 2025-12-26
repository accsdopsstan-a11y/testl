"""
Subscription service for Whop embedded app.

Handles subscription and membership status checks via Whop API.

Key concepts in Whop:
- Membership: Represents a user's access to a product (subscription or one-time)
- Membership statuses: trialing, active, past_due, completed, canceled, expired, unresolved
- Valid membership: membership.valid == True means user currently has access

References:
    https://docs.whop.com/api-reference/memberships/retrieve-membership
    https://dev.whop.com/api-reference/v5/apps/access
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class MembershipStatus(str, Enum):
    """
    Whop membership status values.

    From Whop documentation:
    - trialing: User is in trial period
    - active: Active paid subscription
    - past_due: Payment failed, grace period
    - completed: One-time purchase completed (always valid)
    - canceled: Subscription was canceled
    - expired: Subscription/trial has expired
    - unresolved: Needs manual resolution
    """

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    COMPLETED = "completed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    UNRESOLVED = "unresolved"


@dataclass
class MembershipInfo:
    """
    Information about a user's membership.

    Contains all relevant details for access control and display.
    """

    membership_id: str
    user_id: str
    product_id: str
    status: MembershipStatus
    valid: bool  # Whether user currently has access

    # Subscription details
    cancel_at_period_end: bool = False
    current_period_end: Optional[datetime] = None
    renewal_period_days: Optional[int] = None

    # Additional context
    company_id: Optional[str] = None
    experience_id: Optional[str] = None
    plan_id: Optional[str] = None


class SubscriptionError(Exception):
    """Custom exception for subscription-related errors."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def check_user_access(
    user_id: str,
    product_id: Optional[str] = None,
    experience_id: Optional[str] = None,
) -> bool:
    """
    Check if a user has valid access.

    This is the primary access check function. It queries Whop API
    to determine if the user has any valid membership.

    Args:
        user_id: Whop user ID
        product_id: Optional - check access to specific product
        experience_id: Optional - check access to specific experience

    Returns:
        bool: True if user has valid access

    NOTE: The exact endpoint depends on your app setup.
    For App API keys, use the hasAccess endpoint.
    For Company API keys, query memberships directly.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Build query params for filtering
            params = {"user_id": user_id, "valid": "true"}

            if product_id:
                params["product_id"] = product_id

            if experience_id:
                params["experience_id"] = experience_id

            # Query memberships to check access
            # NOTE: Endpoint may vary - verify with Whop API docs
            response = await client.get(
                f"{settings.WHOP_API_BASE_URL}/memberships",
                headers={"Authorization": f"Bearer {settings.WHOP_API_KEY}"},
                params=params,
                timeout=5.0,
            )

            if response.status_code != 200:
                logger.error(f"Failed to check access: {response.status_code}")
                return False

            data = response.json()

            # Check if any valid memberships exist
            # API response structure: {"data": [...], "pagination": {...}}
            memberships = data.get("data", [])
            return len(memberships) > 0

        except Exception as e:
            logger.error(f"Error checking user access: {e}")
            # Fail closed - deny access on error
            return False


async def get_user_membership(user_id: str) -> Optional[MembershipInfo]:
    """
    Get detailed membership information for a user.

    Retrieves the first valid membership for the user.
    For users with multiple memberships, consider using get_all_memberships().

    Args:
        user_id: Whop user ID

    Returns:
        Optional[MembershipInfo]: Membership details or None if no valid membership
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.WHOP_API_BASE_URL}/memberships",
                headers={"Authorization": f"Bearer {settings.WHOP_API_KEY}"},
                params={"user_id": user_id, "valid": "true"},
                timeout=5.0,
            )

            if response.status_code != 200:
                logger.error(f"Failed to get membership: {response.status_code}")
                return None

            data = response.json()
            memberships = data.get("data", [])

            if not memberships:
                return None

            # Return first valid membership
            mem = memberships[0]
            return _parse_membership(mem)

        except Exception as e:
            logger.error(f"Error getting membership: {e}")
            return None


async def get_membership_by_id(membership_id: str) -> Optional[MembershipInfo]:
    """
    Get membership by its ID.

    Args:
        membership_id: Whop membership ID (format: mem_xxxxx)

    Returns:
        Optional[MembershipInfo]: Membership details or None if not found
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{settings.WHOP_API_BASE_URL}/memberships/{membership_id}",
                headers={"Authorization": f"Bearer {settings.WHOP_API_KEY}"},
                timeout=5.0,
            )

            if response.status_code == 404:
                return None

            if response.status_code != 200:
                logger.error(f"Failed to get membership: {response.status_code}")
                return None

            return _parse_membership(response.json())

        except Exception as e:
            logger.error(f"Error getting membership by ID: {e}")
            return None


async def sync_membership_status(membership_id: str) -> Optional[MembershipInfo]:
    """
    Synchronize membership status from Whop.

    Use this to refresh local cache after webhook events
    or when you need the most current status.

    Args:
        membership_id: Whop membership ID

    Returns:
        Optional[MembershipInfo]: Updated membership info
    """
    # For now, just fetch fresh data
    # In production, you might want to update local database cache here
    return await get_membership_by_id(membership_id)


def _parse_membership(data: dict) -> MembershipInfo:
    """
    Parse membership data from Whop API response.

    Args:
        data: Raw membership data from API

    Returns:
        MembershipInfo: Parsed membership object

    NOTE: Field names based on Whop API documentation.
    Verify and adjust based on actual API response structure.
    """
    # Parse renewal period end if present
    current_period_end = None
    if data.get("renewal_period_end"):
        try:
            # Whop uses Unix timestamps in seconds
            current_period_end = datetime.fromtimestamp(data["renewal_period_end"])
        except (ValueError, TypeError):
            pass

    return MembershipInfo(
        membership_id=data.get("id", ""),
        user_id=data.get("user_id", ""),
        product_id=data.get("product_id", ""),
        status=MembershipStatus(data.get("status", "unresolved")),
        valid=data.get("valid", False),
        cancel_at_period_end=data.get("cancel_at_period_end", False),
        current_period_end=current_period_end,
        renewal_period_days=data.get("renewal_period_days"),
        company_id=data.get("company_id"),
        experience_id=data.get("experience_id"),
        plan_id=data.get("plan_id"),
    )
