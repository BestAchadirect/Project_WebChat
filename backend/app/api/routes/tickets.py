from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.ticket import TicketRead, TicketUpdate
from app.services.ticket_service import TicketService
from app.core.config import settings

router = APIRouter()

def _absolute_image_url(request: Request, image_url: Optional[str]) -> Optional[str]:
    if not image_url:
        return image_url
    if image_url.startswith("http"):
        return image_url
    
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        host = forwarded_host.split(",")[0].strip()
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        return f"{proto}://{host}{image_url}"
    
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{image_url}"

@router.post("/", response_model=TicketRead)
async def create_ticket(
    request: Request,
    user_id: str = Form(...),
    description: str = Form(...),
    images: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db)
) -> TicketRead:
    service = TicketService(db)
    user = await service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    ticket = await service.create_ticket(user_id, description, images)
    ticket.image_url = _absolute_image_url(request, ticket.image_url)
    if ticket.image_urls:
        ticket.image_urls = [_absolute_image_url(request, url) for url in ticket.image_urls if url]
    return ticket

@router.get("/", response_model=List[TicketRead])
async def list_tickets(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db)
) -> List[TicketRead]:
    service = TicketService(db)
    tickets = await service.get_tickets(user_id)
    for t in tickets:
        t.image_url = _absolute_image_url(request, t.image_url)
        if t.image_urls:
            t.image_urls = [_absolute_image_url(request, url) for url in t.image_urls if url]
    return tickets

@router.get("/all", response_model=List[TicketRead])
async def list_all_tickets(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> List[TicketRead]:
    service = TicketService(db)
    tickets = await service.get_all_tickets()
    for t in tickets:
        t.image_url = _absolute_image_url(request, t.image_url)
        if t.image_urls:
            t.image_urls = [_absolute_image_url(request, url) for url in t.image_urls if url]
    return tickets

@router.patch("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    request: Request,
    ticket_id: int,
    description: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    ai_summary: Optional[str] = Form(None),
    images: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db)
) -> TicketRead:
    service = TicketService(db)
    updates = TicketUpdate(
        description=description,
        status=status,
        ai_summary=ai_summary
    )
    ticket = await service.update_ticket(ticket_id, updates, images)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.image_url = _absolute_image_url(request, ticket.image_url)
    if ticket.image_urls:
        ticket.image_urls = [_absolute_image_url(request, url) for url in ticket.image_urls if url]
    return ticket
