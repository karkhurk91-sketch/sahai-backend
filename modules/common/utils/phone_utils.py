def normalize_phone(phone: str) -> str:
    """Normalize a phone number by removing +, spaces, dashes, parentheses."""
    if not phone:
        return ""
    # Remove common separators and plus sign
    return phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()