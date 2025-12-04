"""Supabase Storage Service for file management."""
from typing import Optional
from uuid import UUID
from fastapi import UploadFile, HTTPException
from supabase import create_client, Client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class SupabaseStorageService:
    """Service for managing files in Supabase Storage."""
    
    def __init__(self):
        """Initialize Supabase client."""
        try:
            self.client: Client = create_client(
                supabase_url=settings.SUPABASE_URL,
                supabase_key=settings.SUPABASE_SERVICE_KEY
            )
            self.bucket_name = settings.SUPABASE_BUCKET
            logger.info(f"Supabase Storage Service initialized with bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    async def upload_file(
        self, 
        file: UploadFile, 
        document_id: UUID
    ) -> str:
        """
        Upload file to Supabase Storage.
        
        Args:
            file: UploadFile object from FastAPI
            document_id: UUID of the document
        
        Returns:
            Storage path of the uploaded file
        """
        try:
            # Read file content
            file_content = await file.read()
            
            # Generate storage path
            storage_path = f"{document_id}/{file.filename}"
            
            # Upload to Supabase Storage
            response = self.client.storage.from_(self.bucket_name).upload(
                path=storage_path,
                file=file_content,
                file_options={"content-type": file.content_type or "application/octet-stream"}
            )
            
            logger.info(f"File uploaded successfully: {storage_path}")
            return storage_path
            
        except Exception as e:
            logger.error(f"Error uploading file to Supabase: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file: {str(e)}"
            )
    
    async def download_file(self, storage_path: str) -> bytes:
        """
        Download file from Supabase Storage.
        
        Args:
            storage_path: Path to the file in storage
        
        Returns:
            File content as bytes
        """
        try:
            response = self.client.storage.from_(self.bucket_name).download(
                path=storage_path
            )
            logger.info(f"File downloaded successfully: {storage_path}")
            return response
            
        except Exception as e:
            logger.error(f"Error downloading file from Supabase: {e}")
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {storage_path}"
            )
    
    async def delete_file(self, storage_path: str) -> bool:
        """
        Delete file from Supabase Storage.
        
        Args:
            storage_path: Path to the file in storage
        
        Returns:
            True if deleted successfully
        """
        try:
            self.client.storage.from_(self.bucket_name).remove(
                paths=[storage_path]
            )
            logger.info(f"File deleted successfully: {storage_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file from Supabase: {e}")
            # Don't raise exception for delete failures
            return False
    
    async def get_signed_url(
        self, 
        storage_path: str, 
        expires_in: int = 3600
    ) -> str:
        """
        Generate a signed URL for temporary file access.
        
        Args:
            storage_path: Path to the file in storage
            expires_in: URL expiration time in seconds (default: 1 hour)
        
        Returns:
            Signed URL string
        """
        try:
            response = self.client.storage.from_(self.bucket_name).create_signed_url(
                path=storage_path,
                expires_in=expires_in
            )
            
            if isinstance(response, dict) and 'signedURL' in response:
                signed_url = response['signedURL']
            else:
                signed_url = response
            
            logger.info(f"Signed URL generated for: {storage_path}")
            return signed_url
            
        except Exception as e:
            logger.error(f"Error generating signed URL: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate download URL: {str(e)}"
            )
    
    async def file_exists(self, storage_path: str) -> bool:
        """
        Check if a file exists in storage.
        
        Args:
            storage_path: Path to the file in storage
        
        Returns:
            True if file exists, False otherwise
        """
        try:
            # List files in the directory
            directory = "/".join(storage_path.split("/")[:-1])
            files = self.client.storage.from_(self.bucket_name).list(
                path=directory
            )
            
            # Check if our file is in the list
            filename = storage_path.split("/")[-1]
            return any(f.get('name') == filename for f in files)
            
        except Exception as e:
            logger.warning(f"Error checking file existence: {e}")
            return False
    
    async def get_public_url(self, storage_path: str) -> str:
        """
        Get public URL for a file (if bucket is public).
        
        Args:
            storage_path: Path to the file in storage
        
        Returns:
            Public URL string
        """
        try:
            response = self.client.storage.from_(self.bucket_name).get_public_url(
                path=storage_path
            )
            return response
            
        except Exception as e:
            logger.error(f"Error getting public URL: {e}")
            # Fall back to signed URL
            return await self.get_signed_url(storage_path)


# Singleton instance
supabase_storage = SupabaseStorageService()
