import os
import time
import uuid
from datetime import datetime

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# ---------- Configuração (vem de variáveis de ambiente) ----------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./task.db")
SEED_DEMO = os.getenv("SEED_DEMO", "true").lower() == "true"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# ---------- Tabelas (banco do task-service) ----------
class Base(DeclarativeBase):
    pass


class Plano(Base):
    __tablename__ = "planos"
    plano_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ong_id: Mapped[str] = mapped_column(String(50), index=True)
    diagnostico_id: Mapped[str] = mapped_column(String(50))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Tarefa(Base):
    __tablename__ = "tarefas"
    tarefa_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plano_id: Mapped[str] = mapped_column(ForeignKey("planos.plano_id"), index=True)
    ong_id: Mapped[str] = mapped_column(String(50))
    titulo: Mapped[str] = mapped_column(String(200))
    prazo: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="PENDENTE")  # PENDENTE | CONCLUIDA | REABERTA


# ---------- Formato dos dados que chegam (contrato OpenAPI) ----------
class NovaTarefa(BaseModel):
    titulo: str
    prazo: str


class NovoPlano(BaseModel):
    ong_id: str
    diagnostico_id: str
    tarefas: list[NovaTarefa]


# ---------- Aplicação ----------
app = FastAPI(title="ONGSec task-service", version="1.0.0")


def erro(status: int, titulo: str, detalhe: str, request: Request) -> JSONResponse:
    # Erros no formato application/problem+json (RFC 7807), como no contrato
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={"type": "about:blank", "title": titulo, "status": status,
                 "detail": detalhe, "instance": request.url.path},
    )


@app.on_event("startup")
def iniciar():
    # O Postgres pode demorar alguns segundos para ficar pronto: tenta de novo.
    for tentativa in range(30):
        try:
            Base.metadata.create_all(engine)
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("Banco de dados indisponível")
    if SEED_DEMO:  # dados de exemplo (Associação Cuidar) para a demonstração
        with Session(engine) as s:
            if not s.get(Plano, "plano-1"):
                s.add(Plano(plano_id="plano-1", ong_id="ong-123", diagnostico_id="diag-55"))
                s.add(Tarefa(tarefa_id="tarefa-1", plano_id="plano-1", ong_id="ong-123",
                             titulo="Elaborar política de privacidade", prazo="2026-12-01"))
                s.add(Tarefa(tarefa_id="tarefa-2", plano_id="plano-1", ong_id="ong-123",
                             titulo="Ativar autenticação em dois fatores", prazo="2026-12-10"))
                s.commit()


# ---------- Funções auxiliares ----------
def pendentes(s: Session, plano_id: str) -> int:
    return len(s.scalars(select(Tarefa).where(
        Tarefa.plano_id == plano_id, Tarefa.status.in_(["PENDENTE", "REABERTA"]))).all())


def plano_json(s: Session, p: Plano) -> dict:
    return {"plano_id": p.plano_id, "ong_id": p.ong_id, "diagnostico_id": p.diagnostico_id,
            "tarefas_pendentes": pendentes(s, p.plano_id)}


def tarefa_json(t: Tarefa) -> dict:
    # HATEOAS: a resposta já traz os links das próximas ações possíveis
    return {"tarefa_id": t.tarefa_id, "plano_id": t.plano_id, "ong_id": t.ong_id,
            "titulo": t.titulo, "status": t.status, "prazo": t.prazo,
            "_links": {
                "self": {"href": f"/v1/tarefas/{t.tarefa_id}", "method": "GET"},
                "plano": {"href": f"/v1/planos/{t.plano_id}", "method": "GET"},
                "concluir": {"href": f"/v1/tarefas/{t.tarefa_id}/conclusao", "method": "POST"},
                "reabrir": {"href": f"/v1/planos/{t.plano_id}/reabertura", "method": "POST"}}}


# ---------- Endpoints ----------
@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "task-service"}


@app.post("/v1/planos", status_code=201)
def criar_plano(corpo: NovoPlano, idempotency_key: str | None = Header(default=None)):
    with Session(engine) as s:
        if idempotency_key:  # mesma chave = mesma resposta, sem duplicar
            existente = s.scalars(select(Plano).where(Plano.idempotency_key == idempotency_key)).first()
            if existente:
                return plano_json(s, existente)
        plano = Plano(plano_id="plano-" + uuid.uuid4().hex[:6], ong_id=corpo.ong_id,
                      diagnostico_id=corpo.diagnostico_id, idempotency_key=idempotency_key)
        s.add(plano)
        for t in corpo.tarefas:
            s.add(Tarefa(tarefa_id="tarefa-" + uuid.uuid4().hex[:6], plano_id=plano.plano_id,
                         ong_id=corpo.ong_id, titulo=t.titulo, prazo=t.prazo))
        s.commit()
        return plano_json(s, plano)


@app.get("/v1/planos/{plano_id}")
def obter_plano(plano_id: str, request: Request):
    with Session(engine) as s:
        p = s.get(Plano, plano_id)
        if not p:
            return erro(404, "Plano não encontrado", plano_id, request)
        return plano_json(s, p)


@app.get("/v1/planos/{plano_id}/tarefas")
def listar_tarefas(plano_id: str, request: Request):
    with Session(engine) as s:
        if not s.get(Plano, plano_id):
            return erro(404, "Plano não encontrado", plano_id, request)
        ts = s.scalars(select(Tarefa).where(Tarefa.plano_id == plano_id)).all()
        return [tarefa_json(t) for t in ts]


@app.post("/v1/planos/{plano_id}/reabertura")
def reabrir_plano(plano_id: str, request: Request):
    # Compensação da SAGA: reabre as tarefas concluídas
    with Session(engine) as s:
        p = s.get(Plano, plano_id)
        if not p:
            return erro(404, "Plano não encontrado", plano_id, request)
        for t in s.scalars(select(Tarefa).where(Tarefa.plano_id == plano_id,
                                                Tarefa.status == "CONCLUIDA")).all():
            t.status = "REABERTA"
        s.commit()
        return plano_json(s, p)


@app.get("/v1/organizacoes/{ong_id}/plano-atual")
def plano_atual(ong_id: str, request: Request):
    with Session(engine) as s:
        p = s.scalars(select(Plano).where(Plano.ong_id == ong_id)
                      .order_by(Plano.criado_em.desc())).first()
        if not p:
            return erro(404, "Plano não encontrado", ong_id, request)
        return plano_json(s, p)


@app.get("/v1/tarefas/{tarefa_id}")
def obter_tarefa(tarefa_id: str, request: Request):
    with Session(engine) as s:
        t = s.get(Tarefa, tarefa_id)
        if not t:
            return erro(404, "Tarefa não encontrada", tarefa_id, request)
        return tarefa_json(t)


@app.post("/v1/tarefas/{tarefa_id}/conclusao")
def concluir_tarefa(tarefa_id: str, request: Request):
    with Session(engine) as s:
        t = s.get(Tarefa, tarefa_id)
        if not t:
            return erro(404, "Tarefa não encontrada", tarefa_id, request)
        if t.status == "CONCLUIDA":
            return erro(409, "Conflito de estado", "A tarefa já está concluída", request)
        t.status = "CONCLUIDA"
        s.commit()
        return tarefa_json(t)