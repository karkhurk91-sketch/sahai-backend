import asyncio
import functools
from typing import Callable, Any, Optional
from modules.common.logger import get_logger

logger = get_logger(__name__)

def retry_async(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator for retrying async functions with exponential backoff.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        wait_time = delay * (backoff ** attempt)
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator

# WhatsApp constants
DOCUMENT_MIME_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain'
}

MAX_ATTACHMENT_SIZES = {
    'image': 5 * 1024 * 1024,
    'video': 16 * 1024 * 1024,
    'audio': 10 * 1024 * 1024,
    'document': 100 * 1024 * 1024,
}

def get_media_type_and_limit(content_type: str, filename: str = '') -> tuple[Optional[str], Optional[int]]:
    if content_type.startswith('image/'):
        return 'image', MAX_ATTACHMENT_SIZES['image']
    if content_type.startswith('video/'):
        return 'video', MAX_ATTACHMENT_SIZES['video']
    if content_type.startswith('audio/'):
        return 'audio', MAX_ATTACHMENT_SIZES['audio']
    if content_type in DOCUMENT_MIME_TYPES:
        return 'document', MAX_ATTACHMENT_SIZES['document']

    if not content_type and filename:
        ext = filename.lower().rsplit('.', 1)[-1]
        if ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt'):
            return 'document', MAX_ATTACHMENT_SIZES['document']
        if ext in ('mp3', 'wav', 'm4a', 'ogg', 'aac'):
            return 'audio', MAX_ATTACHMENT_SIZES['audio']
        if ext in ('mp4', 'mov', 'webm'):
            return 'video', MAX_ATTACHMENT_SIZES['video']
        if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
            return 'image', MAX_ATTACHMENT_SIZES['image']

    return None, None