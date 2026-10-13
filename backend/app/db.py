from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.app.config import DATABASE_URL
from backend.app.models.base import Base
from backend.app.models.health import HealthCheckRecord

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def check_db_connection() -> dict:
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            # Also record or update health check
            init_db()
            return {"status": "ok", "query_result": result}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
