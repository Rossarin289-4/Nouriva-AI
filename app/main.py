
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.routes.meals import router as meals_router
from app.routes.rules import router as rules_router
from app.routes import nutrition
from app.routes import foods
from app.routes.auth import router as auth_router
from app.routes.profile import router as profile_router
from app.routes.consents import router as consents_router
from app.routes.ai_chat import router as ai_chat_router

app = FastAPI(
    title="Nouriva AI API",
    description="Backend API for Nouriva AI",
    version="0.1.0",
)

app.include_router(rules_router)
app.include_router(nutrition.router)
app.include_router(foods.router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(consents_router)
app.include_router(ai_chat_router)
app.include_router(meals_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/my-profile", include_in_schema=False)
def my_profile_page():
    return FileResponse(STATIC_DIR / "profile.html")


@app.get("/health/db")
def check_database():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except SQLAlchemyError:
        return {
            "status": "error",
            "database": "disconnected",
        }
