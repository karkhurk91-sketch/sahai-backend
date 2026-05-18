"""Base repository class for data access patterns"""

from typing import TypeVar, Generic, List, Optional, Any
from uuid import UUID
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

T = TypeVar('T')

class BaseRepository(Generic[T]):
    """
    Base repository class providing:
    - Common CRUD operations
    - Query building
    - Relationship loading
    - Pagination
    - Filtering
    """
    
    def __init__(self, session: AsyncSession, model: type[T]):
        """
        Initialize repository
        
        Args:
            session: SQLAlchemy async session
            model: SQLAlchemy model class
        """
        self.session = session
        self.model = model
    
    async def create(self, **kwargs) -> T:
        """
        Create and save a new entity
        
        Args:
            **kwargs: Entity attributes
        
        Returns:
            Created entity
        """
        entity = self.model(**kwargs)
        self.session.add(entity)
        await self.session.flush()
        return entity
    
    async def save(self, entity: T) -> T:
        """
        Save entity (add if not tracked)
        
        Args:
            entity: Entity to save
        
        Returns:
            Saved entity
        """
        self.session.add(entity)
        await self.session.flush()
        return entity
    
    async def read(self, id: UUID) -> Optional[T]:
        """
        Read entity by ID
        
        Args:
            id: Entity ID
        
        Returns:
            Entity or None
        """
        stmt = select(self.model).where(self.model.id == id)
        result = await self.session.execute(stmt)
        return result.scalars().first()
    
    async def read_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        """
        Read all entities with pagination
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
        
        Returns:
            List of entities
        """
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def update(self, id: UUID, **kwargs) -> Optional[T]:
        """
        Update entity
        
        Args:
            id: Entity ID
            **kwargs: Attributes to update
        
        Returns:
            Updated entity or None
        """
        entity = await self.read(id)
        if not entity:
            return None
        
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        
        await self.session.flush()
        return entity
    
    async def delete(self, id: UUID) -> bool:
        """
        Delete entity
        
        Args:
            id: Entity ID
        
        Returns:
            True if deleted, False if not found
        """
        entity = await self.read(id)
        if not entity:
            return False
        
        await self.session.delete(entity)
        await self.session.flush()
        return True
    
    async def count(self, **filters) -> int:
        """
        Count entities matching filters
        
        Args:
            **filters: Filter attributes
        
        Returns:
            Count of matching entities
        """
        stmt = select(self.model)
        
        for key, value in filters.items():
            if hasattr(self.model, key):
                stmt = stmt.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(stmt)
        return result.scalars().all().__len__()
    
    async def filter(self, **kwargs) -> List[T]:
        """
        Filter entities
        
        Args:
            **kwargs: Filter criteria
        
        Returns:
            Matching entities
        """
        stmt = select(self.model)
        
        for key, value in kwargs.items():
            if hasattr(self.model, key):
                stmt = stmt.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def find_one(self, **kwargs) -> Optional[T]:
        """
        Find first entity matching criteria
        
        Args:
            **kwargs: Filter criteria
        
        Returns:
            First matching entity or None
        """
        results = await self.filter(**kwargs)
        return results[0] if results else None
    
    async def exists(self, **kwargs) -> bool:
        """
        Check if entity matching criteria exists
        
        Args:
            **kwargs: Filter criteria
        
        Returns:
            True if exists
        """
        return await self.find_one(**kwargs) is not None
    
    async def commit(self) -> None:
        """Commit current transaction"""
        await self.session.commit()
    
    async def flush(self) -> None:
        """Flush pending changes"""
        await self.session.flush()
    
    async def rollback(self) -> None:
        """Rollback current transaction"""
        await self.session.rollback()


class FilterQueryBuilder:
    """Helper for building complex filter queries"""
    
    def __init__(self, model: type[T]):
        self.model = model
        self.conditions = []
    
    def add_filter(self, attr: str, value: Any, operator: str = "==") -> 'FilterQueryBuilder':
        """
        Add filter condition
        
        Args:
            attr: Attribute name
            value: Filter value
            operator: Comparison operator (==, !=, <, >, <=, >=, in, like, ilike)
        
        Returns:
            Self for chaining
        """
        if not hasattr(self.model, attr):
            return self
        
        column = getattr(self.model, attr)
        
        if operator == "==":
            self.conditions.append(column == value)
        elif operator == "!=":
            self.conditions.append(column != value)
        elif operator == "<":
            self.conditions.append(column < value)
        elif operator == ">":
            self.conditions.append(column > value)
        elif operator == "<=":
            self.conditions.append(column <= value)
        elif operator == ">=":
            self.conditions.append(column >= value)
        elif operator == "in":
            self.conditions.append(column.in_(value))
        elif operator == "like":
            self.conditions.append(column.like(value))
        elif operator == "ilike":
            self.conditions.append(column.ilike(value))
        
        return self
    
    def build(self) -> Any:
        """Build final where clause"""
        if not self.conditions:
            return None
        return and_(*self.conditions)


class PaginationParams:
    """Pagination parameters"""
    
    def __init__(self, skip: int = 0, limit: int = 100):
        self.skip = max(0, skip)
        self.limit = min(1000, max(1, limit))  # Bound limit between 1 and 1000
    
    def offset(self) -> int:
        """Get offset for query"""
        return self.skip
    
    def limit_value(self) -> int:
        """Get limit for query"""
        return self.limit
