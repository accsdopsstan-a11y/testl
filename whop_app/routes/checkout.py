"""
Checkout route for subscription management.

Handles:
- Displaying available plans
- Processing checkout (subscribing to a plan)
- Managing user subscriptions
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
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
    For paid plans, would redirect to payment (TODO).
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

    # Check if user already has active subscription to this plan
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == db_user.id,
            Subscription.plan_id == plan.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
        )
    )
    existing_sub = result.scalar_one_or_none()

    if existing_sub:
        return CheckoutResponse(
            success=True,
            message="You already have an active subscription to this plan",
            subscription_id=existing_sub.id,
            plan_name=plan.name,
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

    # For paid plans, create pending subscription and redirect to payment
    # TODO: Integrate with Whop checkout or other payment provider
    subscription = Subscription(
        user_id=db_user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.PENDING,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    return CheckoutResponse(
        success=True,
        message=f"Subscription created. Please complete payment for {plan.name}.",
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
    # Get user with subscriptions
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
    # Get user
    result = await db.execute(
        select(User).where(User.whop_user_id == user.user_id)
    )
    db_user = result.scalar_one_or_none()

    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Get subscription
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


@router.get("/", response_class=HTMLResponse)
async def checkout_page(
    request: Request,
    user: WhopUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Render checkout page with available plans.
    """
    # Get plans
    result = await db.execute(
        select(Plan).where(Plan.is_active == True).order_by(Plan.price)
    )
    plans = result.scalars().all()

    # Get user's current subscription
    result = await db.execute(
        select(User)
        .where(User.whop_user_id == user.user_id)
        .options(selectinload(User.subscriptions).selectinload(Subscription.plan))
    )
    db_user = result.scalar_one_or_none()

    current_plan = None
    if db_user:
        for sub in db_user.subscriptions:
            if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
                current_plan = sub.plan.slug
                break

    return HTMLResponse(content=_render_checkout_page(plans, current_plan, user))


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


def _render_checkout_page(plans: list, current_plan: Optional[str], user: WhopUser) -> str:
    """Render checkout page HTML."""
    plans_html = ""
    for plan in plans:
        is_current = plan.slug == current_plan
        button_text = "Current Plan" if is_current else ("Get Started" if plan.price == 0 else f"Subscribe ${plan.price}")
        button_class = "btn-current" if is_current else "btn-subscribe"
        disabled = "disabled" if is_current else ""

        plans_html += f"""
        <div class="plan-card {'current' if is_current else ''}">
            <h3>{plan.name}</h3>
            <div class="price">
                {'Free' if plan.price == 0 else f'${plan.price:.2f}'}
                {f'<span class="period">/ {plan.billing_period_days} days</span>' if plan.billing_period_days > 0 else ''}
            </div>
            <p class="description">{plan.description or ''}</p>
            <button class="{button_class}" onclick="subscribe('{plan.slug}')" {disabled}>
                {button_text}
            </button>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Choose Your Plan</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #fff;
                min-height: 100vh;
                padding: 2rem;
            }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            h1 {{ text-align: center; margin-bottom: 0.5rem; }}
            .subtitle {{ text-align: center; color: rgba(255,255,255,0.6); margin-bottom: 2rem; }}
            .plans {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; }}
            .plan-card {{
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 16px;
                padding: 2rem;
                text-align: center;
                transition: transform 0.2s, border-color 0.2s;
            }}
            .plan-card:hover {{ transform: translateY(-4px); border-color: rgba(74, 222, 128, 0.5); }}
            .plan-card.current {{ border-color: #4ade80; background: rgba(74, 222, 128, 0.1); }}
            .plan-card h3 {{ font-size: 1.5rem; margin-bottom: 1rem; }}
            .price {{ font-size: 2.5rem; font-weight: 700; margin-bottom: 0.5rem; }}
            .period {{ font-size: 0.9rem; color: rgba(255,255,255,0.5); }}
            .description {{ color: rgba(255,255,255,0.7); margin-bottom: 1.5rem; min-height: 3rem; }}
            button {{
                width: 100%;
                padding: 0.875rem 1.5rem;
                border: none;
                border-radius: 8px;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }}
            .btn-subscribe {{
                background: #4ade80;
                color: #1a1a2e;
            }}
            .btn-subscribe:hover {{ background: #22c55e; transform: scale(1.02); }}
            .btn-current {{
                background: rgba(74, 222, 128, 0.2);
                color: #4ade80;
                cursor: default;
            }}
            button:disabled {{ opacity: 0.7; cursor: not-allowed; }}
            .back-link {{
                display: block;
                text-align: center;
                margin-top: 2rem;
                color: rgba(255,255,255,0.6);
                text-decoration: none;
            }}
            .back-link:hover {{ color: #fff; }}
            .toast {{
                position: fixed;
                bottom: 2rem;
                left: 50%;
                transform: translateX(-50%);
                background: #4ade80;
                color: #1a1a2e;
                padding: 1rem 2rem;
                border-radius: 8px;
                font-weight: 600;
                display: none;
            }}
            .toast.error {{ background: #ef4444; color: #fff; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Choose Your Plan</h1>
            <p class="subtitle">Select the plan that works best for you</p>

            <div class="plans">
                {plans_html}
            </div>

            <a href="/dashboard/" class="back-link">← Back to Dashboard</a>
        </div>

        <div id="toast" class="toast"></div>

        <script>
            async function subscribe(planSlug) {{
                const btn = event.target;
                btn.disabled = true;
                btn.textContent = 'Processing...';

                try {{
                    const response = await fetch('/checkout/subscribe', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{ plan_slug: planSlug }}),
                    }});

                    const data = await response.json();

                    if (data.success) {{
                        showToast(data.message, false);
                        setTimeout(() => window.location.href = '/dashboard/', 1500);
                    }} else {{
                        showToast(data.detail || 'Something went wrong', true);
                        btn.disabled = false;
                        btn.textContent = 'Get Started';
                    }}
                }} catch (error) {{
                    showToast('Network error. Please try again.', true);
                    btn.disabled = false;
                    btn.textContent = 'Get Started';
                }}
            }}

            function showToast(message, isError) {{
                const toast = document.getElementById('toast');
                toast.textContent = message;
                toast.className = 'toast' + (isError ? ' error' : '');
                toast.style.display = 'block';
                setTimeout(() => toast.style.display = 'none', 3000);
            }}
        </script>
    </body>
    </html>
    """
