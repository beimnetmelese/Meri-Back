from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token, verify_secret_key
from app.models.platform import Platform
from app.models.user import User

security_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
            )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    return user


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "superadmin", "platform_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )
    return current_user


async def get_current_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SuperAdmin privileges required",
        )
    return current_user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except Exception:
        return None


async def get_platform_from_public_key(
    public_key: str,
    db: AsyncSession = Depends(get_db),
) -> Platform:
    stmt = select(Platform).where(Platform.public_key == public_key, Platform.enabled == True)
    result = await db.execute(stmt)
    platform = result.scalar_one_or_none()
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Platform not found or integration is disabled",
        )
    return platform


async def get_authenticated_platform(
    x_platform_key: str | None = Header(None, alias="X-Platform-Key"),
    x_platform_secret: str | None = Header(None, alias="X-Platform-Secret"),
    db: AsyncSession = Depends(get_db),
) -> Platform:
    """Verifies server-to-server platform integration credentials."""
    if not x_platform_key or not x_platform_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Platform-Key or X-Platform-Secret headers",
        )

    stmt = select(Platform).where(Platform.public_key == x_platform_key, Platform.enabled == True)
    result = await db.execute(stmt)
    platform = result.scalar_one_or_none()
    if not platform or not verify_secret_key(x_platform_secret, platform.secret_key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid platform integration credentials",
        )
    return platform


async def get_session_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    x_public_key: str | None = Header(None, alias="X-Public-Key"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Extracts platform and user identity from Bearer token if present,
    or falls back to public platform key for anonymous guest learners on public LMS.
    """
    if credentials:
        try:
            payload = decode_token(credentials.credentials)
            user_id = payload.get("sub")
            platform_id = payload.get("platform_id")
            role = payload.get("role", "learner")
            return {
                "user_id": user_id,
                "platform_id": platform_id,
                "role": role,
                "is_authenticated": True,
            }
        except Exception:
            pass

    # If public key header provided (e.g., initial widget guest session)
    if x_public_key:
        stmt = select(Platform).where(Platform.public_key == x_public_key, Platform.enabled == True)
        res = await db.execute(stmt)
        plat = res.scalar_one_or_none()
        if plat:
            return {
                "user_id": None,
                "platform_id": plat.id,
                "role": "guest",
                "is_authenticated": False,
            }

    # Default fallback
    return {
        "user_id": None,
        "platform_id": None,
        "role": "guest",
        "is_authenticated": False,
    }
