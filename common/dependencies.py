"""Dependency injection and request context management"""

import logging
from typing import Optional, Type, TypeVar, Callable, Any, AsyncGenerator
from uuid import UUID
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncSession

from modules.common.database import AsyncSessionLocal
from modules.common.logger import get_logger

T = TypeVar('T')


class DIContainer:
    """Simple dependency injection container"""
    
    def __init__(self):
        self._singletons: dict[Type, Any] = {}
        self._factories: dict[Type, Callable] = {}
        self.logger = get_logger(__name__)
    
    def register_singleton(self, service_type: Type[T], instance: T) -> None:
        """Register singleton instance"""
        self._singletons[service_type] = instance
        self.logger.info(f"Registered singleton: {service_type.__name__}")
    
    def register_factory(
        self,
        service_type: Type[T],
        factory: Callable[..., T]
    ) -> None:
        """Register factory function"""
        self._factories[service_type] = factory
        self.logger.info(f"Registered factory: {service_type.__name__}")
    
    def get(self, service_type: Type[T]) -> T:
        """Get service instance"""
        if service_type in self._singletons:
            return self._singletons[service_type]
        
        if service_type in self._factories:
            return self._factories[service_type]()
        
        raise ValueError(f"Service not registered: {service_type.__name__}")
    
    async def get_async(self, service_type: Type[T]) -> T:
        """Get async service instance"""
        if service_type in self._singletons:
            return self._singletons[service_type]
        
        if service_type in self._factories:
            factory = self._factories[service_type]
            # Check if factory is async
            if hasattr(factory, '__call__'):
                result = factory()
                if hasattr(result, '__await__'):
                    return await result
                return result
        
        raise ValueError(f"Service not registered: {service_type.__name__}")


# Dependency injection functions for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_logger_dep(name: str = "api") -> logging.Logger:
    """Logger dependency"""
    return get_logger(name)


async def get_org_id_from_request(request) -> Optional[UUID]:
    """Extract organization ID from request"""
    if hasattr(request.state, 'user'):
        return request.state.user.organization_id
    return None


async def ensure_org_access(
    org_id: UUID,
    current_user
) -> None:
    """Verify user can access organization"""
    from common.exceptions import TenantIsolationException
    
    if current_user.organization_id != org_id:
        raise TenantIsolationException(
            f"User {current_user.id} cannot access organization {org_id}"
        )


async def get_user_org_id(current_user) -> UUID:
    """Get organization ID from current user"""
    from common.exceptions import UnauthorizedException
    
    if not current_user or not current_user.organization_id:
        raise UnauthorizedException("Organization context required")
    
    return current_user.organization_id


# Caching for expensive operations
@lru_cache(maxsize=128)
def get_cached_config(key: str) -> Optional[str]:
    """Cache configuration values"""
    # This is a simple example - use Redis for production
    return None


def set_cached_config(key: str, value: str, ttl: int = 3600) -> None:
    """Set configuration cache"""
    # This is a simple example - use Redis for production
    pass
