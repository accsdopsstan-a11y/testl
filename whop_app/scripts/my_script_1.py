#!/usr/bin/env python3
"""
Example script 1: Handle new purchase/membership activation.

This script is triggered when a user gains access to your product.
It runs as a separate process, isolated from the main FastAPI app.

Input (via environment variables):
    - WHOP_USER_ID: The user's Whop ID
    - WHOP_MEMBERSHIP_ID: The membership ID
    - WHOP_EVENT: Event type (e.g., "purchase")

Use cases:
    - Send welcome email
    - Provision user resources
    - Create accounts in external services
    - Log analytics events
    - Notify team via Slack/Discord
"""

import os
import logging
from datetime import datetime

# Configure logging for standalone script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("purchase_script")


def main():
    """
    Main script entry point.

    Reads input from environment variables and performs purchase actions.
    """
    # Read input from environment
    user_id = os.environ.get("WHOP_USER_ID", "unknown")
    membership_id = os.environ.get("WHOP_MEMBERSHIP_ID", "unknown")
    event = os.environ.get("WHOP_EVENT", "unknown")

    logger.info(f"Processing purchase event")
    logger.info(f"  User ID: {user_id}")
    logger.info(f"  Membership ID: {membership_id}")
    logger.info(f"  Event: {event}")
    logger.info(f"  Timestamp: {datetime.now().isoformat()}")

    # ============================================================
    # ADD YOUR PURCHASE LOGIC HERE
    # ============================================================
    #
    # Example actions:
    #
    # 1. Send welcome email
    # -----------------------------------------------------------
    # from your_email_service import send_email
    # send_email(
    #     to=get_user_email(user_id),
    #     template="welcome",
    #     data={"membership_id": membership_id}
    # )
    #
    # 2. Provision resources
    # -----------------------------------------------------------
    # from your_provisioning_service import create_user_resources
    # create_user_resources(user_id, membership_id)
    #
    # 3. Notify team
    # -----------------------------------------------------------
    # import requests
    # requests.post(
    #     os.environ.get("SLACK_WEBHOOK_URL"),
    #     json={"text": f"New purchase! User: {user_id}"}
    # )
    #
    # 4. Log to analytics
    # -----------------------------------------------------------
    # from your_analytics import track_event
    # track_event("purchase", {"user_id": user_id, "membership_id": membership_id})
    #
    # ============================================================

    # Placeholder: Log success
    logger.info("Purchase processing completed successfully")

    # Return 0 for success (used by subprocess)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        exit(exit_code)
    except Exception as e:
        logger.error(f"Script failed with error: {e}", exc_info=True)
        exit(1)
