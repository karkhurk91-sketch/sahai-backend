from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict
from modules.common.redis_client import get_redis
from modules.common.logger import get_logger
from modules.common.database import AsyncSessionLocal
from sqlalchemy import text

logger = get_logger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP or user ID)
        client_ip = request.client.host
        user_id = getattr(request.state, 'user_id', None) if hasattr(request.state, 'user_id') else None
        identifier = user_id or client_ip

        # Check rate limit
        redis = await get_redis()
        if redis:
            key = f"rate_limit:{identifier}"
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 60)  # 1 minute window

            if current > self.requests_per_minute:
                logger.warning(f"Rate limit exceeded for {identifier}")
                raise HTTPException(429, "Too many requests")

        # Proceed with request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Log slow requests
        if process_time > 1.0:  # More than 1 second
            logger.warning(f"Slow request: {request.method} {request.url} took {process_time:.2f}s")

        return response

class TenantIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Set current user context for RLS if user is authenticated
        user_id = getattr(request.state, 'user_id', None)
        if user_id:
            async with AsyncSessionLocal() as session:
                try:
                    await session.execute(text("SELECT set_current_user(:user_id)"), {"user_id": str(user_id)})
                    await session.commit()
                except Exception as e:
                    logger.error(f"Failed to set current user context: {e}")

        response = await call_next(request)

        # Clear context after request
        if user_id:
            async with AsyncSessionLocal() as session:
                try:
                    await session.execute(text("SELECT clear_current_user()"))
                    await session.commit()
                except Exception as e:
                    logger.error(f"Failed to clear current user context: {e}")

        return response

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log all API calls for audit
        user_id = getattr(request.state, 'user_id', None) if hasattr(request.state, 'user_id') else None
        org_id = getattr(request.state, 'org_id', None) if hasattr(request.state, 'org_id') else None

        logger.info(f"AUDIT: {request.method} {request.url} - User: {user_id}, Org: {org_id}")

        response = await call_next(request)
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute

    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP or user ID)
        client_ip = request.client.host
        user_id = getattr(request.state, 'user_id', None) if hasattr(request.state, 'user_id') else None
        identifier = user_id or client_ip

        # Check rate limit
        redis = await get_redis()
        if redis:
            key = f"rate_limit:{identifier}"
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 60)  # 1 minute window

            if current > self.requests_per_minute:
                logger.warning(f"Rate limit exceeded for {identifier}")
                raise HTTPException(429, "Too many requests")

        # Proceed with request
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Log slow requests
        if process_time > 1.0:  # More than 1 second
            logger.warning(f"Slow request: {request.method} {request.url} took {process_time:.2f}s")

        return response

class TenantIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Ensure tenant isolation in all requests
        # This would be enhanced with more specific checks
        response = await call_next(request)
        return response

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log all API calls for audit
        user_id = getattr(request.state, 'user_id', None) if hasattr(request.state, 'user_id') else None
        org_id = getattr(request.state, 'org_id', None) if hasattr(request.state, 'org_id') else None

        logger.info(f"AUDIT: {request.method} {request.url} - User: {user_id}, Org: {org_id}")

        response = await call_next(request)
        return response