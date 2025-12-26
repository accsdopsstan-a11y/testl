"""
Task service for Whop embedded app.

Handles execution of background tasks and scripts in response to events.
Scripts are isolated Python files in the scripts/ directory.

Design principles:
- Tasks are fire-and-forget (don't block webhook response)
- Scripts are isolated and don't import FastAPI
- Error handling is local to each task
- Easy to add new event handlers
"""

import asyncio
import importlib.util
import logging
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Base path for scripts
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


class EventType(str, Enum):
    """
    Whop webhook event types.

    Based on Whop webhook documentation:
    - membership.went_valid: User gained access (new purchase or renewal)
    - membership.went_invalid: User lost access (cancel, expire, failed payment)
    - payment.succeeded: Payment was successful
    - payment.failed: Payment attempt failed
    """

    MEMBERSHIP_VALID = "membership.went_valid"
    MEMBERSHIP_INVALID = "membership.went_invalid"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"

    # Legacy/alternative event names (for compatibility)
    PURCHASE = "purchase"
    CANCEL = "cancel"
    RENEW = "renew"


@dataclass
class TaskContext:
    """
    Context passed to task handlers.

    Contains all relevant information about the triggering event.
    """

    event_type: EventType
    user_id: str
    membership_id: Optional[str] = None
    product_id: Optional[str] = None
    company_id: Optional[str] = None
    payment_id: Optional[str] = None
    raw_data: Optional[dict] = None


# Registry of event handlers
# Maps event type to list of handler functions
_event_handlers: Dict[EventType, list[Callable]] = {}


def register_handler(event_type: EventType):
    """
    Decorator to register an event handler.

    Usage:
        @register_handler(EventType.MEMBERSHIP_VALID)
        async def on_purchase(context: TaskContext):
            ...

    Args:
        event_type: Event type to handle
    """

    def decorator(func: Callable):
        if event_type not in _event_handlers:
            _event_handlers[event_type] = []
        _event_handlers[event_type].append(func)
        logger.info(f"Registered handler {func.__name__} for {event_type.value}")
        return func

    return decorator


async def handle_event(event_type: EventType, context: TaskContext) -> None:
    """
    Handle an event by running all registered handlers.

    Handlers are run concurrently. Errors in one handler don't affect others.

    Args:
        event_type: Type of event
        context: Event context with relevant data
    """
    handlers = _event_handlers.get(event_type, [])

    if not handlers:
        logger.warning(f"No handlers registered for event: {event_type.value}")
        return

    logger.info(f"Running {len(handlers)} handlers for {event_type.value}")

    # Run all handlers concurrently
    tasks = [_run_handler_safely(handler, context) for handler in handlers]
    await asyncio.gather(*tasks)


async def _run_handler_safely(
    handler: Callable, context: TaskContext
) -> Optional[Any]:
    """
    Run a handler with error isolation.

    Catches and logs any errors without propagating.

    Args:
        handler: Handler function to run
        context: Event context

    Returns:
        Handler result or None if error
    """
    try:
        result = handler(context)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    except Exception as e:
        logger.error(f"Handler {handler.__name__} failed: {e}", exc_info=True)
        return None


async def run_script(script_name: str, args: Optional[dict] = None) -> bool:
    """
    Run a Python script from the scripts directory.

    Scripts are run as separate processes for isolation.

    Args:
        script_name: Name of script file (with or without .py)
        args: Optional arguments passed as environment variables

    Returns:
        bool: True if script completed successfully
    """
    if not script_name.endswith(".py"):
        script_name = f"{script_name}.py"

    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False

    try:
        # Build environment with args
        env = {}
        if args:
            for key, value in args.items():
                env[f"WHOP_{key.upper()}"] = str(value)

        # Run script as subprocess
        # Using asyncio subprocess for non-blocking execution
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            env={**env},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(
                f"Script {script_name} failed with code {process.returncode}: "
                f"{stderr.decode()}"
            )
            return False

        logger.info(f"Script {script_name} completed successfully")
        if stdout:
            logger.debug(f"Script output: {stdout.decode()}")

        return True

    except Exception as e:
        logger.error(f"Error running script {script_name}: {e}")
        return False


def run_script_sync(script_name: str, args: Optional[dict] = None) -> bool:
    """
    Synchronous version of run_script for use outside async context.

    Args:
        script_name: Name of script file
        args: Optional arguments

    Returns:
        bool: True if successful
    """
    if not script_name.endswith(".py"):
        script_name = f"{script_name}.py"

    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False

    try:
        env = {}
        if args:
            for key, value in args.items():
                env[f"WHOP_{key.upper()}"] = str(value)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Script failed: {result.stderr}")
            return False

        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Script {script_name} timed out")
        return False
    except Exception as e:
        logger.error(f"Error running script: {e}")
        return False


# Default event handlers
# These demonstrate the pattern - customize for your use case


@register_handler(EventType.MEMBERSHIP_VALID)
async def on_membership_valid(context: TaskContext) -> None:
    """
    Handle new valid membership (purchase/renewal).

    This runs when a user gains access to your product.
    """
    logger.info(
        f"New valid membership: user={context.user_id}, "
        f"membership={context.membership_id}"
    )

    # Run the purchase script
    await run_script(
        "my_script_1.py",
        {
            "user_id": context.user_id,
            "membership_id": context.membership_id,
            "event": "purchase",
        },
    )


@register_handler(EventType.MEMBERSHIP_INVALID)
async def on_membership_invalid(context: TaskContext) -> None:
    """
    Handle membership becoming invalid (cancel/expire).

    This runs when a user loses access to your product.
    """
    logger.info(
        f"Membership invalid: user={context.user_id}, "
        f"membership={context.membership_id}"
    )

    # Run the cancellation script
    await run_script(
        "my_script_2.py",
        {
            "user_id": context.user_id,
            "membership_id": context.membership_id,
            "event": "cancel",
        },
    )


@register_handler(EventType.PAYMENT_FAILED)
async def on_payment_failed(context: TaskContext) -> None:
    """
    Handle failed payment.

    Use this to notify users about payment issues.
    """
    logger.warning(
        f"Payment failed: user={context.user_id}, "
        f"payment={context.payment_id}"
    )

    # You might want to:
    # - Send notification to user
    # - Log for analytics
    # - Trigger dunning workflow


# Convenience functions for common patterns


async def trigger_on_purchase(
    user_id: str,
    membership_id: str,
    product_id: Optional[str] = None,
    raw_data: Optional[dict] = None,
) -> None:
    """
    Trigger purchase event handlers.

    Convenience function for webhook handler.

    Args:
        user_id: Whop user ID
        membership_id: Membership ID
        product_id: Optional product ID
        raw_data: Optional raw webhook data
    """
    context = TaskContext(
        event_type=EventType.MEMBERSHIP_VALID,
        user_id=user_id,
        membership_id=membership_id,
        product_id=product_id,
        raw_data=raw_data,
    )
    await handle_event(EventType.MEMBERSHIP_VALID, context)


async def trigger_on_cancel(
    user_id: str,
    membership_id: str,
    product_id: Optional[str] = None,
    raw_data: Optional[dict] = None,
) -> None:
    """
    Trigger cancellation event handlers.

    Args:
        user_id: Whop user ID
        membership_id: Membership ID
        product_id: Optional product ID
        raw_data: Optional raw webhook data
    """
    context = TaskContext(
        event_type=EventType.MEMBERSHIP_INVALID,
        user_id=user_id,
        membership_id=membership_id,
        product_id=product_id,
        raw_data=raw_data,
    )
    await handle_event(EventType.MEMBERSHIP_INVALID, context)
