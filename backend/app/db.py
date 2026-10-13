from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.app.config import DATABASE_URL
from backend.app.models.base import Base
from backend.app.models.health import HealthCheckRecord

# hide_parameters: SQL errors are logged without bound values (plates, names, phone numbers).
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True, hide_parameters=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def check_db_connection() -> dict:
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            # Read-only probe: the schema is owned by Alembic migrations, never created from here.
            return {"status": "ok", "query_result": result}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
