"""Supabase Storage Service for file management."""
from typing import Optional
from uuid import UUID
import io
import asyncio
import httpx
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

    async def upload_file_bytes(
        self,
        *,
        file_content: bytes,
        filename: str,
        document_id: UUID,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload raw bytes to Supabase Storage in a non-blocking way by running
        the synchronous client call in a threadpool. Returns a public URL
        or storage path on success.
        """
        storage_path = f"{document_id}/{filename}"

        def _sync_upload():
            try:
                # Use same upload signature as in upload_file
                response = self.client.storage.from_(self.bucket_name).upload(
                    path=storage_path,
                    file=file_content,
                    file_options={"content-type": content_type} if content_type else None,
                )

                # Attempt to get a public URL; adapt to client response shape
                pub = self.client.storage.from_(self.bucket_name).get_public_url(
                    path=storage_path
                )
                if isinstance(pub, dict):
                    return pub.get("publicURL") or pub.get("publicUrl") or storage_path
                return pub

            except Exception:
                # Re-raise to be caught by executor wrapper
                raise

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _sync_upload)
            logger.info(f"File uploaded successfully: {storage_path}")
            return result
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
            # If storage_path is a full URL (public URL), fetch it over HTTP
            if isinstance(storage_path, str) and storage_path.startswith("http"):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(storage_path)
                    if resp.status_code == 200:
                        logger.info(f"File downloaded successfully from URL: {storage_path}")
                        return resp.content
                    # If public URL fetch fails (private bucket or other), fall back
                    # to using the Supabase client download with the object path.
                    logger.warning(f"Public URL fetch failed ({resp.status_code}), falling back to SDK download: {resp.text}")
                    # Extract object path after '/storage/v1/object/public/{bucket}/'
                    from urllib.parse import urlparse
                    parsed = urlparse(storage_path)
                    path = parsed.path
                    marker = f"/storage/v1/object/public/{self.bucket_name}/"
                    if marker in path:
                        object_path = path.split(marker, 1)[1]
                    else:
                        # As a last resort, try to strip prefix up to bucket name
                        parts = path.split(f"/{self.bucket_name}/")
                        object_path = parts[-1] if len(parts) > 1 else path
                    def _sync_download():
                        return self.client.storage.from_(self.bucket_name).download(path=object_path)
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, _sync_download)
                    logger.info(f"File downloaded successfully via SDK: {object_path}")
                    return result

            # Otherwise, call the Supabase client download in a thread to avoid blocking
            def _sync_download():
                return self.client.storage.from_(self.bucket_name).download(path=storage_path)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _sync_download)
            logger.info(f"File downloaded successfully: {storage_path}")
            return result

        except HTTPException:
            raise
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
