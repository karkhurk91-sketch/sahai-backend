"""
Media upload service for WhatsApp Cloud API integration
Handles file uploads, validation, and WhatsApp message transmission
"""

import asyncio
import hashlib
import logging
from typing import Optional, BinaryIO, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

import httpx
from pathlib import Path

# Assuming these imports exist in your project – adjust if needed
from core.service_layer import BaseService, retry
from common.exceptions import MediaUploadException, WhatsAppAPIException, ValidationException


class MediaType(str, Enum):
    """Supported media types"""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class MediaMimeType:
    """MIME type mappings and validation"""
    TYPES = {
        MediaType.IMAGE: ["image/jpeg", "image/png", "image/gif", "image/webp"],
        MediaType.VIDEO: ["video/mp4", "video/quicktime", "video/3gpp"],
        MediaType.AUDIO: ["audio/mpeg", "audio/wav", "audio/ogg", "audio/aac", "audio/amr"],
        MediaType.DOCUMENT: [
            "application/pdf", "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain", "text/csv"
        ]
    }
    
    @staticmethod
    def validate(mime_type: str) -> MediaType:
        """Validate and get media type from MIME type"""
        for media_type, mime_types in MediaMimeType.TYPES.items():
            if mime_type in mime_types:
                return media_type
        raise ValidationException(f"Unsupported media type: {mime_type}")


class Service(BaseService):
    """
    Handles media upload and WhatsApp Cloud API integration
    
    Features:
    - File validation (type, size, filename)
    - Upload to WhatsApp Cloud API
    - Metadata persistence
    - Async processing with retry
    - Deduplication via file hash
    - Sending media messages
    
    WhatsApp API limits:
    - Image: 5 MB (JPEG, PNG, JPG, WEBP)
    - Video: 16 MB (MP4, 3GPP)
    - Audio: 16 MB (AAC, MP4, MPEG, AMR, OGG - Opus)
    - Document: 100 MB (PDF, DOC, XLS, PPT, TXT, etc.)
    """
    
    # WhatsApp official size limits
    MAX_IMAGE_SIZE = 5 * 1024 * 1024      # 5 MB
    MAX_VIDEO_SIZE = 16 * 1024 * 1024     # 16 MB
    MAX_AUDIO_SIZE = 16 * 1024 * 1024     # 16 MB
    MAX_DOCUMENT_SIZE = 100 * 1024 * 1024 # 100 MB
    
    SIZE_LIMITS = {
        MediaType.IMAGE: MAX_IMAGE_SIZE,
        MediaType.VIDEO: MAX_VIDEO_SIZE,
        MediaType.AUDIO: MAX_AUDIO_SIZE,
        MediaType.DOCUMENT: MAX_DOCUMENT_SIZE,
    }
    
    def __init__(self, repository, logger, whatsapp_config: Dict[str, str]):
        """
        Initialize media service
        
        Args:
            repository: Media repository (must have create, find_one, delete_old methods)
            logger: Logger instance
            whatsapp_config: WhatsApp API config
                - access_token (required)
                - phone_number_id (required)
                - api_version (default: v21.0)
                - api_url (default: https://graph.facebook.com)
        """
        super().__init__(repository, logger)
        self.whatsapp_config = whatsapp_config
        self.whatsapp_api_url = (
            f"{whatsapp_config.get('api_url', 'https://graph.facebook.com')}"
            f"/{whatsapp_config.get('api_version', 'v21.0')}"
        )
        self.phone_number_id = whatsapp_config.get('phone_number_id')
        if not self.phone_number_id:
            raise ValueError("whatsapp_config must contain 'phone_number_id'")
        if not whatsapp_config.get('access_token'):
            raise ValueError("whatsapp_config must contain 'access_token'")
    
    async def validate_file(
        self,
        file: BinaryIO,
        filename: str,
        mime_type: str
    ) -> MediaType:
        """
        Validate uploaded file type, size, and filename
        
        Args:
            file: File object (supports seek, tell, read)
            filename: Original filename
            mime_type: File MIME type from client
        
        Returns:
            Validated MediaType
        
        Raises:
            ValidationException if validation fails
        """
        # Validate MIME type against supported types
        media_type = MediaMimeType.validate(mime_type)
        
        # Get file size
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to start
        
        # Validate file size against WhatsApp limits
        max_size = self.SIZE_LIMITS[media_type]
        if file_size > max_size:
            raise ValidationException(
                f"File size exceeds limit for {media_type.value}: "
                f"{file_size / 1024 / 1024:.1f}MB / {max_size / 1024 / 1024:.1f}MB"
            )
        
        # Basic filename validation
        if not filename or len(filename) > 255:
            raise ValidationException("Invalid filename (empty or too long)")
        
        self.logger.info(
            f"File validated: {filename}, type={media_type.value}, size={file_size} bytes, mime={mime_type}"
        )
        
        return media_type
    
    async def calculate_file_hash(self, file: BinaryIO) -> str:
        """
        Calculate SHA-256 hash of file for deduplication
        
        Args:
            file: File object (will be reset to start after calculation)
        
        Returns:
            Hex hash string
        """
        file.seek(0)
        sha256_hash = hashlib.sha256()
        
        for chunk in iter(lambda: file.read(4096), b""):
            sha256_hash.update(chunk)
        
        file.seek(0)
        return sha256_hash.hexdigest()
    
    async def upload_to_whatsapp(
        self,
        file: BinaryIO,
        media_type: MediaType,
        filename: str,
        actual_mime_type: str
    ) -> str:
        """
        Upload file to WhatsApp Cloud API with retry
        
        Args:
            file: File object
            media_type: Type of media (for logging)
            filename: Original filename
            actual_mime_type: The real MIME type from client (e.g., 'image/png')
        
        Returns:
            WhatsApp media ID
        
        Raises:
            WhatsAppAPIException on upload failure after retries
        """
        # Correct endpoint: /{phone-number-id}/media
        url = f"{self.whatsapp_api_url}/{self.phone_number_id}/media"
        
        # Required form-data fields
        data = {
            'messaging_product': 'whatsapp',
            'type': actual_mime_type,
        }
        
        files = {
            'file': (filename, file, actual_mime_type)
        }
        
        headers = {
            'Authorization': f"Bearer {self.whatsapp_config['access_token']}"
        }
        
        # Use the retry decorator logic (async-compatible)
        max_attempts = 3
        backoff = 1.0
        
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    response = await client.post(
                        url,
                        data=data,
                        files=files,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        media_id = result.get('id')  # Correct field: "id", not "h"
                        if not media_id:
                            raise WhatsAppAPIException("Upload response missing 'id' field")
                        
                        self.logger.info(
                            f"WhatsApp upload successful: media_id={media_id}, "
                            f"type={media_type.value}, filename={filename}"
                        )
                        return media_id
                    
                    # Non-200 response: log full error details
                    error_detail = response.text
                    self.logger.error(
                        f"WhatsApp upload failed (attempt {attempt}/{max_attempts}): "
                        f"status={response.status_code}, response={error_detail}"
                    )
                    
                    # If last attempt, raise exception
                    if attempt == max_attempts:
                        raise WhatsAppAPIException(
                            f"Upload failed after {max_attempts} attempts: {error_detail}"
                        )
                    
                    # Wait before retry (exponential backoff)
                    await asyncio.sleep(backoff * (2 ** (attempt - 1)))
                    
            except httpx.RequestError as e:
                self.logger.error(f"Network error on attempt {attempt}: {str(e)}")
                if attempt == max_attempts:
                    raise WhatsAppAPIException(f"Upload request failed: {str(e)}")
                await asyncio.sleep(backoff * (2 ** (attempt - 1)))
        
        # Should never reach here
        raise WhatsAppAPIException("Upload failed unexpectedly")
    
    async def create_media_record(
        self,
        file: BinaryIO,
        filename: str,
        media_type: MediaType,
        mime_type: str,
        organization_id: UUID,
        conversation_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Create media database record (deduplicates by file hash)
        
        Args:
            file: File object (will be read and reset)
            filename: Original filename
            media_type: Type of media (validated)
            mime_type: Actual MIME type
            organization_id: Organization ID
            conversation_id: Optional conversation ID
            user_id: Optional user ID
        
        Returns:
            Media record dict with all metadata (including existing if duplicate)
        """
        # Calculate file hash for deduplication
        file_hash = await self.calculate_file_hash(file)
        
        # Check for existing media with same hash in this org
        existing = await self.repo.find_one(
            organization_id=organization_id,
            file_hash=file_hash
        )
        
        if existing:
            self.logger.info(
                f"Duplicate media detected: hash={file_hash}, "
                f"existing_media_id={existing.id}, reusing"
            )
            return existing.to_dict()
        
        # Get file size (file is at position 0 after hash calculation)
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        # Upload to WhatsApp (uses actual mime type)
        whatsapp_media_id = await self.upload_to_whatsapp(
            file, media_type, filename, mime_type
        )
        
        # Create database record
        media = await self.repo.create(
            organization_id=organization_id,
            conversation_id=conversation_id,
            uploaded_by=user_id,
            file_name=filename,
            media_type=media_type.value,
            mime_type=mime_type,
            file_size=file_size,
            file_hash=file_hash,
            whatsapp_media_id=whatsapp_media_id,
            upload_status="uploaded",
            uploaded_at=datetime.now(),
        )
        
        self.logger.info(
            f"Media record created: id={media.id}, whatsapp_id={whatsapp_media_id}, "
            f"org={organization_id}, file={filename}"
        )
        
        return media.to_dict()
    
    async def send_media_message(
        self,
        recipient_phone: str,
        media_id: str,
        media_type: MediaType,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send media message via WhatsApp Cloud API
        
        Args:
            recipient_phone: Recipient phone number (international format, no '+' sign)
            media_id: WhatsApp media ID returned from upload
            media_type: Type of media (image, video, audio, document)
            caption: Optional caption (not supported for audio)
        
        Returns:
            WhatsApp API response JSON
        
        Raises:
            WhatsAppAPIException on send failure
        """
        # Correct endpoint: /{phone-number-id}/messages
        url = f"{self.whatsapp_api_url}/{self.phone_number_id}/messages"
        
        # Build media object
        media_object = {
            'id': media_id
        }
        # Caption is allowed for image, video, document (not audio)
        if caption and media_type != MediaType.AUDIO:
            media_object['caption'] = caption
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': recipient_phone,
            'type': media_type.value,
            media_type.value: media_object
        }
        
        headers = {
            'Authorization': f"Bearer {self.whatsapp_config['access_token']}",
            'Content-Type': 'application/json'
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                # WhatsApp returns 200 or 201 for success
                if response.status_code not in (200, 201):
                    error_detail = response.text
                    self.logger.error(
                        f"WhatsApp send failed: status={response.status_code}, "
                        f"response={error_detail}, recipient={recipient_phone}"
                    )
                    raise WhatsAppAPIException(
                        f"Send message failed: {error_detail}"
                    )
                
                result = response.json()
                message_id = result.get('messages', [{}])[0].get('id')
                self.logger.info(
                    f"Media message sent: message_id={message_id}, "
                    f"media_id={media_id}, type={media_type.value}, "
                    f"recipient={recipient_phone}"
                )
                return result
                
        except httpx.RequestError as e:
            self.logger.error(f"Network error sending message: {str(e)}")
            raise WhatsAppAPIException(f"Send request failed: {str(e)}")
    
    async def cleanup_old_uploads(self, days_old: int = 30) -> int:
        """
        Clean up old temporary uploads (only metadata, WhatsApp retains media for 30 days)
        
        Args:
            days_old: Delete records older than this many days
        
        Returns:
            Number of deleted records
        """
        deleted = await self.repo.delete_old(days=days_old)
        self.logger.info(f"Cleaned up {deleted} old media records (older than {days_old} days)")
        return deleted