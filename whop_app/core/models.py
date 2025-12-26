"""
Database models for Whop embedded app.

Defines SQLAlchemy models for:
- User: Stores Whop user information
- Subscription: Tracks subscription/membership status
- Plan: Available subscription plans (e.g., Free, Pro)
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class SubscriptionStatus(str, PyEnum):
    """Subscription status values."""

    ACTIVE = "active"
    CANCELED = "canceled"
    EXPIRED = "expired"
    PENDING = "pending"  # Waiting for payment confirmation
    TRIAL = "trial"


class User(Base):
    """
    User model - stores Whop user information.

    Users are identified by their Whop user_id (e.g., user_xxxxx).
    Additional profile data is cached from Whop API.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Whop user ID (unique identifier from Whop)
    whop_user_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)

    # Profile data (cached from Whop)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    profile_pic_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.whop_user_id}>"

    @property
    def has_active_subscription(self) -> bool:
        """Check if user has any active subscription."""
        return any(
            sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL)
            for sub in self.subscriptions
        )


class Plan(Base):
    """
    Subscription plan model.

    Defines available plans with pricing and features.
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Plan identifiers
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Pricing (0 = free)
    price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    # Billing period in days (0 = one-time, 30 = monthly, 365 = yearly)
    billing_period_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Plan features (JSON-like text for flexibility)
    features: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="plan"
    )

    def __repr__(self) -> str:
        return f"<Plan {self.name} ${self.price}>"


class Subscription(Base):
    """
    Subscription model - tracks user's subscription status.

    Links users to plans and tracks billing/access status.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plans.id"), nullable=False, index=True
    )

    # Whop references (for syncing with Whop)
    whop_membership_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    whop_checkout_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Status
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False
    )

    # Billing dates
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship("Plan", back_populates="subscriptions")

    def __repr__(self) -> str:
        return f"<Subscription user={self.user_id} plan={self.plan_id} status={self.status}>"

    @property
    def is_active(self) -> bool:
        """Check if subscription grants access."""
        if self.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
            return False

        # Check expiration
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False

        return True
