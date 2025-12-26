"""
Dashboard route for Whop embedded app.

This endpoint serves the main application UI that loads inside Whop's iframe.

Key points:
- Runs inside Whop iframe, receives user token automatically
- Must verify user access before showing content
- Can return HTML (for full-page app) or JSON (for SPA)
- Should handle gracefully when user has no access
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.models import Plan
from core.whop_auth import WhopUser, get_current_user, get_optional_user
from services.subscriptions import check_user_access, get_user_membership
from services.users import get_current_user_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: WhopUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Main dashboard page.

    This is the entry point for the embedded app. Whop's iframe
    will load this page with the user's token in headers.

    The page:
    1. Authenticates the user via Whop token
    2. Checks if user has valid subscription/access
    3. Returns appropriate content based on access

    Args:
        request: FastAPI request object
        user: Authenticated user from dependency
        db: Database session

    Returns:
        HTMLResponse: Dashboard HTML content
    """
    # Check if user has access to the app
    has_access = await check_user_access(user.user_id)

    if not has_access:
        # Get available plans for checkout display
        result = await db.execute(
            select(Plan).where(Plan.is_active == True).order_by(Plan.price)
        )
        plans = result.scalars().all()

        # User is authenticated but doesn't have a valid subscription
        return HTMLResponse(
            content=_render_no_access_page(user, plans),
            status_code=status.HTTP_200_OK,
        )

    # Get additional user info for personalization
    membership = await get_user_membership(user.user_id)

    return HTMLResponse(
        content=_render_dashboard_page(user, membership),
        status_code=status.HTTP_200_OK,
    )


@router.get("/api/me")
async def get_current_user_info(
    user: WhopUser = Depends(get_current_user),
):
    """
    Get current user information as JSON.

    Useful for SPAs that need user data after initial page load.

    Args:
        user: Authenticated user

    Returns:
        dict: User information
    """
    profile = await get_current_user_profile(user)
    membership = await get_user_membership(user.user_id)

    return {
        "user": {
            "id": profile.user_id,
            "username": profile.username,
            "email": profile.email,
            "profile_pic_url": profile.profile_pic_url,
        },
        "membership": {
            "id": membership.membership_id if membership else None,
            "status": membership.status.value if membership else None,
            "valid": membership.valid if membership else False,
            "product_id": membership.product_id if membership else None,
            "plan_name": membership.plan_name if membership else None,
        }
        if membership
        else None,
        "has_access": membership is not None and membership.valid,
    }


@router.get("/api/status")
async def check_access_status(
    user: WhopUser = Depends(get_current_user),
):
    """
    Quick access status check.

    Lightweight endpoint for checking if user has access
    without fetching full profile data.

    Args:
        user: Authenticated user

    Returns:
        dict: Access status
    """
    has_access = await check_user_access(user.user_id)

    return {
        "user_id": user.user_id,
        "has_access": has_access,
    }


@router.get("/health")
async def health_check():
    """
    Health check endpoint.

    Doesn't require authentication. Used for monitoring.

    Returns:
        dict: Health status
    """
    return {"status": "healthy", "service": "dashboard"}


# HTML rendering functions
# In production, consider using Jinja2 templates instead


def _render_dashboard_page(user: WhopUser, membership) -> str:
    """
    Render the main dashboard HTML.

    Args:
        user: Authenticated user
        membership: User's membership info

    Returns:
        str: HTML content
    """
    plan_name = membership.plan_name if membership and membership.plan_name else "Active"
    membership_info = ""
    if membership:
        membership_info = f"""
        <div class="membership-card">
            <div class="membership-header">
                <span class="plan-badge">{plan_name}</span>
                <span class="status-badge active">{membership.status.value}</span>
            </div>
            <p class="membership-detail">Plan: <strong>{membership.product_id}</strong></p>
            {f'<p class="membership-detail">Renews: <strong>{membership.current_period_end}</strong></p>' if membership.current_period_end else '<p class="membership-detail">No expiration</p>'}
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard - Whop App</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #ffffff;
                min-height: 100vh;
                padding: 2rem;
            }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .header {{
                display: flex;
                align-items: center;
                gap: 1rem;
                margin-bottom: 2rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid rgba(255,255,255,0.1);
            }}
            .avatar {{
                width: 48px;
                height: 48px;
                border-radius: 50%;
                background: #4a5568;
                object-fit: cover;
            }}
            .welcome {{ font-size: 1.5rem; font-weight: 600; }}
            .user-id {{ font-size: 0.75rem; color: rgba(255,255,255,0.4); margin-top: 0.25rem; }}
            .card {{
                background: rgba(255,255,255,0.05);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 1rem;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            .membership-card {{
                background: rgba(74, 222, 128, 0.1);
                border: 1px solid rgba(74, 222, 128, 0.3);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 1rem;
            }}
            .membership-header {{
                display: flex;
                align-items: center;
                gap: 0.75rem;
                margin-bottom: 1rem;
            }}
            .plan-badge {{
                background: #4ade80;
                color: #1a1a2e;
                padding: 0.25rem 0.75rem;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.875rem;
            }}
            .status-badge {{
                padding: 0.25rem 0.75rem;
                border-radius: 20px;
                font-size: 0.75rem;
                font-weight: 500;
            }}
            .status-badge.active {{ background: rgba(74, 222, 128, 0.2); color: #4ade80; }}
            .membership-detail {{ margin: 0.5rem 0; color: rgba(255,255,255,0.7); }}
            h2 {{ margin-bottom: 1rem; font-size: 1.25rem; }}
            p {{ line-height: 1.6; color: rgba(255,255,255,0.7); }}
            code {{
                background: rgba(255,255,255,0.1);
                padding: 0.125rem 0.375rem;
                border-radius: 4px;
                font-size: 0.875rem;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img class="avatar" src="{user.profile_pic_url or ''}" alt="Avatar"
                     onerror="this.style.background='#4a5568'; this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%23718096%22><path d=%22M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z%22/></svg>'">
                <div>
                    <div class="welcome">Welcome, {user.username or 'User'}!</div>
                    <div class="user-id">{user.user_id}</div>
                </div>
            </div>

            {membership_info}

            <div class="card">
                <h2>Your Dashboard</h2>
                <p>
                    You have full access to all features.
                    This is your embedded app dashboard - customize it for your needs.
                </p>
            </div>

            <div class="card">
                <h2>Quick Start</h2>
                <p>
                    Edit <code>routes/dashboard.py</code> to customize this page.<br>
                    Add business logic in <code>services/</code>.<br>
                    Handle events via <code>routes/webhook_whop.py</code>.
                </p>
            </div>
        </div>
    </body>
    </html>
    """


def _render_no_access_page(user: WhopUser, plans: list) -> str:
    """
    Render page for users without access - includes checkout.

    Args:
        user: Authenticated user (without subscription)
        plans: Available subscription plans

    Returns:
        str: HTML content with embedded checkout
    """
    # Build plans HTML
    plans_html = ""
    for plan in plans:
        price_text = "Free" if plan.price == 0 else f"${plan.price:.2f}"
        period_text = ""
        if plan.billing_period_days > 0:
            if plan.billing_period_days == 30:
                period_text = "/month"
            elif plan.billing_period_days == 365:
                period_text = "/year"
            else:
                period_text = f"/{plan.billing_period_days} days"

        plans_html += f"""
        <div class="plan-card" data-slug="{plan.slug}">
            <div class="plan-name">{plan.name}</div>
            <div class="plan-price">{price_text}<span class="period">{period_text}</span></div>
            <div class="plan-description">{plan.description or ''}</div>
            <button class="btn-subscribe" onclick="subscribe('{plan.slug}')">
                {'Get Started Free' if plan.price == 0 else 'Subscribe'}
            </button>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Choose Your Plan - Whop App</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #ffffff;
                min-height: 100vh;
                padding: 2rem;
            }}
            .container {{ max-width: 600px; margin: 0 auto; text-align: center; }}
            .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
            h1 {{ font-size: 1.75rem; margin-bottom: 0.5rem; }}
            .subtitle {{ color: rgba(255,255,255,0.6); margin-bottom: 2rem; }}
            .user-info {{
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                background: rgba(255,255,255,0.1);
                padding: 0.5rem 1rem;
                border-radius: 20px;
                margin-bottom: 2rem;
                font-size: 0.875rem;
            }}
            .plans {{ display: flex; flex-direction: column; gap: 1rem; }}
            .plan-card {{
                background: rgba(255,255,255,0.05);
                border: 2px solid rgba(255,255,255,0.1);
                border-radius: 16px;
                padding: 1.5rem;
                text-align: left;
                transition: all 0.2s;
            }}
            .plan-card:hover {{ border-color: rgba(74, 222, 128, 0.5); transform: translateY(-2px); }}
            .plan-name {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 0.5rem; }}
            .plan-price {{ font-size: 2rem; font-weight: 700; margin-bottom: 0.5rem; }}
            .plan-price .period {{ font-size: 0.875rem; color: rgba(255,255,255,0.5); font-weight: 400; }}
            .plan-description {{ color: rgba(255,255,255,0.6); margin-bottom: 1rem; font-size: 0.875rem; }}
            .btn-subscribe {{
                width: 100%;
                padding: 0.875rem;
                background: #4ade80;
                color: #1a1a2e;
                border: none;
                border-radius: 8px;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }}
            .btn-subscribe:hover {{ background: #22c55e; }}
            .btn-subscribe:disabled {{ opacity: 0.6; cursor: not-allowed; }}
            .toast {{
                position: fixed;
                bottom: 2rem;
                left: 50%;
                transform: translateX(-50%) translateY(100px);
                background: #4ade80;
                color: #1a1a2e;
                padding: 1rem 2rem;
                border-radius: 8px;
                font-weight: 600;
                opacity: 0;
                transition: all 0.3s;
                z-index: 1000;
            }}
            .toast.show {{ transform: translateX(-50%) translateY(0); opacity: 1; }}
            .toast.error {{ background: #ef4444; color: #fff; }}
            .loading {{
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 2px solid rgba(26, 26, 46, 0.3);
                border-top-color: #1a1a2e;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
                margin-right: 0.5rem;
            }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">🚀</div>
            <h1>Welcome to Our App!</h1>
            <p class="subtitle">Choose a plan to get started</p>

            <div class="user-info">
                <span>👤</span>
                <span>{user.username or user.user_id}</span>
            </div>

            <div class="plans">
                {plans_html if plans_html else '<p>No plans available</p>'}
            </div>
        </div>

        <div id="toast" class="toast"></div>

        <script>
            // Get token from URL for API calls
            const urlParams = new URLSearchParams(window.location.search);
            const token = urlParams.get('whop-dev-user-token');

            async function subscribe(planSlug) {{
                const btn = event.target;
                const originalText = btn.textContent;
                btn.disabled = true;
                btn.innerHTML = '<span class="loading"></span>Processing...';

                try {{
                    const headers = {{ 'Content-Type': 'application/json' }};

                    // Pass token in header for API authentication
                    if (token) {{
                        headers['x-whop-user-token'] = token;
                    }}

                    const response = await fetch('/checkout/subscribe', {{
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify({{ plan_slug: planSlug }}),
                    }});

                    const data = await response.json();

                    if (response.ok && data.success) {{
                        showToast('🎉 ' + data.message, false);
                        // Reload page to show dashboard
                        setTimeout(() => window.location.reload(), 1500);
                    }} else {{
                        showToast(data.detail || 'Something went wrong', true);
                        btn.disabled = false;
                        btn.textContent = originalText;
                    }}
                }} catch (error) {{
                    console.error('Subscribe error:', error);
                    showToast('Network error. Please try again.', true);
                    btn.disabled = false;
                    btn.textContent = originalText;
                }}
            }}

            function showToast(message, isError) {{
                const toast = document.getElementById('toast');
                toast.textContent = message;
                toast.className = 'toast' + (isError ? ' error' : '') + ' show';
                setTimeout(() => toast.className = 'toast', 3000);
            }}
        </script>
    </body>
    </html>
    """
