from fastapi import Depends, HTTPException
from modules.auth.jwt import get_current_user
from modules.common.config import ENABLE_ROLE_PERMISSIONS


def require_permission(permission: str):
    async def dependency(current_user: dict = Depends(get_current_user)):
        # If the feature flag is off, allow legacy behavior
        if not ENABLE_ROLE_PERMISSIONS:
            return True

        perms = current_user.get("permissions", []) if current_user else []
        if permission not in perms:
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return True

    return dependency
from fastapi import Depends, HTTPException
from modules.auth.jwt import get_current_user

def require_permission(permission: str):
    async def dependency(current_user: dict = Depends(get_current_user)):
        # If feature flag is off, allow all (legacy behaviour)
        from modules.common.config import ENABLE_ROLE_PERMISSIONS
        if not ENABLE_ROLE_PERMISSIONS:
            return True
        perms = current_user.get("permissions", [])
        if permission not in perms:
            raise HTTPException(403, f"Missing permission: {permission}")
        return True
    return dependency