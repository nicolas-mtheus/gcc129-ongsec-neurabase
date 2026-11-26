"""Orquestrador dedicado da SAGA de emissão do Selo Digital (serviço independente)."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SolicitacaoSaga, agora, criar_tabelas, engine

AUDIT_URL = os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000")
TASK_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8000")
ORG_URL = os.getenv("ORG_SERVICE_URL", "http://org-service:8000")
BADGE_URL = os.getenv("BADGE_SERVICE_URL", "http://badge-service:8000")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", "ongsec-secret-key-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

app = FastAPI(title="ONGSec saga-orchestrator", version="1.0.0")


class NovaSolicitacao(BaseModel):
    ong_id: str
    diagnostico_id: str = "auto"
    plano_id: str = "auto"


def erro(status: int, titulo: str, detalhe: str, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": titulo,
            "status": status,
            "detail": detalhe,
            "instance": request.url.path,
        },
    )


def _token_interno(ong_id: str) -> str:
    payload = {
        "sub": "saga-orchestrator",
        "usuario_id": "saga-orchestrator",
        "ong_id": ong_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@app.on_event("startup")
def iniciar():
    criar_tabelas()
    with Session(engine) as s:
        if not s.get(SolicitacaoSaga, "sol-998"):
            s.add(
                SolicitacaoSaga(
                    solicitacao_id="sol-998",
                    ong_id="ong-123",
                    diagnostico_id="diag-55",
                    plano_id="plano-1",
                    estado="SELO_EMITIDO",
                    id_selo="CERT-2026-998",
                    criado_em="2026-10-10T14:00:00+00:00",
                    historico=[
                        {"evento": "DIAGNOSTICO_CONCLUIDO", "servico": "audit-service", "sucesso": True},
                        {"evento": "TAREFAS_REMEDIADAS", "servico": "task-service", "sucesso": True},
                        {"evento": "SELO_GERADO", "servico": "badge-service", "sucesso": True},
                    ],
                )
            )
            s.commit()


def _chamar(
    metodo: str,
    url: str,
    corr: str | None,
    json_body: dict | None = None,
    extra_headers: dict | None = None,
    auth_ong_id: str | None = None,
):
    headers = {"X-Correlation-ID": corr or ""}
    if auth_ong_id:
        headers["Authorization"] = f"Bearer {_token_interno(auth_ong_id)}"
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = httpx.request(metodo, url, timeout=5.0, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Serviço indisponível: {url}") from e
    return r.status_code, (r.json() if r.content else None)


def _solicitacao_json(sol: SolicitacaoSaga) -> dict:
    links = {
        "self": {"href": f"/v1/solicitacoes/{sol.solicitacao_id}", "method": "GET"},
        "consulta_publica": {"href": f"/v1/consulta/organizacoes/{sol.ong_id}", "method": "GET"},
        "certificacao": {"href": f"/v1/organizacoes/{sol.ong_id}/certificacao", "method": "GET"},
    }
    if sol.id_selo:
        links["revogar"] = {"href": f"/v1/selos/{sol.id_selo}/revogacao", "method": "POST"}
    corpo = {
        "solicitacao_id": sol.solicitacao_id,
        "ong_id": sol.ong_id,
        "diagnostico_id": sol.diagnostico_id,
        "plano_id": sol.plano_id,
        "estado": sol.estado,
        "historico_saga_emissao": sol.historico,
        "criado_em": sol.criado_em,
        "_links": links,
    }
    if sol.id_selo:
        corpo["id_selo"] = sol.id_selo
    return corpo


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "saga-orchestrator"}


@app.post("/v1/solicitacoes", status_code=202)
def iniciar_saga(
    corpo: NovaSolicitacao,
    request: Request,
    idempotency_key: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
    x_simular_falha: str | None = Header(default=None),
):
    if idempotency_key:
        with Session(engine) as s:
            existente = s.scalars(
                select(SolicitacaoSaga).where(SolicitacaoSaga.idempotency_key == idempotency_key)
            ).first()
            if existente:
                return _solicitacao_json(existente)

    # Passo 1 e 2: resolver e validar pré-condições no audit-service e task-service
    diagnostico_id = corpo.diagnostico_id
    plano_id = corpo.plano_id
    try:
        if not diagnostico_id or diagnostico_id == "auto":
            st_list, diag_list = _chamar(
                "GET",
                f"{AUDIT_URL}/v1/organizacoes/{corpo.ong_id}/diagnosticos?status=CONCLUIDO",
                x_correlation_id,
                auth_ong_id=corpo.ong_id,
            )
            itens = diag_list.get("itens", []) if st_list == 200 and isinstance(diag_list, dict) else []
            if not itens:
                return erro(422, "Pré-condição não atendida", "Nenhum diagnóstico concluído encontrado", request)
            diag = itens[0]
            diagnostico_id = diag["diagnostico_id"]
        else:
            st_diag, diag = _chamar(
                "GET",
                f"{AUDIT_URL}/v1/diagnosticos/{diagnostico_id}",
                x_correlation_id,
                auth_ong_id=corpo.ong_id,
            )
            if st_diag != 200 or not diag or diag.get("status") != "CONCLUIDO" or diag.get("score") is None:
                return erro(422, "Pré-condição não atendida", "Diagnóstico não concluído ou sem score", request)

        if diag.get("score") is None or diag.get("score") < 80:
            return erro(422, "Score insuficiente", "Score mínimo de 80% não atingido para certificação", request)

        st_plano, plano = _chamar(
            "GET",
            f"{TASK_URL}/v1/organizacoes/{corpo.ong_id}/plano-atual",
            x_correlation_id,
        )
        if not plano_id or plano_id == "auto":
            if st_plano != 200 or not plano:
                return erro(422, "Pré-condição não atendida", "Nenhum plano de ação encontrado", request)
            plano_id = plano["plano_id"]
        if st_plano != 200 or not plano or plano.get("plano_id") != plano_id or plano.get("tarefas_pendentes") != 0:
            return erro(422, "Pré-condição não atendida", "O plano ainda tem tarefas pendentes", request)
    except RuntimeError as e:
        return erro(503, "Serviço dependente indisponível", str(e), request)

    nome_instituicao = f"Organização {corpo.ong_id}"
    cnpj = None
    try:
        st_org, org = _chamar(
            "GET",
            f"{ORG_URL}/v1/organizacoes/{corpo.ong_id}",
            x_correlation_id,
            auth_ong_id=corpo.ong_id,
        )
        if st_org == 200 and org:
            if org.get("nome_instituicao"):
                nome_instituicao = org["nome_instituicao"]
            cnpj = org.get("cnpj")
    except RuntimeError:
        pass

    sol_id = "sol-" + uuid.uuid4().hex[:6]
    historico = [
        {"evento": "DIAGNOSTICO_CONCLUIDO", "servico": "audit-service", "sucesso": True},
        {"evento": "TAREFAS_REMEDIADAS", "servico": "task-service", "sucesso": True},
    ]

    with Session(engine) as s:
        sol = SolicitacaoSaga(
            solicitacao_id=sol_id,
            ong_id=corpo.ong_id,
            diagnostico_id=diagnostico_id,
            plano_id=plano_id,
            estado="SOLICITADA",
            historico=historico,
            idempotency_key=idempotency_key,
            criado_em=agora(),
        )
        s.add(sol)
        s.commit()

    # Passo 3: solicitar emissão do selo ao badge-service
    try:
        extra = {"X-Simular-Falha": x_simular_falha} if x_simular_falha else None
        st_badge, badge_resp = _chamar(
            "POST",
            f"{BADGE_URL}/v1/selos",
            x_correlation_id,
            json_body={
                "ong_id": corpo.ong_id,
                "solicitacao_id": sol_id,
                "nome_instituicao": nome_instituicao,
                "cnpj": cnpj,
                "historico_saga_emissao": historico,
            },
            extra_headers=extra,
        )
        if st_badge not in (200, 201) or not badge_resp or not badge_resp.get("id_selo"):
            raise RuntimeError("Falha ao emitir selo no badge-service")

        with Session(engine) as s:
            sol = s.get(SolicitacaoSaga, sol_id)
            sol.estado = "SELO_EMITIDO"
            sol.id_selo = badge_resp["id_selo"]
            sol.historico = list(sol.historico) + [
                {"evento": "SELO_GERADO", "servico": "badge-service", "sucesso": True}
            ]
            s.commit()
            return _solicitacao_json(sol)
    except Exception:
        # Compensação em ordem inversa (nesta falha, o selo nunca foi emitido):
        # 1) Reabrir plano de tarefas no task-service (audit-service permanece intacto: fato histórico)
        reabriu = False
        try:
            st_reab, _ = _chamar("POST", f"{TASK_URL}/v1/planos/{plano_id}/reabertura", x_correlation_id)
            reabriu = st_reab == 200
        except RuntimeError:
            pass

        # 2) Registrar falha e compensação na SAGA
        with Session(engine) as s:
            sol = s.get(SolicitacaoSaga, sol_id)
            sol.estado = "COMPENSADA"
            sol.historico = list(sol.historico) + [
                {"evento": "FALHA_EMISSAO_SELO", "servico": "badge-service", "sucesso": False},
                {"evento": "PLANO_REABERTO_COMPENSACAO", "servico": "task-service", "sucesso": reabriu},
                {"evento": "SOLICITACAO_COMPENSADA", "servico": "saga-orchestrator", "sucesso": True},
            ]
            s.commit()
            return _solicitacao_json(sol)


@app.get("/v1/solicitacoes/{solicitacao_id}")
def obter_solicitacao(solicitacao_id: str, request: Request):
    with Session(engine) as s:
        sol = s.get(SolicitacaoSaga, solicitacao_id)
        if not sol:
            return erro(404, "Solicitação não encontrada", solicitacao_id, request)
        return _solicitacao_json(sol)


@app.get("/v1/organizacoes/{ong_id}/ultima-solicitacao")
def ultima_solicitacao(ong_id: str, request: Request):
    with Session(engine) as s:
        sol = s.scalars(
            select(SolicitacaoSaga)
            .where(SolicitacaoSaga.ong_id == ong_id)
            .order_by(SolicitacaoSaga.criado_em.desc())
        ).first()
        if not sol:
            return erro(404, "Nenhuma solicitação SAGA para a organização", ong_id, request)
        return _solicitacao_json(sol)


@app.post("/v1/solicitacoes/{solicitacao_id}/compensacoes")
def compensar_solicitacao(solicitacao_id: str, request: Request, x_correlation_id: str | None = Header(default=None)):
    with Session(engine) as s:
        sol = s.get(SolicitacaoSaga, solicitacao_id)
        if not sol:
            return erro(404, "Solicitação não encontrada", solicitacao_id, request)
        if sol.estado == "COMPENSADA":
            return erro(409, "Conflito de estado", "A solicitação já foi compensada", request)
        id_selo = sol.id_selo
        plano_id = sol.plano_id

    if id_selo:
        try:
            _chamar("POST", f"{BADGE_URL}/v1/selos/{id_selo}/revogacao", x_correlation_id)
        except RuntimeError:
            pass

    try:
        _chamar("POST", f"{TASK_URL}/v1/planos/{plano_id}/reabertura", x_correlation_id)
    except RuntimeError:
        pass

    with Session(engine) as s:
        sol = s.get(SolicitacaoSaga, solicitacao_id)
        sol.estado = "COMPENSADA"
        sol.historico = list(sol.historico) + [
            {"evento": "PLANO_REABERTO_COMPENSACAO", "servico": "task-service", "sucesso": True},
            {"evento": "SOLICITACAO_COMPENSADA", "servico": "saga-orchestrator", "sucesso": True},
        ]
        s.commit()
        return _solicitacao_json(sol)
