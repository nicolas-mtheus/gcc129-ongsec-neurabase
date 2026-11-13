import os
import time
from datetime import datetime, timezone

from sqlalchemy import JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./badge.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


# ----- MODELO DE ESCRITA (CQRS): onde as regras de negócio gravam -----
class Solicitacao(Base):
    __tablename__ = "solicitacoes"
    solicitacao_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ong_id: Mapped[str] = mapped_column(String(50), index=True)
    diagnostico_id: Mapped[str] = mapped_column(String(50))
    plano_id: Mapped[str] = mapped_column(String(50))
    estado: Mapped[str] = mapped_column(String(20))  # SOLICITADA | SELO_EMITIDO | COMPENSADA
    id_selo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    historico: Mapped[list] = mapped_column(JSON, default=list)  # historico_saga_emissao


class Selo(Base):
    __tablename__ = "selos"
    id_selo: Mapped[str] = mapped_column(String(50), primary_key=True)
    ong_id: Mapped[str] = mapped_column(String(50), index=True)
    solicitacao_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # ATIVO | REVOGADO
    emitido_em: Mapped[str] = mapped_column(String(40))


# ----- OUTBOX: o evento é gravado na MESMA transação do dado -----
class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tipo_evento: Mapped[str] = mapped_column(String(50))
    ong_id: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    criado_em: Mapped[str] = mapped_column(String(40))
    enviado_em: Mapped[str | None] = mapped_column(String(40), nullable=True)


# ----- MODELO DE LEITURA (CQRS): tabela pronta para a consulta pública -----
class SeloPublico(Base):
    __tablename__ = "selo_publico"
    ong_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    id_selo: Mapped[str] = mapped_column(String(50))
    nome_instituicao: Mapped[str] = mapped_column(String(200))
    status_conformidade: Mapped[str] = mapped_column(String(20))
    emitido_em: Mapped[str] = mapped_column(String(40))
    mensagem: Mapped[str] = mapped_column(String(200))


def criar_tabelas():
    # O Postgres pode demorar a ficar pronto: tenta de novo por até 1 minuto.
    for _ in range(30):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Banco de dados indisponível")