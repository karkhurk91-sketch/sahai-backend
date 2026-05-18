import os
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv

load_dotenv()

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

#meta facebook Ads
FACEBOOK_ACCESS_TOKEN=os.getenv("FACEBOOK_ACCESS_TOKEN")

# WhatsApp
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "default_verify_token")
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
WhatsApp_Business_Account_ID=os.getenv("WhatsApp_Business_Account_ID")


# AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")


# Database
# Async database URL (must use asyncpg)
#DATABASE_URL = os.getenv("DATABASE_URL")
#if DATABASE_URL and "postgresql://" in DATABASE_URL and "+asyncpg" not in DATABASE_URL:
#    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Synchronous database URL (for sync operations like nano-queue, migrations)
#SYNC_DATABASE_URL = os.getenv("SYNC_DATABASE_URL") or DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
#postgresql://postgres:Cogent3t@123@db.kwozhpijmrgzsmpfwutt.supabase.co:5432/postgres
# Ensure the async URL is correct


DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and "?sslmode=require" in DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    # Remove query string
    cleaned = parsed._replace(query="")
    DATABASE_URL_ASYNC = urlunparse(cleaned)
elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL_ASYNC = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL_ASYNC = DATABASE_URL

if not DATABASE_URL_ASYNC:
    DATABASE_URL_ASYNC = "sqlite+aiosqlite:///./local.db"

SYNC_DATABASE_URL = os.getenv("SYNC_DATABASE_URL")
if not SYNC_DATABASE_URL:
    if DATABASE_URL_ASYNC.startswith("postgresql+asyncpg://"):
        SYNC_DATABASE_URL = DATABASE_URL_ASYNC.replace("postgresql+asyncpg://", "postgresql://", 1)
    elif DATABASE_URL_ASYNC.startswith("sqlite+aiosqlite://"):
        SYNC_DATABASE_URL = DATABASE_URL_ASYNC.replace("sqlite+aiosqlite://", "sqlite:///", 1)
    else:
        SYNC_DATABASE_URL = DATABASE_URL_ASYNC
print(f"Async URL: {DATABASE_URL_ASYNC}")  # for debugging (remove later)


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# App
APP_NAME = os.getenv("APP_NAME", "WAai Backend")
QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "nano")  # 'celery' or 'nano'
# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))




# EMAIL SETTINGS
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
