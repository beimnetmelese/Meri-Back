from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    user_id: str | None = None
    role: str | None = None
    platform_id: str | None = None
    external_learner_id: str | None = None


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class HostPlatformLearnerTokenRequest(BaseModel):
    """
    Used by host platforms (server-to-server) with their private integration key
    to mint a secure, short-lived session token for an authenticated learner.
    """

    public_key: str
    secret_key: str
    external_learner_id: str
    learner_name: str
    learner_email: str | None = None
    role: str = "learner"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    email: str | None = None
    role: str
    is_active: bool
    status: str | None = "active"
    assigned_platform_id: str | None = None
    assigned_platform_name: str | None = None


class LearnerAdminResponse(BaseModel):
    id: str
    full_name: str
    email: str | None = None
    role: str
    is_active: bool
    phone_number: str | None = None
    phone_verified: bool = False
    telegram_linked: bool = False
    telegram_username: str | None = None



class TelegramLinkRequest(BaseModel):
    telegram_chat_id: str
    telegram_username: str | None = None


class TelegramVerifyRequest(BaseModel):
    telegram_chat_id: str
    telegram_user_id: str
    phone_number: str
    first_name: str | None = None
    last_name: str | None = None


class TelegramPlatformOption(BaseModel):
    platform_id: str
    platform_name: str
    domain: str
    role: str


class TelegramSelectPlatformRequest(BaseModel):
    telegram_chat_id: str
    platform_id: str


class AdminRegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    platform_id: str | None = None
    requested_platform_name: str | None = None
    requested_platform_domain: str | None = None


class PendingAdminResponse(BaseModel):
    id: str
    full_name: str
    email: str | None = None
    role: str
    status: str
    created_at: str
    assigned_platform_id: str | None = None
    assigned_platform_name: str | None = None
    requested_platform_name: str | None = None
    requested_platform_domain: str | None = None


class AdminApprovalAction(BaseModel):
    action: str  # "approve" or "reject"
    platform_id: str | None = None
    notes: str | None = None
