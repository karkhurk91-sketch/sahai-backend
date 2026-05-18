"""Base service class with common patterns for all services"""

import asyncio
import functools
from typing import Any, Callable, TypeVar, Optional
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging

T = TypeVar('T')

class BaseService(ABC):
    """
    Base service class providing:
    - Consistent error handling
    - Retry logic
    - Audit logging
    - Repository dependency injection
    - Structured logging
    """
    
    def __init__(self, repository: Any, logger: logging.Logger):
        """
        Initialize service
        
        Args:
            repository: Data access layer
            logger: Structured logger instance
        """
        self.repo = repository
        self.logger = logger
        self._cache = {}
        self._cache_ttl = {}
    
    async def handle_error(
        self,
        error: Exception,
        context: Optional[dict] = None
    ) -> None:
        """
        Centralized error handling
        
        Args:
            error: Exception to handle
            context: Additional context for logging
        """
        context = context or {}
        self.logger.error(
            "service_error",
            error_type=type(error).__name__,
            error_message=str(error),
            **context
        )
    
    async def cache_get(self, key: str) -> Optional[Any]:
        """Get value from service cache"""
        if key not in self._cache:
            return None
        
        value, ttl = self._cache[key]
        if datetime.now() > ttl:
            del self._cache[key]
            return None
        
        return value
    
    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300
    ) -> None:
        """
        Set value in service cache
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds
        """
        self._cache[key] = (value, datetime.now() + timedelta(seconds=ttl_seconds))
    
    async def cache_delete(self, key: str) -> None:
        """Delete value from cache"""
        self._cache.pop(key, None)
    
    async def cache_clear(self) -> None:
        """Clear all cache"""
        self._cache.clear()


def retry(max_attempts: int = 3, backoff_factor: float = 2.0, backoff_base: float = 1.0):
    """
    Retry decorator with exponential backoff
    
    Args:
        max_attempts: Maximum number of retry attempts
        backoff_factor: Exponential backoff multiplier
        backoff_base: Base delay in seconds
    
    Example:
        @retry(max_attempts=3, backoff_base=1.0)
        async def unstable_operation():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt == max_attempts - 1:
                        raise
                    
                    # Exponential backoff
                    wait_time = backoff_base * (backoff_factor ** attempt)
                    await asyncio.sleep(wait_time)
            
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


def rate_limit(calls: int = 100, period: int = 60):
    """
    Rate limit decorator
    
    Args:
        calls: Number of calls allowed
        period: Time period in seconds
    """
    def decorator(func: Callable) -> Callable:
        calls_made = []
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            now = datetime.now()
            
            # Remove old calls outside the period
            calls_made[:] = [call_time for call_time in calls_made 
                             if (now - call_time).total_seconds() < period]
            
            if len(calls_made) >= calls:
                raise Exception(f"Rate limit exceeded: {calls} calls per {period}s")
            
            calls_made.append(now)
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def cache_result(ttl_seconds: int = 300):
    """
    Cache function result
    
    Args:
        ttl_seconds: Time to live in seconds
    """
    def decorator(func: Callable) -> Callable:
        cache = {}
        cache_ttl = {}
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            cache_key = str((args, sorted(kwargs.items())))
            
            if cache_key in cache:
                ttl = cache_ttl.get(cache_key)
                if ttl and datetime.now() < ttl:
                    return cache[cache_key]
                else:
                    del cache[cache_key]
            
            result = await func(*args, **kwargs)
            cache[cache_key] = result
            cache_ttl[cache_key] = datetime.now() + timedelta(seconds=ttl_seconds)
            return result
        
        return wrapper
    return decorator
