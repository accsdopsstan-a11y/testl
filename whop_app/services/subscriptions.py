"""
Subscription service for Whop embedded app.

Handles subscription and membership status checks.
Uses local SQLite database for subscription management.
Falls back to Whop API when needed.

Key concepts:
- Subscription: Local record of user's subscription status
- Plan: Available subscription tiers (Free, Pro, etc.)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.config import settings
from core.database import get_db_session
from core.models import Plan, Subscription, SubscriptionStatus, User

logger = logging.getLogger(__name__)


class MembershipStatus(str, Enum):
    """
    Whop membership status values (for compatibility).
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
    Information about a user's membership/subscription.

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
    plan_name: Optional[str] = None


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

    Checks local database for active subscription.

    Args:
        user_id: Whop user ID
        product_id: Optional - check access to specific product (ignored for now)
        experience_id: Optional - check access to specific experience (ignored for now)

    Returns:
        bool: True if user has valid access
    """
    try:
        async with get_db_session() as session:
            # Get user with subscriptions
            result = await session.execute(
                select(User)
                .where(User.whop_user_id == user_id)
                .options(selectinload(User.subscriptions))
            )
            db_user = result.scalar_one_or_none()

            if db_user is None:
                logger.debug(f"User {user_id} not found in database")
                return False

            # Check for active subscription
            for sub in db_user.subscriptions:
                if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
                    # Check expiration
                    if sub.expires_at is None or sub.expires_at > datetime.utcnow():
                        return True

            return False

    except Exception as e:
        logger.error(f"Error checking user access: {e}")
        return False


async def get_user_membership(user_id: str) -> Optional[MembershipInfo]:
    """
    Get detailed membership/subscription information for a user.

    Args:
        user_id: Whop user ID

    Returns:
        Optional[MembershipInfo]: Subscription details or None if no active subscription
    """
    try:
        async with get_db_session() as session:
            # Get user with subscriptions and plans
            result = await session.execute(
                select(User)
                .where(User.whop_user_id == user_id)
                .options(
                    selectinload(User.subscriptions).selectinload(Subscription.plan)
                )
            )
            db_user = result.scalar_one_or_none()

            if db_user is None:
                return None

            # Find first active subscription
            for sub in db_user.subscriptions:
                if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
                    # Check expiration
                    if sub.expires_at is None or sub.expires_at > datetime.utcnow():
                        return _subscription_to_membership_info(sub, user_id)

            return None

    except Exception as e:
        logger.error(f"Error getting membership: {e}")
        return None


async def get_membership_by_id(membership_id: str) -> Optional[MembershipInfo]:
    """
    Get subscription by its ID.

    Args:
        membership_id: Subscription ID (local or Whop)

    Returns:
        Optional[MembershipInfo]: Subscription details or None if not found
    """
    try:
        async with get_db_session() as session:
            # Try to parse as integer (local ID)
            try:
                sub_id = int(membership_id)
                result = await session.execute(
                    select(Subscription)
                    .where(Subscription.id == sub_id)
                    .options(selectinload(Subscription.plan), selectinload(Subscription.user))
                )
            except ValueError:
                # Whop membership ID format (mem_xxxx)
                result = await session.execute(
                    select(Subscription)
                    .where(Subscription.whop_membership_id == membership_id)
                    .options(selectinload(Subscription.plan), selectinload(Subscription.user))
                )

            sub = result.scalar_one_or_none()

            if sub is None:
                return None

            return _subscription_to_membership_info(sub, sub.user.whop_user_id)

    except Exception as e:
        logger.error(f"Error getting membership by ID: {e}")
        return None


async def sync_membership_status(membership_id: str) -> Optional[MembershipInfo]:
    """
    Synchronize/refresh subscription status.

    Args:
        membership_id: Subscription ID

    Returns:
        Optional[MembershipInfo]: Updated subscription info
    """
    return await get_membership_by_id(membership_id)


async def activate_subscription(
    user_id: str,
    plan_slug: str = "free",
    whop_membership_id: Optional[str] = None,
) -> Optional[Subscription]:
    """
    Activate a subscription for user.

    Used by webhook handler when payment is confirmed.

    Args:
        user_id: Whop user ID
        plan_slug: Plan to activate
        whop_membership_id: Optional Whop membership ID

    Returns:
        Optional[Subscription]: Created/updated subscription
    """
    try:
        async with get_db_session() as session:
            # Get or create user
            result = await session.execute(
                select(User).where(User.whop_user_id == user_id)
            )
            db_user = result.scalar_one_or_none()

            if db_user is None:
                db_user = User(whop_user_id=user_id)
                session.add(db_user)
                await session.flush()

            # Get plan
            result = await session.execute(
                select(Plan).where(Plan.slug == plan_slug)
            )
            plan = result.scalar_one_or_none()

            if plan is None:
                logger.error(f"Plan {plan_slug} not found")
                return None

            # Create subscription
            subscription = Subscription(
                user_id=db_user.id,
                plan_id=plan.id,
                whop_membership_id=whop_membership_id,
                status=SubscriptionStatus.ACTIVE,
                started_at=datetime.utcnow(),
                expires_at=None,  # Free plans don't expire
            )
            session.add(subscription)
            await session.commit()

            logger.info(f"Activated subscription for user {user_id}, plan {plan_slug}")
            return subscription

    except Exception as e:
        logger.error(f"Error activating subscription: {e}")
        return None


async def cancel_subscription_by_whop_id(whop_membership_id: str) -> bool:
    """
    Cancel subscription by Whop membership ID.

    Used by webhook handler when subscription is canceled.

    Args:
        whop_membership_id: Whop membership ID

    Returns:
        bool: True if canceled successfully
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.whop_membership_id == whop_membership_id
                )
            )
            subscription = result.scalar_one_or_none()

            if subscription is None:
                logger.warning(f"Subscription not found: {whop_membership_id}")
                return False

            subscription.status = SubscriptionStatus.CANCELED
            subscription.canceled_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Canceled subscription: {whop_membership_id}")
            return True

    except Exception as e:
        logger.error(f"Error canceling subscription: {e}")
        return False


def _subscription_to_membership_info(sub: Subscription, user_id: str) -> MembershipInfo:
    """Convert local Subscription to MembershipInfo."""
    status_map = {
        SubscriptionStatus.ACTIVE: MembershipStatus.ACTIVE,
        SubscriptionStatus.TRIAL: MembershipStatus.TRIALING,
        SubscriptionStatus.CANCELED: MembershipStatus.CANCELED,
        SubscriptionStatus.EXPIRED: MembershipStatus.EXPIRED,
        SubscriptionStatus.PENDING: MembershipStatus.UNRESOLVED,
    }

    return MembershipInfo(
        membership_id=str(sub.id),
        user_id=user_id,
        product_id=sub.plan.slug if sub.plan else "",
        status=status_map.get(sub.status, MembershipStatus.UNRESOLVED),
        valid=sub.is_active,
        cancel_at_period_end=False,
        current_period_end=sub.expires_at,
        renewal_period_days=sub.plan.billing_period_days if sub.plan else None,
        plan_id=str(sub.plan_id),
        plan_name=sub.plan.name if sub.plan else None,
    )
