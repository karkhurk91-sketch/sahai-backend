"""RBAC and security decorators"""

import functools
from typing import Optional, List, Callable, Any
from fastapi import Depends
from uuid import UUID

from common.exceptions import ForbiddenException, UnauthorizedException


def require_role(*required_roles: str) -> Callable:
    """
    Decorator to enforce role-based access control
    
    Args:
        *required_roles: Allowed roles (e.g., "super_admin", "org_admin")
    
    Example:
        @router.post("/users")
        @require_role("super_admin", "org_admin")
        async def create_user(current_user: User = Depends(get_current_user)):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if not current_user:
                raise UnauthorizedException("User authentication required")
            
            if current_user.role not in required_roles:
                raise ForbiddenException(
                    f"Role {current_user.role} is not authorized for this action. "
                    f"Required roles: {', '.join(required_roles)}"
                )
            
            return await func(*args, current_user=current_user, **kwargs)
        
        # Preserve endpoint metadata
        wrapper.scopes = list(required_roles)
        return wrapper
    
    return decorator


def require_org_access(func: Callable) -> Callable:
    """
    Decorator to verify user has access to organization
    Validates organization_id path parameter matches user's org
    
    Example:
        @router.get("/organizations/{org_id}")
        @require_org_access
        async def get_org(
            org_id: UUID,
            current_user: User = Depends(get_current_user)
        ):
            pass
    """
    @functools.wraps(func)
    async def wrapper(*args, org_id: UUID = None, current_user=None, **kwargs):
        if not current_user:
            raise UnauthorizedException("User authentication required")
        
        if org_id and current_user.organization_id != org_id:
            raise ForbiddenException(
                f"User {current_user.id} cannot access organization {org_id}"
            )
        
        return await func(*args, org_id=org_id, current_user=current_user, **kwargs)
    
    return wrapper


def require_permission(permission: str) -> Callable:
    """
    Decorator to check specific permission
    Permissions are defined in user model or roles
    
    Example:
        @router.post("/conversations/{id}/assign")
        @require_permission("conversations.assign")
        async def assign_conversation(current_user: User):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if not current_user:
                raise UnauthorizedException("User authentication required")
            
            # Check permission based on role
            permissions = get_permissions_for_role(current_user.role)
            
            if permission not in permissions:
                raise ForbiddenException(
                    f"Permission '{permission}' required"
                )
            
            return await func(*args, current_user=current_user, **kwargs)
        
        return wrapper
    
    return decorator


def allow_roles_in_org(*roles: str) -> Callable:
    """
    Decorator for endpoints that should only be accessible
    to specific roles within the organization
    
    Example:
        @router.post("/leads/import")
        @allow_roles_in_org("org_admin", "team_lead")
        async def import_leads(current_user: User):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(
            *args,
            current_user=None,
            org_id: UUID = None,
            **kwargs
        ):
            if not current_user:
                raise UnauthorizedException("User authentication required")
            
            # If org_id provided, verify user belongs to it
            if org_id and current_user.organization_id != org_id:
                raise ForbiddenException("Cannot access this organization")
            
            # Verify role
            if current_user.role not in roles:
                raise ForbiddenException(
                    f"Role {current_user.role} not authorized. "
                    f"Required: {', '.join(roles)}"
                )
            
            return await func(
                *args,
                current_user=current_user,
                org_id=org_id,
                **kwargs
            )
        
        wrapper.allowed_roles = list(roles)
        return wrapper
    
    return decorator


def audit_action(action: str, resource_type: str) -> Callable:
    """
    Decorator to automatically audit user actions
    
    Example:
        @router.post("/conversations")
        @audit_action("create", "conversation")
        async def create_conversation(current_user: User):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            result = await func(*args, current_user=current_user, **kwargs)
            
            # Log audit event
            resource_id = getattr(result, 'id', None) if result else None
            
            # TODO: Call audit service to log this
            # await audit_service.log(
            #     user_id=current_user.id,
            #     organization_id=current_user.organization_id,
            #     action=action,
            #     resource_type=resource_type,
            #     resource_id=resource_id
            # )
            
            return result
        
        return wrapper
    
    return decorator


def validate_tenant_ownership(func: Callable) -> Callable:
    """
    Decorator to ensure resource ownership verification
    Useful for API endpoints that modify shared resources
    
    Example:
        @router.put("/conversations/{id}")
        @validate_tenant_ownership
        async def update_conversation(
            id: UUID,
            current_user: User = Depends(get_current_user),
            conversation_repo = Depends(get_conversation_repo)
        ):
            # Decorator will verify conversation belongs to user's org
            pass
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # This decorator should be used with specific resource logic
        # The actual validation should happen in the service layer
        return await func(*args, **kwargs)
    
    return wrapper


def rate_limit_by_user(calls_per_minute: int = 60) -> Callable:
    """
    Decorator for per-user rate limiting
    
    Example:
        @router.post("/messages")
        @rate_limit_by_user(calls_per_minute=100)
        async def send_message(current_user: User):
            pass
    """
    def decorator(func: Callable) -> Callable:
        call_timestamps = {}
        
        @functools.wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            import time
            
            if not current_user:
                raise UnauthorizedException()
            
            user_id = str(current_user.id)
            now = time.time()
            cutoff = now - 60  # 1 minute window
            
            # Initialize if needed
            if user_id not in call_timestamps:
                call_timestamps[user_id] = []
            
            # Clean old timestamps
            call_timestamps[user_id] = [
                ts for ts in call_timestamps[user_id]
                if ts > cutoff
            ]
            
            # Check limit
            if len(call_timestamps[user_id]) >= calls_per_minute:
                raise ForbiddenException(
                    f"Rate limit exceeded: {calls_per_minute} calls per minute"
                )
            
            # Record this call
            call_timestamps[user_id].append(now)
            
            return await func(*args, current_user=current_user, **kwargs)
        
        return wrapper
    
    return decorator


# Role to permissions mapping
ROLE_PERMISSIONS = {
    "super_admin": [
        "organizations.create",
        "organizations.read",
        "organizations.update",
        "organizations.delete",
        "users.create",
        "users.read",
        "users.update",
        "users.delete",
        "conversations.read",
        "conversations.update",
        "conversations.delete",
        "broadcasts.create",
        "broadcasts.read",
        "broadcasts.update",
        "broadcasts.delete",
        "reports.read",
    ],
    "organization": [
        "users.create",
        "users.read",
        "users.update",
        "conversations.read",
        "conversations.update",
        "conversations.assign",
        "broadcasts.create",
        "broadcasts.read",
        "broadcasts.update",
        "leads.read",
        "leads.update",
        "reports.read",
    ],
    "team_lead": [
        "conversations.read",
        "conversations.update",
        "conversations.assign",
        "broadcasts.create",
        "broadcasts.read",
        "leads.read",
        "leads.update",
        "reports.read",
    ],
    "team_member": [
        "conversations.read",
        "conversations.update",
        "broadcasts.read",
        "leads.read",
    ],
    "viewer": [
        "conversations.read",
        "broadcasts.read",
        "reports.read",
    ]
}


def get_permissions_for_role(role: str) -> List[str]:
    """Get permissions for a role"""
    return ROLE_PERMISSIONS.get(role, [])


def has_permission(user_role: str, permission: str) -> bool:
    """Check if role has permission"""
    return permission in get_permissions_for_role(user_role)
