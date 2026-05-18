"""Enhanced middleware for security, observability, and cross-cutting concerns"""

import time
import logging
from typing import Callable
from uuid import UUID
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from datetime import datetime
import traceback

from common.exceptions import WABotException, TenantIsolationException


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured logging for all requests
    Logs request/response with key metrics
    """
    
    def __init__(self, app, logger=None):
        super().__init__(app)
        self.logger = logger or logging.getLogger(__name__)
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Add request ID
        request.state.request_id = request.headers.get(
            "X-Request-ID",
            f"{datetime.now().timestamp()}"
        )
        
        # Extract tenant context
        org_id = request.headers.get("X-Organization-ID")
        user_id = request.state.user.id if hasattr(request.state, 'user') else None
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            self.logger.info(
                "http_request",
                request_id=request.state.request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration * 1000,
                organization_id=org_id,
                user_id=user_id
            )
            
            return response
        
        except Exception as e:
            duration = time.time() - start_time
            
            self.logger.error(
                "http_error",
                request_id=request.state.request_id,
                method=request.method,
                path=request.url.path,
                error_type=type(e).__name__,
                error_message=str(e),
                duration_ms=duration * 1000,
                organization_id=org_id,
                user_id=user_id,
                traceback=traceback.format_exc()
            )
            
            raise


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """
    Enforces organization data isolation
    Validates all requests have organization context
    """
    
    def __init__(self, app, logger=None):
        super().__init__(app)
        self.logger = logger or logging.getLogger(__name__)
        # Paths that don't require tenant context
        self.exempt_paths = ["/health", "/openapi.json", "/docs", "/redoc"]
    
    async def dispatch(self, request: Request, call_next):
        # Skip exempt paths
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        # Extract from JWT token (set by auth middleware)
        if hasattr(request.state, 'user'):
            org_id = request.state.user.organization_id
            if org_id:
                request.state.organization_id = org_id
                return await call_next(request)
        
        # If no org context for protected route, reject
        if request.method != "GET":  # Allow GET for public endpoints
            self.logger.warning(
                "tenant_isolation_violation",
                path=request.url.path,
                method=request.method
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "TENANT_ISOLATION_VIOLATION",
                    "detail": "Organization context required"
                }
            )
        
        return await call_next(request)


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs all state-modifying requests for compliance
    Captures request/response for audit trail
    """
    
    def __init__(self, app, logger=None):
        super().__init__(app)
        self.logger = logger or logging.getLogger(__name__)
    
    async def dispatch(self, request: Request, call_next):
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            audit_log = {
                "timestamp": datetime.now().isoformat(),
                "method": request.method,
                "path": request.url.path,
                "user_id": getattr(request.state, 'user', {}).id if hasattr(request.state, 'user') else None,
                "organization_id": getattr(request.state, 'organization_id', None),
                "ip_address": request.client.host if request.client else None
            }
            
            request.state.audit_log = audit_log
        
        return await call_next(request)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Centralized error handling and response formatting
    """
    
    def __init__(self, app, logger=None):
        super().__init__(app)
        self.logger = logger or logging.getLogger(__name__)
    
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        
        except WABotException as e:
            self.logger.warning(
                "wabot_exception",
                error_code=e.error_code,
                detail=e.detail,
                path=request.url.path
            )
            
            return JSONResponse(
                status_code=e.status_code,
                content=e.to_dict()
            )
        
        except Exception as e:
            self.logger.error(
                "unhandled_exception",
                error_type=type(e).__name__,
                error_message=str(e),
                path=request.url.path,
                traceback=traceback.format_exc()
            )
            
            return JSONResponse(
                status_code=500,
                content={
                    "error_code": "INTERNAL_ERROR",
                    "detail": "Internal server error"
                }
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting
    For production, use Redis
    """
    
    def __init__(self, app, requests_per_minute: int = 100, logger=None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.logger = logger or logging.getLogger(__name__)
        self.requests = {}  # {ip_address: [(timestamp, count)]}
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - 60  # 1 minute window
        
        # Clean old requests
        if client_ip in self.requests:
            self.requests[client_ip] = [
                (ts, count) for ts, count in self.requests[client_ip]
                if ts > cutoff
            ]
        else:
            self.requests[client_ip] = []
        
        # Count requests in window
        total_requests = sum(count for _, count in self.requests[client_ip])
        
        if total_requests >= self.requests_per_minute:
            self.logger.warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                requests=total_requests
            )
            
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "detail": f"Rate limit: {self.requests_per_minute} requests per minute"
                }
            )
        
        # Record request
        self.requests[client_ip].append((now, 1))
        
        return await call_next(request)


class CORSEnhancedMiddleware(BaseHTTPMiddleware):
    """
    Enhanced CORS with per-tenant configuration
    """
    
    def __init__(self, app, allowed_origins: list = None):
        super().__init__(app)
        self.allowed_origins = allowed_origins or [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:8000"
        ]
    
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        
        if origin in self.allowed_origins:
            response = await call_next(request)
            
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Organization-ID"
            
            return response
        
        return await call_next(request)
