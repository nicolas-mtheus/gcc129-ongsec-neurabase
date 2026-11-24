
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Organizacao(Base):
    __tablename__ = "organizacoes"

    ong_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nome_instituicao: Mapped[str] = mapped_column(String(255))
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    responsavel_legal: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    descricao_atividades: Mapped[str | None] = mapped_column(Text, nullable=True)
    publico_atendido: Mapped[list] = mapped_column(JSON, default=list)
    canais_coleta_dados: Mapped[list] = mapped_column(JSON, default=list)
    perfil_completo: Mapped[bool] = mapped_column(Boolean, default=False)
    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    usuarios: Mapped[list["Usuario"]] = relationship(
        back_populates="organizacao"
    )


class Usuario(Base):
    __tablename__ = "usuarios"

    usuario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ong_id: Mapped[str] = mapped_column(
        ForeignKey("organizacoes.ong_id")
    )
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="GESTOR")

    organizacao: Mapped["Organizacao"] = relationship(
        back_populates="usuarios"
    )
