from datetime import timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_superadmin
from app.core.security import (
    create_access_token,
    verify_password,
    verify_secret_key,
    hash_password,
    generate_public_key,
    generate_secret_key,
    hash_secret_key,
)
from app.models.platform import Platform, PlatformConfiguration, PlatformDomain
from app.models.user import TelegramAccount, User, UserPlatformMembership
from app.schemas.auth import (
    AdminApprovalAction,
    AdminRegisterRequest,
    HostPlatformLearnerTokenRequest,
    LearnerAdminResponse,
    LoginRequest,
    PendingAdminResponse,
    TelegramLinkRequest,
    TelegramPlatformOption,
    TelegramSelectPlatformRequest,
    TelegramVerifyRequest,
    Token,
    UserResponse,
)
from app.services.telegram_service import telegram_service

router = APIRouter()


@router.post("/register-admin", status_code=status.HTTP_201_CREATED)
async def register_platform_admin(
    payload: AdminRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Public registration endpoint for new Platform Administrators.
    Creates an account in 'pending' status awaiting SuperAdmin approval.
    """
    # Check if email is already taken
    email_clean = payload.email.strip().lower()
    stmt = select(User).where(User.email == email_clean)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    assigned_platform_id = None
    if payload.platform_id:
        plat_stmt = select(Platform).where(Platform.id == payload.platform_id)
        plat_res = await db.execute(plat_stmt)
        platform = plat_res.scalar_one_or_none()
        if platform:
            assigned_platform_id = platform.id

    new_admin = User(
        email=email_clean,
        full_name=payload.full_name.strip(),
        role="platform_admin",
        hashed_password=hash_password(payload.password),
        is_active=False,  # Inactive until approved
        status="pending",
        assigned_platform_id=assigned_platform_id,
        requested_platform_name=payload.requested_platform_name.strip() if payload.requested_platform_name else None,
        requested_platform_domain=payload.requested_platform_domain.strip().lower() if payload.requested_platform_domain else None,
    )
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)

    return {
        "status": "pending",
        "message": "Your application has been submitted! The SuperAdmin will review and approve your application before you can log in.",
        "user_id": new_admin.id,
        "email": new_admin.email,
    }


@router.post("/token", response_model=Token)
async def obtain_token(
    payload: HostPlatformLearnerTokenRequest | LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Unified Token Endpoint:
    1. Server-to-server: Host platform requests a secure short-lived token for a logged-in learner.
    2. Direct login: SuperAdmin or Platform Admin logging in with credentials.
    """
    # Case 1: Host platform server-to-server learner token
    if isinstance(payload, HostPlatformLearnerTokenRequest) or hasattr(payload, "secret_key"):
        req: HostPlatformLearnerTokenRequest = payload  # type: ignore
        stmt = select(Platform).where(
            Platform.public_key == req.public_key, Platform.enabled == True
        )
        res = await db.execute(stmt)
        platform = res.scalar_one_or_none()

        if not platform or not verify_secret_key(req.secret_key, platform.secret_key_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid platform integration credentials",
            )

        # Find or create learner user record
        learner_stmt = (
            select(User)
            .join(UserPlatformMembership, UserPlatformMembership.user_id == User.id)
            .where(
                UserPlatformMembership.platform_id == platform.id,
                UserPlatformMembership.external_learner_id == req.external_learner_id,
            )
        )
        learner_res = await db.execute(learner_stmt)
        user = learner_res.scalar_one_or_none()

        if not user:
            user = User(
                email=req.learner_email,
                full_name=req.learner_name,
                role=req.role or "learner",
                is_active=True,
                status="approved",
            )
            db.add(user)
            await db.flush()

            membership = UserPlatformMembership(
                user_id=user.id,
                platform_id=platform.id,
                external_learner_id=req.external_learner_id,
                role=req.role or "learner",
                status="active",
            )
            db.add(membership)
            await db.commit()

        expires_delta = timedelta(minutes=settings.INTEGRATION_TOKEN_EXPIRE_MINUTES)
        token_str = create_access_token(
            subject=user.id,
            expires_delta=expires_delta,
            extra_claims={
                "platform_id": platform.id,
                "role": user.role,
                "external_learner_id": req.external_learner_id,
                "platform_name": platform.name,
            },
        )
        return Token(
            access_token=token_str,
            expires_in=settings.INTEGRATION_TOKEN_EXPIRE_MINUTES * 60,
        )

    # Case 2: Direct user password login (SuperAdmin or Platform Admin)
    login_req: LoginRequest = payload  # type: ignore
    user_stmt = select(User).where(
        (User.email == login_req.username_or_email.strip().lower())
        | (User.id == login_req.username_or_email.strip())
    )
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if (
        not user
        or not user.hashed_password
        or not verify_password(login_req.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Check approval status and account state
    if user.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your application is pending review by the SuperAdmin. Please wait for approval before logging in.",
        )
    if user.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your platform administrator application was not approved by the SuperAdmin.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact the administrator.",
        )

    # Determine assigned platform details
    assigned_plat_name = None
    if user.assigned_platform_id:
        p_stmt = select(Platform).where(Platform.id == user.assigned_platform_id)
        p_res = await db.execute(p_stmt)
        p = p_res.scalar_one_or_none()
        if p:
            assigned_plat_name = p.name

    role_normalized = "superadmin" if user.role in ("superadmin", "admin") else user.role

    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_str = create_access_token(
        subject=user.id,
        expires_delta=expires_delta,
        extra_claims={
            "role": role_normalized,
            "status": user.status,
            "platform_id": user.assigned_platform_id,
            "platform_name": assigned_plat_name,
            "full_name": user.full_name,
            "email": user.email,
        },
    )
    return Token(
        access_token=token_str,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    current_user: User = Depends(get_current_user),
):
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token_str = create_access_token(
        subject=current_user.id,
        expires_delta=expires_delta,
        extra_claims={"role": current_user.role, "status": current_user.status},
    )
    return Token(
        access_token=token_str,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    assigned_plat_name = None
    if current_user.assigned_platform_id:
        stmt = select(Platform).where(Platform.id == current_user.assigned_platform_id)
        res = await db.execute(stmt)
        plat = res.scalar_one_or_none()
        if plat:
            assigned_plat_name = plat.name

    role_normalized = "superadmin" if current_user.role in ("superadmin", "admin") else current_user.role

    return UserResponse(
        id=current_user.id,
        full_name=current_user.full_name,
        email=current_user.email,
        role=role_normalized,
        is_active=current_user.is_active,
        status=current_user.status,
        assigned_platform_id=current_user.assigned_platform_id,
        assigned_platform_name=assigned_plat_name,
    )


@router.get("/pending-admins", response_model=list[PendingAdminResponse])
async def list_pending_admins(
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """SuperAdmin endpoint to list all platform admin applications awaiting review."""
    stmt = (
        select(User)
        .where(User.role == "platform_admin", User.status == "pending")
        .order_by(User.created_at.desc())
    )
    res = await db.execute(stmt)
    pending_users = res.scalars().all()

    results = []
    for u in pending_users:
        plat_name = None
        if u.assigned_platform_id:
            p_res = await db.execute(select(Platform).where(Platform.id == u.assigned_platform_id))
            p = p_res.scalar_one_or_none()
            if p:
                plat_name = p.name

        results.append(
            PendingAdminResponse(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                status=u.status,
                created_at=u.created_at.isoformat() if u.created_at else "",
                assigned_platform_id=u.assigned_platform_id,
                assigned_platform_name=plat_name,
                requested_platform_name=u.requested_platform_name,
                requested_platform_domain=u.requested_platform_domain,
            )
        )
    return results


@router.get("/approved-admins", response_model=list[PendingAdminResponse])
async def list_approved_admins(
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """SuperAdmin endpoint to list all approved platform admins."""
    stmt = (
        select(User)
        .where(User.role == "platform_admin", User.status == "approved")
        .order_by(User.created_at.desc())
    )
    res = await db.execute(stmt)
    admins = res.scalars().all()

    results = []
    for u in admins:
        plat_name = None
        if u.assigned_platform_id:
            p_res = await db.execute(select(Platform).where(Platform.id == u.assigned_platform_id))
            p = p_res.scalar_one_or_none()
            if p:
                plat_name = p.name

        results.append(
            PendingAdminResponse(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                status=u.status,
                created_at=u.created_at.isoformat() if u.created_at else "",
                assigned_platform_id=u.assigned_platform_id,
                assigned_platform_name=plat_name,
                requested_platform_name=u.requested_platform_name,
                requested_platform_domain=u.requested_platform_domain,
            )
        )
    return results


@router.post("/approve-admin/{admin_id}")
async def approve_platform_admin(
    admin_id: str,
    action: AdminApprovalAction | None = None,
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """SuperAdmin endpoint to approve a pending platform admin and link them to their platform."""
    stmt = select(User).where(User.id == admin_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    target_platform_id = action.platform_id if (action and action.platform_id) else user.assigned_platform_id

    # If the user requested a new platform that hasn't been created yet:
    if not target_platform_id and user.requested_platform_name:
        domain = user.requested_platform_domain or f"{user.requested_platform_name.lower().replace(' ', '-')}.example.com"
        # Check domain existence
        existing_p = await db.execute(select(Platform).where(Platform.domain == domain))
        p = existing_p.scalar_one_or_none()
        if not p:
            p = Platform(
                name=user.requested_platform_name,
                domain=domain,
                public_key=generate_public_key(),
                secret_key_hash=hash_secret_key(generate_secret_key()),
                enabled=True,
            )
            db.add(p)
            await db.flush()
            # Add default configuration
            cfg = PlatformConfiguration(
                platform_id=p.id,
                platform_name=p.name,
                theme={"primary": "#16A34A", "secondary": "#14532D", "background": "#FFFFFF", "text": "#111827", "chat_button": "#16A34A"},
                branding={"logo_url": "https://example.com/logo.png"},
                welcome_message=f"Welcome to {p.name}! How can I assist you today?",
                features={"voice": True, "human_support": True, "simple_mode": True, "job_assistance": True, "course_assistant": True},
            )
            db.add(cfg)
            db.add(PlatformDomain(platform_id=p.id, domain=domain, is_verified=True))
            await db.flush()
        target_platform_id = p.id

    user.status = "approved"
    user.is_active = True
    user.assigned_platform_id = target_platform_id

    # Create membership if platform exists
    if target_platform_id:
        mem_stmt = select(UserPlatformMembership).where(
            UserPlatformMembership.user_id == user.id,
            UserPlatformMembership.platform_id == target_platform_id,
        )
        mem_res = await db.execute(mem_stmt)
        if not mem_res.scalar_one_or_none():
            db.add(
                UserPlatformMembership(
                    user_id=user.id,
                    platform_id=target_platform_id,
                    external_learner_id=f"admin_{user.id[:8]}",
                    role="admin",
                    status="active",
                )
            )

    await db.commit()
    await db.refresh(user)

    return {
        "status": "success",
        "message": f"Platform Administrator {user.full_name} has been approved successfully.",
        "user_id": user.id,
        "platform_id": user.assigned_platform_id,
    }


@router.post("/reject-admin/{admin_id}")
async def reject_platform_admin(
    admin_id: str,
    action: AdminApprovalAction | None = None,
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """SuperAdmin endpoint to reject an application."""
    stmt = select(User).where(User.id == admin_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.status = "rejected"
    user.is_active = False
    await db.commit()

    return {
        "status": "rejected",
        "message": f"Application for {user.full_name} has been rejected.",
        "user_id": user.id,
    }


@router.post("/telegram/link")
async def link_telegram_account(
    payload: TelegramLinkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Links current user account to Telegram chat ID."""
    stmt = select(TelegramAccount).where(TelegramAccount.user_id == current_user.id)
    res = await db.execute(stmt)
    tg = res.scalar_one_or_none()

    if not tg:
        tg = TelegramAccount(
            user_id=current_user.id,
            telegram_chat_id=payload.telegram_chat_id,
            telegram_username=payload.telegram_username,
            phone_number="",
            is_verified=False,
        )
        db.add(tg)
    else:
        tg.telegram_chat_id = payload.telegram_chat_id
        tg.telegram_username = payload.telegram_username

    await db.commit()
    return {"status": "success", "message": "Telegram account association created"}


@router.post("/telegram/verify")
async def verify_telegram_phone(
    payload: TelegramVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verifies phone number received via Telegram contact sharing against
    registered platform learner phone records.
    """
    result_message = await telegram_service.verify_contact_and_link(
        db=db,
        chat_id=payload.telegram_chat_id,
        tg_user_id=payload.telegram_user_id,
        phone_number=payload.phone_number,
        first_name=payload.first_name,
    )
    return {"status": "completed", "message": result_message}


@router.get("/telegram/platforms", response_model=list[TelegramPlatformOption])
async def get_telegram_learner_platforms(
    telegram_chat_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieves all authorized platform memberships for a verified Telegram user."""
    stmt = select(TelegramAccount).where(
        TelegramAccount.telegram_chat_id == telegram_chat_id, TelegramAccount.is_verified == True
    )
    res = await db.execute(stmt)
    tg = res.scalar_one_or_none()

    if not tg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram account not linked or not verified",
        )

    mem_stmt = (
        select(UserPlatformMembership, Platform)
        .join(Platform, UserPlatformMembership.platform_id == Platform.id)
        .where(UserPlatformMembership.user_id == tg.user_id, Platform.enabled == True)
    )
    mem_res = await db.execute(mem_stmt)
    memberships = mem_res.all()

    return [
        TelegramPlatformOption(
            platform_id=plat.id,
            platform_name=plat.name,
            domain=plat.domain,
            role=mem.role,
        )
        for mem, plat in memberships
    ]


@router.post("/telegram/select-platform")
async def select_telegram_platform(
    payload: TelegramSelectPlatformRequest,
    db: AsyncSession = Depends(get_db),
):
    """Sets the active platform for a verified Telegram user."""
    stmt = select(TelegramAccount).where(
        TelegramAccount.telegram_chat_id == payload.telegram_chat_id,
        TelegramAccount.is_verified == True,
    )
    res = await db.execute(stmt)
    tg = res.scalar_one_or_none()

    if not tg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Telegram account not verified"
        )

    mem_stmt = select(UserPlatformMembership).where(
        UserPlatformMembership.user_id == tg.user_id,
        UserPlatformMembership.platform_id == payload.platform_id,
    )
    mem_res = await db.execute(mem_stmt)
    if not mem_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Learner is not authorized for this platform",
        )

    tg.active_platform_id = payload.platform_id
    await db.commit()
    return {"status": "success", "message": "Active platform updated"}


@router.get("/learners", response_model=list[LearnerAdminResponse])
async def list_registered_learners(
    db: AsyncSession = Depends(get_db),
):
    """Lists registered learners, their phone verification status, and linked Telegram identity."""
    stmt = (
        select(User)
        .options(selectinload(User.phones), selectinload(User.telegram_account))
        .where(User.role == "learner")
        .order_by(User.created_at.desc())
    )
    res = await db.execute(stmt)
    users = res.scalars().all()

    result = []
    for u in users:
        primary_phone = u.phones[0].phone_number if u.phones else None
        phone_verified = u.phones[0].is_verified if u.phones else False
        tg_linked = u.telegram_account.is_verified if u.telegram_account else False
        tg_username = u.telegram_account.telegram_username if u.telegram_account else None

        result.append(
            LearnerAdminResponse(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                is_active=u.is_active,
                phone_number=primary_phone,
                phone_verified=phone_verified,
                telegram_linked=tg_linked,
                telegram_username=tg_username,
            )
        )
    return result
