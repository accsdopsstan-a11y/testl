#!/usr/bin/env python3
"""
Example script 2: Handle membership cancellation/expiration.

This script is triggered when a user loses access to your product.
It runs as a separate process, isolated from the main FastAPI app.

Input (via environment variables):
    - WHOP_USER_ID: The user's Whop ID
    - WHOP_MEMBERSHIP_ID: The membership ID
    - WHOP_EVENT: Event type (e.g., "cancel")

Use cases:
    - Send farewell/win-back email
    - Revoke access to external services
    - Archive user data
    - Log churn analytics
    - Notify team about churn
"""

import os
import logging
from datetime import datetime

# Configure logging for standalone script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cancel_script")


def main():
    """
    Main script entry point.

    Reads input from environment variables and performs cancellation actions.
    """
    # Read input from environment
    user_id = os.environ.get("WHOP_USER_ID", "unknown")
    membership_id = os.environ.get("WHOP_MEMBERSHIP_ID", "unknown")
    event = os.environ.get("WHOP_EVENT", "unknown")

    logger.info(f"Processing cancellation event")
    logger.info(f"  User ID: {user_id}")
    logger.info(f"  Membership ID: {membership_id}")
    logger.info(f"  Event: {event}")
    logger.info(f"  Timestamp: {datetime.now().isoformat()}")

    # ============================================================
    # ADD YOUR CANCELLATION LOGIC HERE
    # ============================================================
    #
    # Example actions:
    #
    # 1. Send win-back email
    # -----------------------------------------------------------
    # from your_email_service import send_email
    # send_email(
    #     to=get_user_email(user_id),
    #     template="win_back",
    #     data={"membership_id": membership_id, "discount_code": "COMEBACK20"}
    # )
    #
    # 2. Revoke external access
    # -----------------------------------------------------------
    # from your_access_service import revoke_access
    # revoke_access(user_id)
    #
    # 3. Archive user data (for potential reactivation)
    # -----------------------------------------------------------
    # from your_data_service import archive_user_data
    # archive_user_data(user_id, membership_id)
    #
    # 4. Notify team about churn
    # -----------------------------------------------------------
    # import requests
    # requests.post(
    #     os.environ.get("SLACK_WEBHOOK_URL"),
    #     json={"text": f"Churn alert: User {user_id} cancelled"}
    # )
    #
    # 5. Log churn analytics
    # -----------------------------------------------------------
    # from your_analytics import track_event
    # track_event("churn", {"user_id": user_id, "membership_id": membership_id})
    #
    # ============================================================

    # Placeholder: Log success
    logger.info("Cancellation processing completed successfully")

    # Return 0 for success (used by subprocess)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        exit(exit_code)
    except Exception as e:
        logger.error(f"Script failed with error: {e}", exc_info=True)
        exit(1)
