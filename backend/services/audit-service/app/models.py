from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Diagnostico(Base):
    __tablename__ = 'diagnosticos'
    diagnostico_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ong_id: Mapped[str] = mapped_column(String(64), index=True)
    questionario_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    perguntas: Mapped[list] = mapped_column(JSON, default=list)
    respostas: Mapped[list] = mapped_column(JSON, default=list)
    abertura_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    conclusao_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
