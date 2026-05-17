import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

class Base(DeclarativeBase):
    pass

def get_engine():
    # DATABASE_URL overrides individual parts (useful for tests / local dev)
    url = os.getenv("DATABASE_URL") or (
        "postgresql://{user}:{password}@{host}:{port}/{name}".format(
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            name=os.getenv("DB_NAME", "bot"),
        )
    )
    return create_engine(url)

def init_db(app):
    """
    Create all tables on first startup.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    app.config["DB_ENGINE"] = engine
    app.config["DB_SESSION"] = sessionmaker(bind=engine)