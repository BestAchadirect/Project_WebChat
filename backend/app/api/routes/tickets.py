from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.ticket import TicketRead, TicketUpdate, TicketListResponse
from app.services.tickets.service import TicketService
from app.utils.pagination import normalize_pagination

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

@router.get("/all", response_model=TicketListResponse)
async def list_all_tickets(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=9999),
    db: AsyncSession = Depends(get_db)
) -> TicketListResponse:
    if "limit" in request.query_params or "offset" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="limit/offset pagination is no longer supported. Use page and pageSize.",
        )

    service = TicketService(db)
    tickets, total = await service.get_all_tickets(page=page, page_size=page_size)
    safe_page, total_pages, _ = normalize_pagination(
        total_items=total,
        page=page,
        page_size=page_size,
    )
    if safe_page != page:
        tickets, _ = await service.get_all_tickets(page=safe_page, page_size=page_size)
    for t in tickets:
        t.image_url = _absolute_image_url(request, t.image_url)
        if t.image_urls:
            t.image_urls = [_absolute_image_url(request, url) for url in t.image_urls if url]
    return TicketListResponse(
        items=tickets,
        totalItems=total,
        page=safe_page,
        pageSize=page_size,
        totalPages=total_pages,
    )

@router.get("/unread/count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = TicketService(db)
    count = await service.get_admin_unread_count()
    return {"count": count}

@router.post("/{ticket_id}/customer-open", response_model=TicketRead)
async def mark_customer_open(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
) -> TicketRead:
    service = TicketService(db)
    ticket = await service.mark_customer_open(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.image_url = _absolute_image_url(request, ticket.image_url)
    if ticket.image_urls:
        ticket.image_urls = [_absolute_image_url(request, url) for url in ticket.image_urls if url]
    return ticket

@router.post("/{ticket_id}/mark-read", response_model=TicketRead)
async def mark_admin_read(
    request: Request,
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
) -> TicketRead:
    service = TicketService(db)
    ticket = await service.mark_admin_read(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.image_url = _absolute_image_url(request, ticket.image_url)
    if ticket.image_urls:
        ticket.image_urls = [_absolute_image_url(request, url) for url in ticket.image_urls if url]
    return ticket

@router.patch("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    request: Request,
    ticket_id: int,
    description: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    ai_summary: Optional[str] = Form(None),
    admin_reply: Optional[str] = Form(None),
    actor: Optional[str] = Form(None),
    images: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db)
) -> TicketRead:
    service = TicketService(db)
    effective_actor = actor or ("admin" if any(v is not None for v in (status, ai_summary, admin_reply)) else "customer")
    if effective_actor not in {"admin", "customer"}:
        raise HTTPException(status_code=400, detail="Invalid actor. Use 'admin' or 'customer'.")
    updates = TicketUpdate(
        description=description,
        status=status,
        ai_summary=ai_summary,
        admin_reply=admin_reply,
    )
    ticket = await service.update_ticket(ticket_id, updates, images, actor=effective_actor)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.image_url = _absolute_image_url(request, ticket.image_url)
    if ticket.image_urls:
        ticket.image_urls = [_absolute_image_url(request, url) for url in ticket.image_urls if url]
    return ticket
