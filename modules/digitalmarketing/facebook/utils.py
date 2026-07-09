import os
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable not set")
fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt_token(token: str) -> str:
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted: str) -> str:
    return fernet.decrypt(encrypted.encode()).decode()