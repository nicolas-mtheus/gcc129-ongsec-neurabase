import os
from datetime import datetime, timezone

from sqlalchemy import JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saga_orchestrator.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class SolicitacaoSaga(Base):
    __tablename__ = "solicitacoes_saga"
    solicitacao_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ong_id: Mapped[str] = mapped_column(String(50), index=True)
    diagnostico_id: Mapped[str] = mapped_column(String(50))
    plano_id: Mapped[str] = mapped_column(String(50))
    estado: Mapped[str] = mapped_column(String(20))  # SOLICITADA | SELO_EMITIDO | COMPENSADA
    id_selo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    historico: Mapped[list] = mapped_column(JSON, default=list)
    criado_em: Mapped[str] = mapped_column(String(40), default=agora)


def criar_tabelas():
    Base.metadata.create_all(engine)
