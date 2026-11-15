from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chat import Conversation
    from app.models.course import Enrollment
    from app.models.platform import Platform
    from app.models.support import SupportTicket


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), default="Learner")
    role: Mapped[str] = mapped_column(
        String(50), default="learner"
    )  # admin, teacher, learner, support_agent
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False
    )  # pending, approved, rejected, active
    assigned_platform_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requested_platform_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_platform_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    assigned_platform: Mapped[Platform | None] = relationship(
        "Platform", foreign_keys=[assigned_platform_id]
    )

    # Relationships
    phones: Mapped[list[UserPhone]] = relationship(
        "UserPhone", back_populates="user", cascade="all, delete-orphan"
    )
    memberships: Mapped[list[UserPlatformMembership]] = relationship(
        "UserPlatformMembership", back_populates="user", cascade="all, delete-orphan"
    )
    telegram_account: Mapped[TelegramAccount | None] = relationship(
        "TelegramAccount", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        "Enrollment", back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    support_tickets: Mapped[list[SupportTicket]] = relationship(
        "SupportTicket", foreign_keys="SupportTicket.learner_id", back_populates="learner"
    )


class UserPhone(Base, TimestampMixin):
    __tablename__ = "user_phones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="phones")


class UserPlatformMembership(Base, TimestampMixin):
    __tablename__ = "user_platform_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_learner_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="learner")
    status: Mapped[str] = mapped_column(String(50), default="active")

    user: Mapped[User] = relationship("User", back_populates="memberships")
    platform: Mapped[Platform] = relationship("Platform")


class TelegramAccount(Base, TimestampMixin):
    __tablename__ = "telegram_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    telegram_chat_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    active_platform_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user: Mapped[User] = relationship("User", back_populates="telegram_account")
    active_platform: Mapped[Platform | None] = relationship("Platform")
