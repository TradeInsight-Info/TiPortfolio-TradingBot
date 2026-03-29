import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

class Base(DeclarativeBase):
    pass

def get_engine():
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/bot"
    )
    return create_engine(db_url)

def init_db(app):
    """
    Create all tables on first startup.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    app.config["DB_ENGINE"] = engine
    app.config["DB_SESSION"] = sessionmaker(bind=engine)