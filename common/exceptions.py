"""Enhanced exception hierarchy for WABot"""

from typing import Optional, Dict, Any


class WABotException(Exception):
    """Base exception for all WABot errors"""
    
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    detail: str = "Internal server error"
    
    def __init__(
        self,
        detail: Optional[str] = None,
        error_code: Optional[str] = None,
        **kwargs
    ):
        self.detail = detail or self.detail
        self.error_code = error_code or self.error_code
        self.context = kwargs
        super().__init__(self.detail)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response dict"""
        return {
            "error_code": self.error_code,
            "detail": self.detail,
            "context": self.context
        }


class UnauthorizedException(WABotException):
    """401 - Unauthorized"""
    status_code = 401
    error_code = "UNAUTHORIZED"
    detail = "Unauthorized - authentication required"


class ForbiddenException(WABotException):
    """403 - Forbidden"""
    status_code = 403
    error_code = "FORBIDDEN"
    detail = "Forbidden - insufficient permissions"


class NotFoundException(WABotException):
    """404 - Not Found"""
    status_code = 404
    error_code = "NOT_FOUND"
    detail = "Resource not found"


class ValidationException(WABotException):
    """422 - Unprocessable Entity"""
    status_code = 422
    error_code = "VALIDATION_ERROR"
    detail = "Validation error"


class ConflictException(WABotException):
    """409 - Conflict"""
    status_code = 409
    error_code = "CONFLICT"
    detail = "Resource conflict"


class TenantIsolationException(ForbiddenException):
    """403 - Cross-tenant access denied"""
    error_code = "TENANT_ISOLATION_VIOLATION"
    detail = "Cross-tenant access denied"


class RateLimitException(WABotException):
    """429 - Too Many Requests"""
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    detail = "Rate limit exceeded"


class MediaUploadException(WABotException):
    """400 - Media upload error"""
    status_code = 400
    error_code = "MEDIA_UPLOAD_ERROR"
    detail = "Media upload failed"


class WhatsAppAPIException(WABotException):
    """WhatsApp Cloud API error"""
    status_code = 502
    error_code = "WHATSAPP_API_ERROR"
    detail = "WhatsApp API error"


class DatabaseException(WABotException):
    """Database operation error"""
    status_code = 500
    error_code = "DATABASE_ERROR"
    detail = "Database error"


class ExternalServiceException(WABotException):
    """External service integration error"""
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    detail = "External service error"
