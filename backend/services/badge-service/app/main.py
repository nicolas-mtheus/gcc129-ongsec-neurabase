from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import saga
from .db import Selo, SeloPublico, Solicitacao, criar_tabelas, engine

app = FastAPI(title="ONGSec badge-service", version="1.0.0")


class NovaSolicitacao(BaseModel):
    ong_id: str
    diagnostico_id: str
    plano_id: str


def erro(status: int, titulo: str, detalhe: str, request: Request) -> JSONResponse:
    return JSONResponse(status_code=status, media_type="application/problem+json",
                        content={"type": "about:blank", "title": titulo, "status": status,
                                 "detail": detalhe, "instance": request.url.path})


@app.on_event("startup")
def iniciar():
    criar_tabelas()


def solicitacao_json(sol: Solicitacao) -> dict:
    links = {"self": {"href": f"/v1/solicitacoes/{sol.solicitacao_id}", "method": "GET"},
             "consulta_publica": {"href": f"/v1/consulta/organizacoes/{sol.ong_id}", "method": "GET"},
             "certificacao": {"href": f"/v1/organizacoes/{sol.ong_id}/certificacao", "method": "GET"}}
    if sol.id_selo:
        links["revogar"] = {"href": f"/v1/selos/{sol.id_selo}/revogacao", "method": "POST"}
    corpo = {"solicitacao_id": sol.solicitacao_id, "ong_id": sol.ong_id,
             "diagnostico_id": sol.diagnostico_id, "plano_id": sol.plano_id,
             "estado": sol.estado, "historico_saga_emissao": sol.historico, "_links": links}
    if sol.id_selo:
        corpo["id_selo"] = sol.id_selo
    return corpo


def selo_json(selo: Selo) -> dict:
    return {"id_selo": selo.id_selo, "ong_id": selo.ong_id,
            "status_conformidade": selo.status, "emitido_em": selo.emitido_em}


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "badge-service"}


# ---------- Escrita: solicitar o selo (inicia a SAGA) ----------
@app.post("/v1/solicitacoes", status_code=202)
def solicitar_selo(corpo: NovaSolicitacao, request: Request,
                   idempotency_key: str | None = Header(default=None),
                   x_correlation_id: str | None = Header(default=None),
                   x_simular_falha: str | None = Header(default=None)):
    try:
        sol_id = saga.iniciar_saga(corpo.ong_id, corpo.diagnostico_id, corpo.plano_id,
                                   idempotency_key, x_correlation_id,
                                   (x_simular_falha or "").lower() == "true")
    except saga.PreCondicaoFalhou as e:
        return erro(422, "Pré-condição não atendida", str(e), request)
    except saga.DependenciaIndisponivel as e:
        return erro(503, "Serviço dependente indisponível", str(e), request)
    with Session(engine) as s:
        return solicitacao_json(s.get(Solicitacao, sol_id))


@app.get("/v1/solicitacoes/{solicitacao_id}")
def obter_solicitacao(solicitacao_id: str, request: Request):
    with Session(engine) as s:
        sol = s.get(Solicitacao, solicitacao_id)
        if not sol:
            return erro(404, "Solicitação não encontrada", solicitacao_id, request)
        return solicitacao_json(sol)


@app.post("/v1/solicitacoes/{solicitacao_id}/compensacoes")
def compensar_solicitacao(solicitacao_id: str, request: Request,
                          x_correlation_id: str | None = Header(default=None)):
    with Session(engine) as s:
        sol = s.get(Solicitacao, solicitacao_id)
        if not sol:
            return erro(404, "Solicitação não encontrada", solicitacao_id, request)
        if sol.estado == "COMPENSADA":
            return erro(409, "Conflito de estado", "A solicitação já foi compensada", request)
        selo = s.get(Selo, sol.id_selo) if sol.id_selo else None
        if selo and selo.status == "ATIVO":
            saga.revogar_selo(s, selo, x_correlation_id)
        sol.estado = "COMPENSADA"
        saga._historico(s, sol, "SOLICITACAO_COMPENSADA", "badge-service")
        s.commit()
    saga.processar_outbox()
    with Session(engine) as s:
        return solicitacao_json(s.get(Solicitacao, solicitacao_id))


@app.post("/v1/selos/{id_selo}/revogacao")
def revogar(id_selo: str, request: Request, x_correlation_id: str | None = Header(default=None)):
    with Session(engine) as s:
        selo = s.get(Selo, id_selo)
        if not selo:
            return erro(404, "Selo não encontrado", id_selo, request)
        if selo.status == "REVOGADO":
            return erro(409, "Conflito de estado", "O selo já está revogado", request)
        saga.revogar_selo(s, selo, x_correlation_id)
        s.commit()
    saga.processar_outbox()
    with Session(engine) as s:
        return selo_json(s.get(Selo, id_selo))


@app.get("/v1/selos/{id_selo}")
def obter_selo(id_selo: str, request: Request):
    with Session(engine) as s:
        selo = s.get(Selo, id_selo)
        if not selo:
            return erro(404, "Selo não encontrado", id_selo, request)
        return selo_json(selo)


@app.get("/v1/organizacoes/{ong_id}/certificacao")
def certificacao(ong_id: str, request: Request):
    with Session(engine) as s:
        selo = s.scalars(select(Selo).where(Selo.ong_id == ong_id)
                         .order_by(Selo.emitido_em.desc())).first()
        if not selo:
            return erro(404, "Certificação não encontrada", ong_id, request)
        sol = s.get(Solicitacao, selo.solicitacao_id)
        return {**selo_json(selo), "historico_saga_emissao": sol.historico}


# ---------- Leitura (CQRS): lê só a tabela pronta, sem junções ----------
@app.get("/v1/consulta/organizacoes/{ong_id}")
def consulta_publica(ong_id: str, request: Request):
    with Session(engine) as s:
        leitura = s.get(SeloPublico, ong_id)
        if not leitura:
            return erro(404, "Selo não encontrado", ong_id, request)
        return {"id_selo": leitura.id_selo, "ong_id": leitura.ong_id,
                "nome_instituicao": leitura.nome_instituicao,
                "status_conformidade": leitura.status_conformidade,
                "emitido_em": leitura.emitido_em, "mensagem": leitura.mensagem}