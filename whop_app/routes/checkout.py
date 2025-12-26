"""
Checkout API for subscription management.

Provides API endpoints for:
- Getting available plans (public)
- Subscribing to a plan (authenticated)
- Managing subscriptions (authenticated)
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db
from core.models import Plan, Subscription, SubscriptionStatus, User
from core.whop_auth import WhopUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkout", tags=["checkout"])


class CheckoutRequest(BaseModel):
    """Request body for checkout."""

    plan_slug: str


class CheckoutResponse(BaseModel):
    """Response for successful checkout."""

    success: bool
    message: str
    subscription_id: Optional[int] = None
    plan_name: Optional[str] = None


@router.get("/plans")
async def get_available_plans(
    db: AsyncSession = Depends(get_db),
):
    """
    Get list of available subscription plans.

    This endpoint is PUBLIC - no authentication required.
    Returns all active plans with pricing info.
    """
    result = await db.execute(
        select(Plan).where(Plan.is_active == True).order_by(Plan.price)
    )
    plans = result.scalars().all()

    return {
        "plans": [
            {
                "id": plan.id,
                "name": plan.name,
                "slug": plan.slug,
                "price": plan.price,
                "currency": plan.currency,
                "billing_period_days": plan.billing_period_days,
                "description": plan.description,
                "features": plan.features,
            }
            for plan in plans
        ]
    }


@router.post("/subscribe", response_model=CheckoutResponse)
async def subscribe_to_plan(
    request: CheckoutRequest,
    user: WhopUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Subscribe user to a plan.

    For free plans, activates immediately.
    For paid plans, creates pending subscription (payment integration TODO).
    """
    # Find the plan
    result = await db.execute(
        select(Plan).where(Plan.slug == request.plan_slug, Plan.is_active == True)
    )
    plan = result.scalar_one_or_none()

    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{request.plan_slug}' not found",
        )

    # Get or create user
    db_user = await get_or_create_user(db, user)

    # Check if user already has any active subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == db_user.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
        )
    )
    existing_sub = result.scalar_one_or_none()

    if existing_sub:
        # Get plan name for existing subscription
        result = await db.execute(
            select(Plan).where(Plan.id == existing_sub.plan_id)
        )
        existing_plan = result.scalar_one_or_none()

        return CheckoutResponse(
            success=True,
            message=f"You already have an active subscription ({existing_plan.name if existing_plan else 'Unknown'})",
            subscription_id=existing_sub.id,
            plan_name=existing_plan.name if existing_plan else None,
        )

    # For free plans, activate immediately
    if plan.price == 0:
        subscription = Subscription(
            user_id=db_user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            started_at=datetime.utcnow(),
            expires_at=None,  # Free plans don't expire
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

        logger.info(f"User {user.user_id} subscribed to free plan: {plan.name}")

        return CheckoutResponse(
            success=True,
            message=f"Successfully subscribed to {plan.name}!",
            subscription_id=subscription.id,
            plan_name=plan.name,
        )

    # For paid plans, create pending subscription
    # TODO: Integrate with Whop checkout API for payment
    # https://dev.whop.com/api-reference/v5/checkouts/create
    subscription = Subscription(
        user_id=db_user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.PENDING,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    logger.info(f"User {user.user_id} created pending subscription for: {plan.name}")

    return CheckoutResponse(
        success=True,
        message=f"Subscription created. Payment required for {plan.name}.",
        subscription_id=subscription.id,
        plan_name=plan.name,
    )


@router.get("/my-subscription")
async def get_my_subscription(
    user: WhopUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current user's subscription status.
    """
    result = await db.execute(
        select(User)
        .where(User.whop_user_id == user.user_id)
        .options(selectinload(User.subscriptions).selectinload(Subscription.plan))
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        return {
            "has_subscription": False,
            "subscriptions": [],
        }

    active_subs = [
        sub for sub in db_user.subscriptions
        if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL)
    ]

    return {
        "has_subscription": len(active_subs) > 0,
        "subscriptions": [
            {
                "id": sub.id,
                "plan_name": sub.plan.name,
                "plan_slug": sub.plan.slug,
                "status": sub.status.value,
                "started_at": sub.started_at.isoformat() if sub.started_at else None,
                "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            }
            for sub in db_user.subscriptions
        ],
    }


@router.post("/cancel/{subscription_id}")
async def cancel_subscription(
    subscription_id: int,
    user: WhopUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a subscription.
    """
    result = await db.execute(
        select(User).where(User.whop_user_id == user.user_id)
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == db_user.id,
        )
    )
    subscription = result.scalar_one_or_none()

    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )

    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = datetime.utcnow()
    await db.commit()

    logger.info(f"User {user.user_id} canceled subscription {subscription_id}")

    return {"success": True, "message": "Subscription canceled"}


async def get_or_create_user(db: AsyncSession, whop_user: WhopUser) -> User:
    """
    Get existing user or create new one.

    Args:
        db: Database session
        whop_user: Authenticated Whop user

    Returns:
        User: Database user record
    """
    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user.user_id)
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        db_user = User(
            whop_user_id=whop_user.user_id,
            email=whop_user.email,
            username=whop_user.username,
            profile_pic_url=whop_user.profile_pic_url,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        logger.info(f"Created new user: {whop_user.user_id}")

    return db_user
