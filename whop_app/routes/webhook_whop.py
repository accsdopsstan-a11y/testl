"""
Webhook route for Whop events.

Handles incoming webhook events from Whop for:
- Membership changes (valid/invalid)
- Payment events (success/failure)

Security:
- All webhooks MUST be validated using signature verification
- Whop requires response within 3 seconds

References:
    https://docs.whop.com/developer/guides/webhooks
    https://dev.whop.com/webhooks/v5
"""

import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import BaseModel

from core.config import settings
from services.subscriptions import sync_membership_status
from services.tasks import (
    EventType,
    TaskContext,
    handle_event,
    trigger_on_cancel,
    trigger_on_purchase,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookPayload(BaseModel):
    """
    Whop webhook payload structure.

    All Whop webhooks follow this format:
    {
        "event": "membership.went_valid",
        "data": { ... event-specific data ... }
    }
    """

    event: str
    data: Dict[str, Any]

    # Some events include additional fields
    # NOTE: Check Whop docs for complete structure


def verify_webhook_signature(
    payload: bytes,
    signature: Optional[str],
    secret: str,
) -> bool:
    """
    Verify Whop webhook signature.

    Whop signs webhooks using HMAC-SHA256. The signature is
    passed in a header and must be verified before processing.

    Args:
        payload: Raw request body bytes
        signature: Signature from header
        secret: Webhook secret from Whop dashboard

    Returns:
        bool: True if signature is valid

    NOTE: The exact header name and signature format may vary.
    Common patterns:
    - X-Whop-Signature: HMAC-SHA256 hex digest
    - Signature format might be prefixed (e.g., "sha256=...")
    Verify with actual Whop documentation.
    """
    if not signature:
        return False

    # Remove prefix if present (e.g., "sha256=")
    if "=" in signature:
        signature = signature.split("=", 1)[1]

    try:
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


@router.post("/whop")
async def handle_whop_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_whop_signature: Optional[str] = Header(None, alias="X-Whop-Signature"),
    # Alternative header names that Whop might use
    whop_signature: Optional[str] = Header(None, alias="Whop-Signature"),
):
    """
    Main webhook endpoint for Whop events.

    This endpoint:
    1. Validates the webhook signature
    2. Parses the event type and data
    3. Queues event handling as background task (fast response)
    4. Returns 200 OK immediately (Whop requires < 3s response)

    Args:
        request: FastAPI request with raw body
        background_tasks: FastAPI background tasks for async processing
        x_whop_signature: Signature header (primary)
        whop_signature: Signature header (alternative)

    Returns:
        dict: Acknowledgement response

    Raises:
        HTTPException: 401 if signature invalid, 400 if payload invalid
    """
    # Get raw body for signature verification
    raw_body = await request.body()

    # Try both possible header names
    signature = x_whop_signature or whop_signature

    # Verify signature (skip in dev mode for testing)
    if not settings.DEV_MODE:
        if not verify_webhook_signature(raw_body, signature, settings.WEBHOOK_SECRET):
            logger.warning("Invalid webhook signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )
    else:
        if not signature:
            logger.warning("DEV_MODE: Processing webhook without signature verification")

    # Parse payload
    try:
        payload = WebhookPayload.model_validate_json(raw_body)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        )

    logger.info(f"Received webhook: {payload.event}")

    # Queue event processing as background task
    # This ensures we respond quickly to Whop (< 3s requirement)
    background_tasks.add_task(
        process_webhook_event,
        event=payload.event,
        data=payload.data,
    )

    # Return immediately with 200 OK
    return {"status": "received", "event": payload.event}


async def process_webhook_event(event: str, data: dict) -> None:
    """
    Process a webhook event asynchronously.

    This runs as a background task after the webhook response is sent.
    It's where the actual business logic happens.

    Args:
        event: Event type string (e.g., "membership.went_valid")
        data: Event data from Whop
    """
    try:
        logger.info(f"Processing webhook event: {event}")

        # Extract common fields from data
        # NOTE: Field names depend on Whop API - verify with docs
        user_id = data.get("user_id") or data.get("user", {}).get("id")
        membership_id = data.get("id") or data.get("membership_id")
        product_id = data.get("product_id")
        company_id = data.get("company_id")

        # Route to appropriate handler based on event type
        if event == "membership.went_valid":
            await _handle_membership_valid(
                user_id=user_id,
                membership_id=membership_id,
                product_id=product_id,
                data=data,
            )

        elif event == "membership.went_invalid":
            await _handle_membership_invalid(
                user_id=user_id,
                membership_id=membership_id,
                product_id=product_id,
                data=data,
            )

        elif event == "payment.succeeded":
            await _handle_payment_succeeded(
                user_id=user_id,
                payment_id=data.get("id"),
                data=data,
            )

        elif event == "payment.failed":
            await _handle_payment_failed(
                user_id=user_id,
                payment_id=data.get("id"),
                data=data,
            )

        else:
            logger.warning(f"Unhandled webhook event type: {event}")

    except Exception as e:
        logger.error(f"Error processing webhook event {event}: {e}", exc_info=True)


async def _handle_membership_valid(
    user_id: str,
    membership_id: str,
    product_id: Optional[str],
    data: dict,
) -> None:
    """
    Handle membership.went_valid event.

    This fires when:
    - New purchase is made
    - Subscription renews
    - Membership is manually reactivated

    You can distinguish using data.get("status_reason"):
    - "created" = new purchase
    - "updated" = renewal or reactivation
    """
    logger.info(f"Membership valid: user={user_id}, membership={membership_id}")

    # Sync membership status to local cache if using database
    await sync_membership_status(membership_id)

    # Trigger task handlers
    await trigger_on_purchase(
        user_id=user_id,
        membership_id=membership_id,
        product_id=product_id,
        raw_data=data,
    )


async def _handle_membership_invalid(
    user_id: str,
    membership_id: str,
    product_id: Optional[str],
    data: dict,
) -> None:
    """
    Handle membership.went_invalid event.

    This fires when:
    - Subscription is canceled
    - Membership expires
    - Payment fails (after grace period)
    """
    logger.info(f"Membership invalid: user={user_id}, membership={membership_id}")

    # Sync membership status
    await sync_membership_status(membership_id)

    # Trigger task handlers
    await trigger_on_cancel(
        user_id=user_id,
        membership_id=membership_id,
        product_id=product_id,
        raw_data=data,
    )


async def _handle_payment_succeeded(
    user_id: str,
    payment_id: str,
    data: dict,
) -> None:
    """
    Handle payment.succeeded event.

    Use for:
    - Logging successful payments
    - Analytics and reporting
    - Triggering post-payment actions
    """
    logger.info(f"Payment succeeded: user={user_id}, payment={payment_id}")

    context = TaskContext(
        event_type=EventType.PAYMENT_SUCCEEDED,
        user_id=user_id,
        payment_id=payment_id,
        raw_data=data,
    )
    await handle_event(EventType.PAYMENT_SUCCEEDED, context)


async def _handle_payment_failed(
    user_id: str,
    payment_id: str,
    data: dict,
) -> None:
    """
    Handle payment.failed event.

    Use for:
    - Notifying users about failed payments
    - Triggering dunning workflows
    - Logging for analytics
    """
    logger.warning(f"Payment failed: user={user_id}, payment={payment_id}")

    context = TaskContext(
        event_type=EventType.PAYMENT_FAILED,
        user_id=user_id,
        payment_id=payment_id,
        raw_data=data,
    )
    await handle_event(EventType.PAYMENT_FAILED, context)


@router.get("/health")
async def webhook_health():
    """
    Webhook endpoint health check.

    Can be used by monitoring systems to verify the endpoint is available.
    """
    return {"status": "healthy", "service": "webhooks"}
