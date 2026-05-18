from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from datetime import datetime, timedelta
from modules.common.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from modules.common.redis_client import get_redis
import bcrypt

security = HTTPBearer()

# ---------- Password hashing helpers ----------
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

# Alias for consistent naming across modules
get_password_hash = hash_password

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# ---------- JWT token creation ----------
def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict):
    """Create a JWT refresh token with longer expiration."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)  # 7 days
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def blacklist_token(token: str):
    """Add token to blacklist if Redis is available."""
    try:
        redis_client = get_redis()
    except Exception:
        redis_client = None

    if redis_client:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
            exp = payload.get("exp", 0)
            ttl = max(0, exp - int(datetime.utcnow().timestamp()))
            await redis_client.setex(f"blacklist:{token}", ttl, "1")
        except Exception as e:
            # Log but don't fail
            print(f"Failed to blacklist token: {e}")

async def is_token_blacklisted(token: str) -> bool:
    """Check if token is blacklisted. Returns False if Redis is unavailable."""
    try:
        redis_client = get_redis()
    except Exception:
        return False

    if redis_client:
        try:
            result = await redis_client.exists(f"blacklist:{token}")
            return result == 1
        except Exception:
            return False
    return False

# ---------- JWT authentication dependencies ----------
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    # Optional: skip blacklist check if no Redis
    try:
        if await is_token_blacklisted(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    except Exception:
        # If Redis or blacklist availability fails, continue authentication.
        pass

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Validate token type
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        return {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role"),
            "org_id": payload.get("org_id"),
            "user_id": payload.get("user_id"),
            "partner_id": payload.get("partner_id")
        }
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

async def get_current_super_admin(current_user = Depends(get_current_user)):
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user

async def get_current_partner(current_user = Depends(get_current_user)):
    if current_user.get("role") != "partner":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user