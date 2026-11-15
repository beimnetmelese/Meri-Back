from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user_optional, get_current_admin
from app.models.user import User
from app.core.security import (
    generate_public_key,
    generate_secret_key,
    hash_secret_key,
    verify_secret_key,
)
from app.models.platform import Platform, PlatformConfiguration, PlatformDomain
from app.schemas.platform import (
    BrandingConfig,
    DomainAddRequest,
    FeaturesConfig,
    IntegrationVerifyRequest,
    IntegrationVerifyResponse,
    PlatformCreate,
    PlatformRegistrationResult,
    PlatformResponse,
    PlatformStatusUpdate,
    PluginConfigResponse,
    PluginConfigUpdate,
    RotateKeysResponse,
    ThemeConfig,
)

router = APIRouter()


@router.get("", response_model=list[PlatformResponse])
async def list_platforms(
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Lists registered platforms. Scoped to assigned platform if logged in as platform_admin."""
    stmt = (
        select(Platform)
        .options(selectinload(Platform.configuration), selectinload(Platform.domains))
        .order_by(Platform.created_at.desc())
    )
    if current_user and current_user.role == "platform_admin" and current_user.assigned_platform_id:
        stmt = stmt.where(Platform.id == current_user.assigned_platform_id)
    res = await db.execute(stmt)
    platforms = res.scalars().all()

    result = []
    for platform in platforms:
        domains = [d.domain for d in platform.domains]
        cfg = None
        if platform.configuration:
            c = platform.configuration
            cfg = PluginConfigResponse(
                platform_name=c.platform_name,
                theme=ThemeConfig(**c.theme),
                branding=BrandingConfig(**c.branding),
                welcome_message=c.welcome_message,
                language=c.language,
                position=c.position,
                size=c.size,
                features=FeaturesConfig(**c.features),
                context_extraction_rules=c.context_extraction_rules or {},
                public_key=platform.public_key,
            )
        result.append(
            PlatformResponse(
                id=platform.id,
                name=platform.name,
                domain=platform.domain,
                public_key=platform.public_key,
                enabled=platform.enabled,
                domains=domains,
                configuration=cfg,
            )
        )
    return result


@router.post("", response_model=PlatformRegistrationResult, status_code=status.HTTP_201_CREATED)
async def register_platform(
    payload: PlatformCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Registers a new platform. Generates public installation key and private integration key.
    The secret key is only revealed once upon creation!
    """
    # Check domain uniqueness
    existing = await db.execute(select(Platform).where(Platform.domain == payload.domain))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A platform with domain '{payload.domain}' is already registered.",
        )

    public_key = generate_public_key()
    plain_secret = generate_secret_key()
    secret_hash = hash_secret_key(plain_secret)

    platform = Platform(
        name=payload.name,
        domain=payload.domain,
        public_key=public_key,
        secret_key_hash=secret_hash,
        enabled=True,
    )
    db.add(platform)
    await db.flush()

    # Add primary domain
    primary_domain = PlatformDomain(
        platform_id=platform.id, domain=payload.domain, is_verified=True
    )
    db.add(primary_domain)

    for d in payload.allowed_domains or []:
        if d != payload.domain:
            db.add(PlatformDomain(platform_id=platform.id, domain=d, is_verified=True))

    # Initialize configuration
    init_cfg = payload.initial_config or PluginConfigUpdate()
    config = PlatformConfiguration(
        platform_id=platform.id,
        platform_name=init_cfg.platform_name or payload.name,
        theme=init_cfg.theme.model_dump() if init_cfg.theme else ThemeConfig().model_dump(),
        branding=init_cfg.branding.model_dump()
        if init_cfg.branding
        else BrandingConfig().model_dump(),
        welcome_message=init_cfg.welcome_message
        or "Hello! How can I assist your learning and career today?",
        language=init_cfg.language or "en",
        position=init_cfg.position or "bottom-right",
        size=init_cfg.size or "medium",
        features=init_cfg.features.model_dump()
        if init_cfg.features
        else FeaturesConfig().model_dump(),
        context_extraction_rules=init_cfg.context_extraction_rules or {},
    )
    db.add(config)
    await db.commit()

    return PlatformRegistrationResult(
        id=platform.id,
        name=platform.name,
        domain=platform.domain,
        public_key=platform.public_key,
        secret_key=plain_secret,
        enabled=platform.enabled,
        domains=[payload.domain] + (payload.allowed_domains or []),
        configuration=PluginConfigResponse(
            platform_name=config.platform_name,
            theme=ThemeConfig(**config.theme),
            branding=BrandingConfig(**config.branding),
            welcome_message=config.welcome_message,
            language=config.language,
            position=config.position,
            size=config.size,
            features=FeaturesConfig(**config.features),
            context_extraction_rules=config.context_extraction_rules,
            public_key=platform.public_key,
        ),
    )


@router.get("/{id}", response_model=PlatformResponse)
async def get_platform_details(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Platform)
        .options(selectinload(Platform.configuration), selectinload(Platform.domains))
        .where(Platform.id == id)
    )
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()
    if not platform:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")

    domains = [d.domain for d in platform.domains]
    cfg = None
    if platform.configuration:
        c = platform.configuration
        cfg = PluginConfigResponse(
            platform_name=c.platform_name,
            theme=ThemeConfig(**c.theme),
            branding=BrandingConfig(**c.branding),
            welcome_message=c.welcome_message,
            language=c.language,
            position=c.position,
            size=c.size,
            features=FeaturesConfig(**c.features),
            context_extraction_rules=c.context_extraction_rules or {},
            public_key=platform.public_key,
        )

    return PlatformResponse(
        id=platform.id,
        name=platform.name,
        domain=platform.domain,
        public_key=platform.public_key,
        enabled=platform.enabled,
        domains=domains,
        configuration=cfg,
    )


@router.patch("/{id}/plugin-config", response_model=PluginConfigResponse)
async def update_platform_plugin_config(
    id: str,
    update: PluginConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Dynamically updates plugin colors, branding, and features.
    Changes apply to all installed widgets in real time without rebuilding the frontend bundle.
    """
    stmt = select(Platform).options(selectinload(Platform.configuration)).where(Platform.id == id)
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()
    if not platform:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")

    config = platform.configuration
    if not config:
        config = PlatformConfiguration(platform_id=platform.id)
        db.add(config)

    if update.platform_name is not None:
        config.platform_name = update.platform_name
    if update.theme is not None:
        config.theme = update.theme.model_dump()
    if update.branding is not None:
        config.branding = update.branding.model_dump()
    if update.welcome_message is not None:
        config.welcome_message = update.welcome_message
    if update.language is not None:
        config.language = update.language
    if update.position is not None:
        config.position = update.position
    if update.size is not None:
        config.size = update.size
    if update.features is not None:
        config.features = update.features.model_dump()
    if update.context_extraction_rules is not None:
        config.context_extraction_rules = update.context_extraction_rules

    await db.commit()

    return PluginConfigResponse(
        platform_name=config.platform_name,
        theme=ThemeConfig(**config.theme),
        branding=BrandingConfig(**config.branding),
        welcome_message=config.welcome_message,
        language=config.language,
        position=config.position,
        size=config.size,
        features=FeaturesConfig(**config.features),
        context_extraction_rules=config.context_extraction_rules or {},
        public_key=platform.public_key,
    )


@router.post("/{id}/rotate-keys", response_model=RotateKeysResponse)
async def rotate_platform_keys(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generates a new private secret integration key for the platform."""
    stmt = select(Platform).where(Platform.id == id)
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()
    if not platform:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")

    new_secret = generate_secret_key()
    platform.secret_key_hash = hash_secret_key(new_secret)
    await db.commit()

    return RotateKeysResponse(
        id=platform.id,
        public_key=platform.public_key,
        secret_key=new_secret,
        message="Integration credentials successfully rotated. Update your backend environment variables with the new secret key.",
    )


@router.patch("/{id}/status", response_model=PlatformResponse)
async def update_platform_status(
    id: str,
    payload: PlatformStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Enables or disables a platform integration."""
    stmt = (
        select(Platform)
        .options(selectinload(Platform.configuration), selectinload(Platform.domains))
        .where(Platform.id == id)
    )
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()
    if not platform:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")

    platform.enabled = payload.enabled
    await db.commit()
    await db.refresh(platform)

    domains = [d.domain for d in platform.domains]
    cfg = None
    if platform.configuration:
        c = platform.configuration
        cfg = PluginConfigResponse(
            platform_name=c.platform_name,
            theme=ThemeConfig(**c.theme),
            branding=BrandingConfig(**c.branding),
            welcome_message=c.welcome_message,
            language=c.language,
            position=c.position,
            size=c.size,
            features=FeaturesConfig(**c.features),
            context_extraction_rules=c.context_extraction_rules or {},
            public_key=platform.public_key,
        )

    return PlatformResponse(
        id=platform.id,
        name=platform.name,
        domain=platform.domain,
        public_key=platform.public_key,
        enabled=platform.enabled,
        domains=domains,
        configuration=cfg,
    )


@router.post("/{id}/domains")
async def add_platform_domain(
    id: str,
    payload: DomainAddRequest,
    db: AsyncSession = Depends(get_db),
):
    """Adds an authorized origin domain for the platform."""
    stmt = select(Platform).where(Platform.id == id)
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()
    if not platform:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform not found")

    existing = await db.execute(
        select(PlatformDomain).where(
            PlatformDomain.platform_id == id,
            PlatformDomain.domain == payload.domain,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "ok", "message": "Domain already registered", "domain": payload.domain}

    domain_obj = PlatformDomain(platform_id=id, domain=payload.domain, is_verified=True)
    db.add(domain_obj)
    await db.commit()
    return {"status": "ok", "message": "Domain added successfully", "domain": payload.domain}


@router.delete("/{id}/domains/{domain_id}")
async def delete_platform_domain(
    id: str,
    domain_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Removes an authorized domain from the platform."""
    stmt = select(PlatformDomain).where(
        PlatformDomain.platform_id == id,
        (PlatformDomain.id == domain_id) | (PlatformDomain.domain == domain_id),
    )
    res = await db.execute(stmt)
    dom = res.scalar_one_or_none()
    if not dom:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    await db.delete(dom)
    await db.commit()
    return {"status": "ok", "message": "Domain removed"}



@router.post("/integrations/verify", response_model=IntegrationVerifyResponse)
async def verify_integration(
    payload: IntegrationVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verifies that platform public and private keys are valid and origin domain matches."""
    stmt = select(Platform).where(Platform.public_key == payload.public_key)
    res = await db.execute(stmt)
    platform = res.scalar_one_or_none()

    if not platform or not verify_secret_key(payload.secret_key, platform.secret_key_hash):
        return IntegrationVerifyResponse(
            verified=False,
            platform_id="",
            platform_name="",
            message="Invalid public key or secret key",
        )

    # Check domain
    domain_stmt = select(PlatformDomain).where(
        PlatformDomain.platform_id == platform.id,
        PlatformDomain.domain == payload.domain,
    )
    dom_res = await db.execute(domain_stmt)
    if (
        not dom_res.scalar_one_or_none()
        and platform.domain != payload.domain
        and payload.domain not in ["localhost", "127.0.0.1"]
    ):
        return IntegrationVerifyResponse(
            verified=False,
            platform_id=platform.id,
            platform_name=platform.name,
            message=f"Domain '{payload.domain}' is not authorized for this platform",
        )

    return IntegrationVerifyResponse(
        verified=True,
        platform_id=platform.id,
        platform_name=platform.name,
        message="Integration credentials successfully verified",
    )
