from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupportTicketCreate(BaseModel):
    conversation_id: str | None = None
    subject: str = Field(
        default="Request for Human Assistance", examples=["Need clarification on assignment"]
    )
    initial_message: str | None = None
    consent_share_history: bool = Field(default=True)
    screen_sharing_active: bool = Field(default=False)
    platform_id: str | None = None
    public_key: str | None = None
    learner_name: str | None = None
    page_context: str | None = None


class SupportMessageCreate(BaseModel):
    content: str = Field(..., examples=["Hello, I have an issue with lesson 3"])


class SupportMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    sender_id: str
    sender_role: str
    content: str
    created_at: datetime


class SupportTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform_id: str
    learner_id: str
    conversation_id: str | None = None
    assigned_agent_id: str | None = None
    subject: str
    status: str
    consent_share_history: bool
    screen_sharing_active: bool
    created_at: datetime
    messages: list[SupportMessageResponse] = Field(default_factory=list)
    learner_name: str | None = None
    platform_name: str | None = None


class SupportTicketStatusUpdate(BaseModel):
    status: str = Field(..., examples=["in_progress", "resolved", "closed"])
