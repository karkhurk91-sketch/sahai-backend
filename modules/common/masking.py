"""
Data masking utilities for protecting sensitive information.
Handles masking of phone numbers and emails based on user role and organization settings.
"""
from typing import Optional, Dict, Any


def mask_phone_number(phone: Optional[str], partial: bool = True) -> Optional[str]:
    """
    Mask phone number for display to non-admin users.
    
    Args:
        phone: Phone number to mask
        partial: If True, masks middle digits. If False, shows only last 2 digits.
    
    Returns:
        Masked phone number or None if input is None
        Examples:
            "+919876543210" -> "+91****3210" (partial=True)
            "+919876543210" -> "+91****10" (partial=False)
    """
    if not phone:
        return None
    
    if partial:
        # Show country code and last 4 digits
        if len(phone) > 7:
            return phone[:3] + "****" + phone[-4:]
        return phone[:2] + "****" + phone[-2:]
    else:
        # Show only last 2 digits
        if len(phone) > 5:
            return phone[:3] + "****" + phone[-2:]
        return phone[:2] + "****"


def mask_email(email: Optional[str], partial: bool = True) -> Optional[str]:
    """
    Mask email address for display to non-admin users.
    
    Args:
        email: Email address to mask
        partial: If True, shows first char + domain. If False, shows only domain.
    
    Returns:
        Masked email or None if input is None
        Examples:
            "user@example.com" -> "u****@example.com" (partial=True)
            "user@example.com" -> "****@example.com" (partial=False)
    """
    if not email or "@" not in email:
        return None
    
    try:
        local, domain = email.split("@", 1)
        
        if partial:
            # Show first char + domain
            if len(local) > 1:
                masked_local = local[0] + "*" * (len(local) - 1)
            else:
                masked_local = "*"
        else:
            # Show only asterisks + domain
            masked_local = "*" * len(local)
        
        return f"{masked_local}@{domain}"
    except Exception:
        return None


class MaskingConfig:
    """Configuration for masking behavior"""
    
    def __init__(
        self,
        mask_phone: bool = False,
        mask_email: bool = False,
        phone_partial: bool = True,
        email_partial: bool = True,
    ):
        """
        Args:
            mask_phone: Whether to mask phone numbers
            mask_email: Whether to mask emails
            phone_partial: Masking style for phones (True = show last 4, False = show last 2)
            email_partial: Masking style for emails (True = show 1 char, False = show domain only)
        """
        self.mask_phone = mask_phone
        self.mask_email = mask_email
        self.phone_partial = phone_partial
        self.email_partial = email_partial
    
    @classmethod
    def from_dict(cls, settings: Dict[str, Any]) -> "MaskingConfig":
        """Create config from settings dictionary"""
        return cls(
            mask_phone=settings.get("mask_phone", False),
            mask_email=settings.get("mask_email", False),
            phone_partial=settings.get("phone_partial", True),
            email_partial=settings.get("email_partial", True),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for storage"""
        return {
            "mask_phone": self.mask_phone,
            "mask_email": self.mask_email,
            "phone_partial": self.phone_partial,
            "email_partial": self.email_partial,
        }


def should_mask_data(user_role: str) -> bool:
    """
    Determine if data should be masked based on user role.
    
    Args:
        user_role: User's role (super_admin, partner, org_admin, agent, viewer)
    
    Returns:
        True if data should be masked for this role
    """
    # Org admins and super admins see unmasked data
    # Everyone else (agent, viewer) sees masked data
    return user_role not in ["super_admin", "org_admin", "partner"]


def apply_masking_to_dict(
    data: Dict[str, Any],
    user_role: str,
    masking_config: MaskingConfig,
    phone_fields: list = None,
    email_fields: list = None,
) -> Dict[str, Any]:
    """
    Apply masking to dictionary based on role and config.
    
    Args:
        data: Dictionary to mask
        user_role: User's role
        masking_config: Masking configuration
        phone_fields: List of field names to treat as phone numbers
        email_fields: List of field names to treat as emails
    
    Returns:
        Dictionary with masked fields
    """
    if phone_fields is None:
        phone_fields = ["phone_number", "customer_phone", "customer_phone_number"]
    
    if email_fields is None:
        email_fields = ["email"]
    
    # Don't mask for admins
    if not should_mask_data(user_role):
        return data
    
    masked_data = data.copy()
    
    # Apply phone masking
    if masking_config.mask_phone:
        for field in phone_fields:
            if field in masked_data and masked_data[field]:
                masked_data[field] = mask_phone_number(
                    masked_data[field], 
                    partial=masking_config.phone_partial
                )
    
    # Apply email masking
    if masking_config.mask_email:
        for field in email_fields:
            if field in masked_data and masked_data[field]:
                masked_data[field] = mask_email(
                    masked_data[field],
                    partial=masking_config.email_partial
                )
    
    return masked_data
