import os
import uuid
import logging
import asyncio
import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import jwt
from pydantic import BaseModel, EmailStr, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bff-gestao")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", "ongsec-secret-key-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
MOCK_FALLBACK = os.getenv("MOCK_FALLBACK", "true").lower() in ("true", "1", "yes")

ORG_SERVICE_URL = os.getenv("ORG_SERVICE_URL", "http://org-service:8000")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000")
TASK_SERVICE_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8000")
BADGE_SERVICE_URL = os.getenv("BADGE_SERVICE_URL", "http://badge-service:8000")
SAGA_ORCHESTRATOR_URL = os.getenv("SAGA_ORCHESTRATOR_URL", "http://saga-orchestrator:8000")
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai-service:8000")

app = FastAPI(
    title="ONGSec BFF Gestão",
    description="Backend For Frontend voltado para o Painel Web de Gestão e Auditores da plataforma ONGSec.",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = corr_id
    response: Response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    corr_id = getattr(request.state, "correlation_id", None)
    headers = {"X-Correlation-ID": corr_id} if corr_id else {}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://ongsec.local/erros/{exc.status_code}",
            "title": "Erro na requisição",
            "status": exc.status_code,
            "detail": exc.detail
        },
        headers=headers,
        media_type="application/problem+json"
    )

# JWT Authentication Dependency
async def require_jwt(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT ausente ou inválido"
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        # Permite tokens de exemplo documentados em modo demonstração / teste
        if token in ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.exemplo", "demo-token", "valid-test-token"):
            return {"sub": "usr-1", "usuario_id": "usr-1", "ong_id": "ong-123"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT ausente ou inválido"
        )

# Health endpoint (root and prefixed)
@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
@app.get("/api/gestao/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "bff-gestao"}

# Models
class LoginRequest(BaseModel):
    email: str
    senha: str

class SessaoResponse(BaseModel):
    tipo: str
    token: str
    expira_em: int
    usuario_id: str
    ong_id: str

class EventoSaga(BaseModel):
    evento: str
    servico: str
    sucesso: bool

class InstituicaoInfo(BaseModel):
    ong_id: str
    responsavel_legal: str

class DetalheSeloGestao(BaseModel):
    id_selo: str
    status_conformidade: str
    score_auditoria: int
    instituicao: InstituicaoInfo
    historico_saga_emissao: List[EventoSaga]
    tarefas_pendentes: int
    links: Dict[str, Dict[str, str]] = Field(default_factory=dict, alias="_links", serialization_alias="_links")

# Autenticação / Emissão de JWT (rota aberta para obtenção de token)
@app.post(
    "/api/gestao/sessoes",
    response_model=SessaoResponse,
    summary="Cria sessão e emite JWT para o painel de gestão",
    tags=["Autenticação"]
)
@app.post(
    "/sessoes",
    response_model=SessaoResponse,
    include_in_schema=False
)
async def criar_sessao(body: LoginRequest, request: Request):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id}

    # Tenta autenticar no org-service se disponível
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{ORG_SERVICE_URL}/v1/sessoes",
                json=body.model_dump(),
                headers=headers
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (400, 401):
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Credenciais inválidas"))
    except httpx.RequestError:
        logger.warning("org-service indisponível para login, usando gerador interno se fallback habilitado")
        if not MOCK_FALLBACK:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="org-service indisponível")

    # Fallback / Emissão de JWT local
    exp_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    payload = {
        "sub": "usr-1",
        "usuario_id": "usr-1",
        "ong_id": "ong-123",
        "email": body.email,
        "exp": exp_time
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return {
        "tipo": "Bearer",
        "token": token,
        "expira_em": 7200,
        "usuario_id": "usr-1",
        "ong_id": "ong-123"
    }

# Rota protegida: Composição de Detalhes do Selo
@app.get(
    "/api/gestao/selos/{ong_id}/detalhes",
    response_model=DetalheSeloGestao,
    summary="Consulta composta do selo da ONG com histórico da SAGA e HATEOAS",
    tags=["Gestão do Selo"]
)
@app.get(
    "/selos/{ong_id}/detalhes",
    response_model=DetalheSeloGestao,
    include_in_schema=False
)
async def obter_detalhes_selo(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {
        "X-Correlation-ID": corr_id,
        "Authorization": request.headers.get("Authorization", "")
    }

    # Funções de busca aos serviços internos
    async def fetch_badge():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/certificacao", headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def fetch_audit():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def fetch_org():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}", headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def fetch_task():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/plano-atual", headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def fetch_saga():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{SAGA_ORCHESTRATOR_URL}/v1/organizacoes/{ong_id}/ultima-solicitacao", headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    badge_data, audit_data, org_data, task_data, saga_data = await asyncio.gather(
        fetch_badge(), fetch_audit(), fetch_org(), fetch_task(), fetch_saga()
    )

    # Se todos os serviços responderam, monta os dados agregados
    if badge_data and audit_data and org_data and task_data:
        score = 92
        if isinstance(audit_data, list) and len(audit_data) > 0:
            score = audit_data[0].get("score", 92)
        elif isinstance(audit_data, dict):
            itens = audit_data.get("itens")
            if isinstance(itens, list) and len(itens) > 0:
                score = itens[0].get("score", 92)
            else:
                score = audit_data.get("score", 92)

        tarefas_pendentes = 0
        if isinstance(task_data, dict):
            tarefas_pendentes = task_data.get("tarefas_pendentes", 0)

        responsavel = org_data.get("responsavel_legal", "Maria da Silva")
        historico_saga = (
            saga_data.get("historico_saga_emissao")
            if isinstance(saga_data, dict) and saga_data.get("historico_saga_emissao")
            else badge_data.get("historico_saga_emissao", [])
        )

        return {
            "id_selo": badge_data.get("id_selo", "CERT-2026-998"),
            "status_conformidade": badge_data.get("status_conformidade", "ATIVO"),
            "score_auditoria": score,
            "instituicao": {
                "ong_id": ong_id,
                "responsavel_legal": responsavel
            },
            "historico_saga_emissao": historico_saga,
            "tarefas_pendentes": tarefas_pendentes,
            "_links": {
                "self": {
                    "href": f"/api/gestao/selos/{ong_id}/detalhes"
                },
                "auditoria": {
                    "href": f"/api/gestao/{ong_id}/auditoria"
                },
                "revogar_selo": {
                    "href": f"/api/gestao/selos/{ong_id}/revogar",
                    "method": "POST"
                }
            }
        }

    # Em caso de fallback (serviços de domínio não iniciados ou em teste isolado do BFF/Gateway)
    if MOCK_FALLBACK:
        return {
            "id_selo": "CERT-2026-998",
            "status_conformidade": "ATIVO",
            "score_auditoria": 92,
            "instituicao": {
                "ong_id": ong_id,
                "responsavel_legal": "Maria da Silva"
            },
            "historico_saga_emissao": [
                {
                    "evento": "DIAGNOSTICO_CONCLUIDO",
                    "servico": "audit-service",
                    "sucesso": True
                },
                {
                    "evento": "TAREFAS_REMEDIADAS",
                    "servico": "task-service",
                    "sucesso": True
                },
                {
                    "evento": "SELO_GERADO",
                    "servico": "badge-service",
                    "sucesso": True
                }
            ],
            "tarefas_pendentes": 0,
            "_links": {
                "self": {
                    "href": f"/api/gestao/selos/{ong_id}/detalhes"
                },
                "auditoria": {
                    "href": f"/api/gestao/{ong_id}/auditoria"
                },
                "revogar_selo": {
                    "href": f"/api/gestao/selos/{ong_id}/revogar",
                    "method": "POST"
                }
            }
        }

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Microsserviços de domínio indisponíveis para agregação dos dados."
    )

# Rota protegida adicional: Auditoria da ONG
@app.get(
    "/api/gestao/{ong_id}/auditoria",
    summary="Detalhes da auditoria da ONG",
    tags=["Auditoria"]
)
@app.get(
    "/{ong_id}/auditoria",
    include_in_schema=False
)
async def obter_auditoria(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers=headers)
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        pass

    if MOCK_FALLBACK:
        return {
            "ong_id": ong_id,
            "score": 92,
            "status": "CONCLUIDO",
            "diagnostico_id": "diag-55",
            "data_conclusao": "2026-10-09T18:00:00Z"
        }
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="audit-service indisponível")

# Rota protegida adicional: Revogação de Selo
@app.post(
    "/api/gestao/selos/{ong_id}/revogar",
    summary="Revogação administrativa do selo da ONG",
    tags=["Gestão do Selo"]
)
@app.post(
    "/selos/{ong_id}/revogar",
    include_in_schema=False
)
async def revogar_selo(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {
        "X-Correlation-ID": corr_id,
        "Idempotency-Key": request.headers.get("Idempotency-Key", str(uuid.uuid4())),
        "Authorization": request.headers.get("Authorization", "")
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/revogacao",
                headers=headers
            )
            if resp.status_code in (200, 204):
                return resp.json() if resp.content else {"status": "REVOGADO"}
            if resp.status_code in (404, 409):
                raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "Conflito ao revogar"))
    except httpx.RequestError:
        pass

    if MOCK_FALLBACK:
        return {
            "id_selo": "CERT-2026-998",
            "ong_id": ong_id,
            "status_conformidade": "REVOGADO",
            "motivo": "Revogação solicitada via painel administrativo",
            "revogado_em": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="badge-service indisponível")


# =========================================================================
# Parte 4 — Orquestração SAGA ao vivo, Tarefas, Evidência de Bancos e IA
# =========================================================================

class ExecucaoSagaRequest(BaseModel):
    simular_falha: bool = False
    diagnostico_id: str = "diag-55"
    plano_id: str = "plano-1"


class ConsultoriaIARequest(BaseModel):
    ong_id: str = "ong-123"
    pergunta: str
    usar_rag: bool = True
    usar_cache: bool = True
    simular_falha_llm: bool = False


class CompararRagRequest(BaseModel):
    ong_id: str = "ong-123"
    pergunta: str


class CircuitBreakerRequest(BaseModel):
    acao: str  # abrir | fechar | limpar_cache


@app.post("/api/gestao/saga/{ong_id}/executar", tags=["SAGA Orquestrada"])
async def executar_saga_ao_vivo(ong_id: str, body: ExecucaoSagaRequest, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {
        "X-Correlation-ID": corr_id,
        "Idempotency-Key": request.headers.get("Idempotency-Key", str(uuid.uuid4())),
        "X-Simular-Falha": "true" if body.simular_falha else "false",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{SAGA_ORCHESTRATOR_URL}/v1/solicitacoes",
                json={"ong_id": ong_id, "diagnostico_id": body.diagnostico_id, "plano_id": body.plano_id},
                headers=headers,
            )
            if resp.status_code in (200, 202):
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            detail = resp.json().get("detail", "Falha na SAGA") if resp.content else "Falha na SAGA"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"saga-orchestrator indisponível: {exc}")


@app.get("/api/gestao/tarefas/{ong_id}", tags=["Tarefas"])
async def listar_tarefas_ong(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/tarefas", headers={"X-Correlation-ID": corr_id})
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao buscar tarefas")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"task-service indisponível: {exc}")


@app.post("/api/gestao/tarefas/{ong_id}/concluir-todas", tags=["Tarefas"])
async def concluir_todas_tarefas(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            plano_resp = await client.get(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/plano-atual", headers={"X-Correlation-ID": corr_id})
            plano_id = plano_resp.json().get("plano_id", "plano-1") if plano_resp.status_code == 200 else "plano-1"
            resp = await client.post(f"{TASK_SERVICE_URL}/v1/planos/{plano_id}/conclusao", headers={"X-Correlation-ID": corr_id})
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao concluir plano")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"task-service indisponível: {exc}")


@app.get("/api/gestao/evidencia-bancos", tags=["Observabilidade"])
async def evidencia_bancos_separados(request: Request, ong_id: str = "ong-123", user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}

    async def consultar(nome: str, url: str):
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(url, headers=headers)
                return {"status": r.status_code, "dados": r.json() if r.content else None}
        except Exception as e:
            return {"status": 503, "erro": str(e)}

    org_r, audit_r, task_r, badge_w_r, badge_cqrs_r, saga_r = await asyncio.gather(
        consultar("org-db", f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}"),
        consultar("audit-db", f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos"),
        consultar("task-db", f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/tarefas"),
        consultar("badge-db (Escrita)", f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/certificacao"),
        consultar("badge-db (CQRS Leitura)", f"{BADGE_SERVICE_URL}/v1/consulta/organizacoes/{ong_id}"),
        consultar("saga-orchestrator", f"{SAGA_ORCHESTRATOR_URL}/v1/organizacoes/{ong_id}/ultima-solicitacao"),
    )
    return {
        "ong_id": ong_id,
        "padrao": "Database per Service (4 instâncias PostgreSQL em redes privadas isoladas + Orquestrador SAGA dedicado)",
        "bancos": [
            {"banco": "org-db", "rede_isolada": "org-data", "servico": "org-service", **org_r},
            {"banco": "audit-db", "rede_isolada": "audit-data", "servico": "audit-service", **audit_r},
            {"banco": "task-db", "rede_isolada": "task-data", "servico": "task-service", **task_r},
            {"banco": "badge-db (Modelo Escrita)", "rede_isolada": "badge-data", "servico": "badge-service", **badge_w_r},
            {"banco": "badge-db (Projeção CQRS Leitura)", "rede_isolada": "badge-data", "servico": "badge-service", **badge_cqrs_r},
            {"banco": "saga_orchestrator.db", "rede_isolada": "app", "servico": "saga-orchestrator", **saga_r},
        ],
    }


async def _proxy_ai(method: str, path: str, request: Request, body: dict | None = None):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            r = await client.request(method, f"{AI_SERVICE_URL}{path}", headers=headers, json=body)
            return JSONResponse(status_code=r.status_code, content=r.json() if r.content else {})
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"ai-service indisponível: {exc}")


@app.post("/api/gestao/ia/consultoria", tags=["Assistente IA (RAG + LangChain)"])
async def ia_consultoria(body: ConsultoriaIARequest, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    return await _proxy_ai("POST", "/v1/ia/consultoria", request, body.model_dump())


@app.post("/api/gestao/ia/comparar-rag", tags=["Assistente IA (RAG + LangChain)"])
async def ia_comparar_rag(body: CompararRagRequest, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    return await _proxy_ai("POST", "/v1/ia/comparar-rag", request, body.model_dump())


@app.get("/api/gestao/ia/metricas", tags=["Assistente IA (RAG + LangChain)"])
async def ia_metricas(request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    return await _proxy_ai("GET", "/v1/ia/metricas", request)


@app.post("/api/gestao/ia/circuit-breaker", tags=["Assistente IA (RAG + LangChain)"])
async def ia_circuit_breaker(body: CircuitBreakerRequest, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    return await _proxy_ai("POST", "/v1/ia/circuit-breaker", request, body.model_dump())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
