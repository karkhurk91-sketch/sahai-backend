# core/dependency_injection.py
"""Simple dependency injection container"""

from typing import Dict, Any, Callable, Type, TypeVar, Optional
import inspect

T = TypeVar('T')


class DIContainer:
    """A basic dependency injection container."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._services = {}
            cls._instance._singletons = {}
        return cls._instance
    
    def register(self, service_type: Type[T], implementation: Callable[..., T], singleton: bool = False) -> None:
        """Register a service with its factory."""
        self._services[service_type] = (implementation, singleton)
    
    def resolve(self, service_type: Type[T]) -> T:
        """Resolve a service instance."""
        if service_type in self._singletons:
            return self._singletons[service_type]
        
        if service_type not in self._services:
            raise KeyError(f"No registration found for {service_type}")
        
        factory, singleton = self._services[service_type]
        
        # Resolve dependencies of the factory if it's a class or function
        if inspect.isclass(factory) or callable(factory):
            sig = inspect.signature(factory)
            dependencies = {}
            for param in sig.parameters.values():
                if param.annotation != param.empty:
                    dependencies[param.name] = self.resolve(param.annotation)
            instance = factory(**dependencies) if dependencies else factory()
        else:
            instance = factory
        
        if singleton:
            self._singletons[service_type] = instance
        return instance
    
    def clear(self):
        """Clear all registrations and singletons (useful for testing)."""
        self._services.clear()
        self._singletons.clear()