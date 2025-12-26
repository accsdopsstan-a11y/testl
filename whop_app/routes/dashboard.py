"""
Dashboard route for Whop embedded app.

This endpoint serves the main application UI that loads inside Whop's iframe.

Key points:
- Runs inside Whop iframe, receives user token automatically
- Must verify user access before showing content
- Can return HTML (for full-page app) or JSON (for SPA)
- Should handle gracefully when user has no access
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from core.whop_auth import WhopUser, get_current_user, get_optional_user
from services.subscriptions import check_user_access, get_user_membership
from services.users import get_current_user_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: WhopUser = Depends(get_current_user),
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

    Returns:
        HTMLResponse: Dashboard HTML content
    """
    # Check if user has access to the app
    has_access = await check_user_access(user.user_id)

    if not has_access:
        # User is authenticated but doesn't have a valid subscription
        return HTMLResponse(
            content=_render_no_access_page(user),
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
    membership_info = ""
    if membership:
        membership_info = f"""
        <div class="membership-card">
            <h3>Your Subscription</h3>
            <p><strong>Status:</strong> {membership.status.value}</p>
            <p><strong>Product:</strong> {membership.product_id}</p>
            {f'<p><strong>Renews:</strong> {membership.current_period_end}</p>' if membership.current_period_end else ''}
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
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #ffffff;
                min-height: 100vh;
                padding: 2rem;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
            }}
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
            }}
            .welcome {{
                font-size: 1.5rem;
                font-weight: 600;
            }}
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
            .membership-card h3 {{
                color: #4ade80;
                margin-bottom: 1rem;
            }}
            .membership-card p {{
                margin: 0.5rem 0;
                color: rgba(255,255,255,0.8);
            }}
            h1 {{
                margin-bottom: 1rem;
            }}
            p {{
                line-height: 1.6;
                color: rgba(255,255,255,0.7);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img class="avatar" src="{user.profile_pic_url or ''}" alt="Avatar" onerror="this.style.display='none'">
                <div>
                    <div class="welcome">Welcome, {user.username or 'User'}!</div>
                    <small style="color: rgba(255,255,255,0.5);">{user.email or ''}</small>
                </div>
            </div>

            {membership_info}

            <div class="card">
                <h2>Your Dashboard</h2>
                <p>
                    This is your embedded app dashboard. You have full access to all features.
                    Customize this page to show your app's main functionality.
                </p>
            </div>

            <div class="card">
                <h3>Getting Started</h3>
                <p>
                    • Edit <code>routes/dashboard.py</code> to customize this page<br>
                    • Add your business logic in <code>services/</code><br>
                    • React to events via webhooks in <code>routes/webhook_whop.py</code>
                </p>
            </div>
        </div>
    </body>
    </html>
    """


def _render_no_access_page(user: WhopUser) -> str:
    """
    Render page for users without access.

    Args:
        user: Authenticated user (without subscription)

    Returns:
        str: HTML content
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Access Required - Whop App</title>
        <style>
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: #ffffff;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 2rem;
            }}
            .container {{
                max-width: 500px;
                text-align: center;
            }}
            .icon {{
                font-size: 4rem;
                margin-bottom: 1rem;
            }}
            h1 {{
                margin-bottom: 1rem;
                font-size: 1.75rem;
            }}
            p {{
                color: rgba(255,255,255,0.7);
                line-height: 1.6;
                margin-bottom: 2rem;
            }}
            .btn {{
                display: inline-block;
                background: #4ade80;
                color: #1a1a2e;
                padding: 0.75rem 2rem;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 600;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(74, 222, 128, 0.3);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">🔒</div>
            <h1>Subscription Required</h1>
            <p>
                Hi {user.username or 'there'}! You need an active subscription
                to access this app. Please purchase a membership to continue.
            </p>
            <a href="#" class="btn" onclick="window.parent.postMessage('whop:open-checkout', '*')">
                Get Access
            </a>
        </div>
    </body>
    </html>
    """
