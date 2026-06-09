import os
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text

from modules.common.config import APP_NAME
from modules.common.database import engine, Base
from modules.common.logger import get_logger
from modules.websocket import manager 

# Import all routers
from modules.message.webhook import router as webhook_router
from modules.auth.routes import router as auth_router
from modules.organizations.routes import router as org_router
from modules.admin.routes import router as admin_router
from modules.leads.routes import router as leads_router
from modules.leads.nurturing_routes import router as nurturing_router
from modules.leads.followup_routes import router as followup_router
from modules.broadcast.routes import router as broadcast_router
from modules.ai_config.routes import router as ai_config_router
from modules.conversations.routes import router as conv_router
from modules.customers.routes import router as customers_router
from modules.knowledge.routes import router as knowledge_router
from modules.analytics.routes import router as analytics_router
from modules.chat.routes import router as chat_router
from modules.bookings.routes import router as bookings_router
from modules.admin.prompts import router as admin_prompts_router
# from modules.chat.test_routes import router as admin_ai_test_router  # commented out
from modules.blog.routes import router as blog_router
from modules.messages.router import router as messages_router
from modules.webhooks.router import router as webhooks_router
from modules.campaigns import router as campaigns_router
from modules.social import router as social_router
from modules.partners import router as partners_router
from modules.team import router as team_router
from modules.whatsapp_templates import router as whatsapp_templates_router
from modules.broadcast.groups_routes import router as broadcast_groups_router
from modules.bot_builder.routes import router as bot_builder_router


logger = get_logger(__name__)
app = FastAPI(title=APP_NAME)

# ---------- OpenAPI Security Scheme ----------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version="1.0.0",
        description=app.title,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ---------- Static files for uploads ----------
os.makedirs("uploads/campaigns", exist_ok=True)
app.mount("/static", StaticFiles(directory="uploads"), name="static")

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8000",
        "https://wabot-backend-geky.onrender.com",
        "https://wabot-dashboard-one.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Include all routers ----------
app.include_router(webhook_router)
app.include_router(auth_router)
app.include_router(org_router)
app.include_router(admin_router)
app.include_router(leads_router)
app.include_router(nurturing_router)
app.include_router(followup_router)
app.include_router(broadcast_router)
app.include_router(ai_config_router)
app.include_router(conv_router)
app.include_router(customers_router)
app.include_router(knowledge_router)
app.include_router(analytics_router)
app.include_router(chat_router)
app.include_router(bookings_router)
app.include_router(admin_prompts_router)
# app.include_router(admin_ai_test_router)  # commented out
app.include_router(blog_router)
app.include_router(messages_router)
app.include_router(webhooks_router)
app.include_router(campaigns_router)
app.include_router(social_router)
app.include_router(partners_router) 
app.include_router(team_router)
app.include_router(whatsapp_templates_router)
app.include_router(broadcast_groups_router)
app.include_router(bot_builder_router)



# ---------- Startup / Shutdown ----------
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    #await run_migration()
    logger.info("Database tables initialized and schema up to date")

@app.on_event("shutdown")
async def shutdown():
    await engine.dispose()
    logger.info("Database connection closed")

# ---------- Health endpoints ----------
@app.get("/")
def root():
    return {"message": f"{APP_NAME} is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.websocket("/ws/alerts")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)