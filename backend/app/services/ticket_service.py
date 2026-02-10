import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.ticket import Ticket
from app.models.chat import AppUser
from app.schemas.ticket import TicketUpdate
from app.core.config import settings
from app.services.llm_service import LLMService

class TicketService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()

    @staticmethod
    def _resolve_uploads_dir() -> Path:
        return Path(settings.UPLOAD_DIR).resolve()

    async def create_ticket(
        self, 
        user_id: str, 
        description: str, 
        images: Optional[List[UploadFile]] = None
    ) -> Ticket:
        image_urls = []
        upload_dir = self._resolve_uploads_dir() / "tickets"
        upload_dir.mkdir(parents=True, exist_ok=True)

        if images:
            for image in images:
                suffix = Path(image.filename or "").suffix or ".jpg"
                filename = f"ticket_{uuid.uuid4().hex}{suffix}"
                dest = upload_dir / filename
                contents = await image.read()
                dest.write_bytes(contents)
                image_urls.append(f"/uploads/tickets/{filename}")

        # Generate AI Summary
        prompt = f"""
        User reported an issue:
        "{description}"
        
        Please provide a short, professional summary of this report for a customer support ticket.
        Mention that we have received their report and are looking into it.
        Keep it concise (1-3 sentences).
        """
        ai_summary = await self.llm.generate_chat_response([{"role": "user", "content": prompt}])

        ticket = Ticket(
            user_id=user_id,
            description=description,
            image_url=image_urls[0] if image_urls else None,
            image_urls=image_urls,
            ai_summary=ai_summary,
            status="pending"
        )
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_tickets(self, user_id: str) -> List[Ticket]:
        query = select(Ticket).where(Ticket.user_id == user_id).order_by(Ticket.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_tickets(self) -> List[Ticket]:
        query = select(Ticket).order_by(Ticket.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_ticket(
        self, 
        ticket_id: int, 
        updates: TicketUpdate,
        images: Optional[List[UploadFile]] = None
    ) -> Optional[Ticket]:
        ticket = await self.db.get(Ticket, ticket_id)
        if not ticket:
            return None
        
        if updates.status is not None:
            ticket.status = updates.status
        if updates.ai_summary is not None:
            ticket.ai_summary = updates.ai_summary
        
        if updates.description is not None:
            ticket.description = updates.description
            # Re-generate AI Summary if description changes
            prompt = f"""
            User updated their report:
            "{updates.description}"
            
            Please provide a short, professional summary of this updated report for a customer support ticket.
            Keep it concise (1-3 sentences).
            """
            ticket.ai_summary = await self.llm.generate_chat_response([{"role": "user", "content": prompt}])

        if images:
            new_image_urls = []
            upload_dir = self._resolve_uploads_dir() / "tickets"
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            for image in images:
                suffix = Path(image.filename or "").suffix or ".jpg"
                filename = f"ticket_{uuid.uuid4().hex}{suffix}"
                dest = upload_dir / filename
                contents = await image.read()
                dest.write_bytes(contents)
                new_image_urls.append(f"/uploads/tickets/{filename}")
            
            # Combine or replace? User said "upload or update", if they upload more, we should probably append or replace based on intent.
            # Usually "Update detail" with new images replaces the old ones, or appends.
            # Given the request "multiple image upload", I'll append to existing image_urls if they exist.
            current_urls = ticket.image_urls or []
            if ticket.image_url and ticket.image_url not in current_urls:
                current_urls.append(ticket.image_url)
            
            updated_urls = current_urls + new_image_urls
            ticket.image_urls = updated_urls
            ticket.image_url = updated_urls[0] if updated_urls else None
        elif updates.image_url is not None:
            ticket.image_url = updates.image_url
        
        if updates.image_urls is not None:
            ticket.image_urls = updates.image_urls
            
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_user(self, user_id: str) -> Optional[AppUser]:
        return await self.db.get(AppUser, user_id)
