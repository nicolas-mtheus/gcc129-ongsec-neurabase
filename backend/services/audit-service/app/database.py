import os
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    db_user = os.getenv("DB_USER", "ongsec")
    db_pass = os.getenv("DB_PASSWORD", "ongsec_local_dev")
    db_host = os.getenv("DB_HOST", "audit-db")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "audit_db")
    DATABASE_URL = f"postgresql+psycopg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as db:
        yield db
