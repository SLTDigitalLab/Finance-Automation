import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from api.routes import router
from app.routes.auth_routes import auth_router
from app.routes.user_routes import user_router
from app.routes.audit_routes import audit_router
from app.routes.forecasting import forecast_router
from app.routes.anomaly_routes import anomaly_router
from utils.logger import logger

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Finance Revenue Automation - Generate PowerPoint reports from Excel data",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(audit_router)
app.include_router(forecast_router)
app.include_router(anomaly_router)


@app.on_event("startup")
async def startup_event():
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} starting up")
    logger.info(f"Upload dir: {settings.UPLOAD_DIR}")
    logger.info(f"Output dir: {settings.OUTPUT_DIR}")

    # Initialize DB & Seed Admin
    try:
        from app.database.connection import engine, SessionLocal
        from app.models.user_and_log import (
            Base,
            FinancialTBRecord,
            UploadedFinanceFile,
            User,
        )
        from app.auth.jwt_handler import get_password_hash

        logger.info("Initializing database tables...")

        # Add missing columns to existing tables (idempotent migration)
        from sqlalchemy import text

        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result]
            if "auth_provider" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN auth_provider VARCHAR DEFAULT 'local'"
                    )
                )
                conn.commit()
                logger.info("Added 'auth_provider' column to users table")
            if "microsoft_id" not in columns:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN microsoft_id VARCHAR")
                )
                conn.commit()
                logger.info("Added 'microsoft_id' column to users table")
            if "service_number" not in columns:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN service_number VARCHAR")
                )
                conn.commit()
                logger.info("Added 'service_number' column to users table")

        Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        admin_exists = db.query(User).filter(User.role == "Admin").first()
        if not admin_exists:
            logger.info("Seeding default Admin account...")
            default_admin = User(
                full_name="System Administrator",
                email="admin@finance.com",
                password_hash=get_password_hash("adminpassword"),
                role="Admin",
                status="Approved",
                is_active=True,
            )
            db.add(default_admin)
            db.commit()
            logger.info("Admin seeded successfully: admin@finance.com / adminpassword")
        db.close()
    except Exception as e:
        logger.error(f"Error seeding DB: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"{settings.APP_NAME} shutting down")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
