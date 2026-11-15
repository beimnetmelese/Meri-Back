import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_session_context
from app.models.platform import Platform
from app.models.support import SupportMessage, SupportTicket
from app.models.user import User
from app.schemas.support import (
    SupportMessageCreate,
    SupportMessageResponse,
    SupportTicketCreate,
    SupportTicketResponse,
    SupportTicketStatusUpdate,
)
from app.services.websocket_manager import ws_manager

router = APIRouter()


def _to_ticket_response(ticket: SupportTicket) -> SupportTicketResponse:
    learner_name = ticket.learner.full_name if ticket.learner and ticket.learner.full_name else (ticket.learner.email if ticket.learner else "Learner")
    platform_name = ticket.platform.name if ticket.platform else "Platform"
    return SupportTicketResponse(
        id=ticket.id,
        platform_id=ticket.platform_id,
        learner_id=ticket.learner_id,
        conversation_id=ticket.conversation_id,
        assigned_agent_id=ticket.assigned_agent_id,
        subject=ticket.subject,
        status=ticket.status,
        consent_share_history=ticket.consent_share_history,
        screen_sharing_active=ticket.screen_sharing_active,
        created_at=ticket.created_at,
        messages=[SupportMessageResponse.model_validate(m) for m in ticket.messages],
        learner_name=learner_name,
        platform_name=platform_name,
    )


@router.post("/tickets", response_model=SupportTicketResponse, status_code=status.HTTP_201_CREATED)
async def create_support_ticket(
    payload: SupportTicketCreate,
    session: dict = Depends(get_session_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Submits a human assistance request.
    Respects consent rules for sharing conversation history and screen sharing flag.
    Associates request with the correct LMS platform (e.g. Savanna).
    """
    user_id = session.get("user_id")
    platform_id = session.get("platform_id") or payload.platform_id

    # If public_key provided, resolve platform
    if not platform_id and payload.public_key:
        plat_res = await db.execute(
            select(Platform).where(Platform.public_key == payload.public_key, Platform.enabled == True)
        )
        plat = plat_res.scalar_one_or_none()
        if plat:
            platform_id = plat.id

    # If still not resolved, try looking for the primary platform (e.g. Savanna)
    if not platform_id:
        plat_res = await db.execute(
            select(Platform.id).where(Platform.name.ilike("%savanna%")).limit(1)
        )
        platform_id = plat_res.scalar_one_or_none()
        if not platform_id:
            first_res = await db.execute(select(Platform.id).limit(1))
            platform_id = first_res.scalar_one_or_none() or ""

    if not user_id:
        learner_name = payload.learner_name.strip() if payload.learner_name else "Guest Learner"
        # Create or fetch guest user
        guest_res = await db.execute(select(User).where(User.email == "guest@bridgemate.internal"))
        guest = guest_res.scalar_one_or_none()
        if not guest:
            guest = User(
                email="guest@bridgemate.internal",
                full_name=learner_name,
                role="learner",
                status="approved",
                is_active=True,
            )
            db.add(guest)
            await db.flush()
        else:
            if payload.learner_name and guest.full_name != payload.learner_name:
                guest.full_name = payload.learner_name
                await db.flush()
        user_id = guest.id

    subject_text = payload.subject
    if payload.page_context and not payload.subject.startswith("["):
        subject_text = f"[{payload.page_context}] {payload.subject}"

    ticket = SupportTicket(
        platform_id=platform_id,
        learner_id=user_id,
        conversation_id=payload.conversation_id if payload.consent_share_history else None,
        subject=subject_text,
        status="open",
        consent_share_history=payload.consent_share_history,
        screen_sharing_active=payload.screen_sharing_active,
    )
    db.add(ticket)
    await db.flush()

    if payload.initial_message:
        msg = SupportMessage(
            ticket_id=ticket.id,
            sender_id=user_id,
            sender_role="learner",
            content=payload.initial_message,
        )
        db.add(msg)

    await db.commit()
    await db.refresh(ticket)

    # Reload with relations
    stmt = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.learner),
            selectinload(SupportTicket.platform),
        )
        .where(SupportTicket.id == ticket.id)
    )
    res = await db.execute(stmt)
    full_ticket = res.scalar_one()

    # Broadcast new ticket alert to platform & global support channels
    await ws_manager.broadcast(
        f"platform_{platform_id}",
        {
            "type": "new_support_ticket",
            "ticket_id": ticket.id,
            "subject": ticket.subject,
            "status": "open",
        },
    )

    return _to_ticket_response(full_ticket)


@router.get("/tickets", response_model=list[SupportTicketResponse])
async def list_support_tickets(
    session: dict = Depends(get_session_context),
    db: AsyncSession = Depends(get_db),
):
    user_id = session.get("user_id")
    platform_id = session.get("platform_id")
    role = session.get("role", "learner")

    stmt = select(SupportTicket).options(
        selectinload(SupportTicket.messages),
        selectinload(SupportTicket.learner),
        selectinload(SupportTicket.platform),
    )

    # Admins, superadmins, and platform admins see tickets
    if role in ["admin", "superadmin", "platform_admin", "support_agent"]:
        if platform_id:
            # Scoped strictly to their assigned platform (e.g. Savanna admin only sees Savanna tickets)
            stmt = stmt.where(SupportTicket.platform_id == platform_id)
    elif user_id:
        stmt = stmt.where(SupportTicket.learner_id == user_id)

    stmt = stmt.order_by(SupportTicket.created_at.desc())
    res = await db.execute(stmt)
    tickets = res.scalars().all()
    return [_to_ticket_response(t) for t in tickets]


@router.get("/tickets/{id}", response_model=SupportTicketResponse)
async def get_support_ticket(
    id: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.learner),
            selectinload(SupportTicket.platform),
        )
        .where(SupportTicket.id == id)
    )
    res = await db.execute(stmt)
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
        )
    return _to_ticket_response(ticket)


@router.post("/tickets/{id}/messages", response_model=SupportMessageResponse)
async def post_support_message(
    id: str,
    payload: SupportMessageCreate,
    session: dict = Depends(get_session_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SupportTicket).where(SupportTicket.id == id)
    res = await db.execute(stmt)
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
        )

    user_id = session.get("user_id")
    role = session.get("role", "learner")
    sender_role = "support_agent" if role in ["admin", "superadmin", "platform_admin", "support_agent"] else "learner"

    if not user_id:
        user_id = ticket.learner_id

    message = SupportMessage(
        ticket_id=ticket.id,
        sender_id=user_id,
        sender_role=sender_role,
        content=payload.content,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Broadcast via websocket to ticket room
    await ws_manager.broadcast(
        f"support_{ticket.id}",
        {
            "type": "support_message",
            "message_id": message.id,
            "sender_role": sender_role,
            "content": payload.content,
        },
    )

    return message


@router.patch("/tickets/{id}/status", response_model=SupportTicketResponse)
async def update_ticket_status(
    id: str,
    payload: SupportTicketStatusUpdate,
    session: dict = Depends(get_session_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SupportTicket)
        .options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.learner),
            selectinload(SupportTicket.platform),
        )
        .where(SupportTicket.id == id)
    )
    res = await db.execute(stmt)
    ticket = res.scalar_one_or_none()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
        )

    ticket.status = payload.status
    if payload.status == "in_progress" and session.get("user_id"):
        ticket.assigned_agent_id = session.get("user_id")

    await db.commit()
    await db.refresh(ticket)

    # Broadcast status update
    await ws_manager.broadcast(
        f"support_{ticket.id}",
        {
            "type": "ticket_status_updated",
            "ticket_id": ticket.id,
            "status": ticket.status,
            "assigned_agent_id": ticket.assigned_agent_id,
        },
    )

    return _to_ticket_response(ticket)
