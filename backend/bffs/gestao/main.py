import asyncio
import datetime
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
import jwt
import redis as redis_lib
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bff-gestao")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", "ongsec-secret-key-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
MOCK_FALLBACK = os.getenv("MOCK_FALLBACK", "false").lower() in ("true", "1", "yes")
REDIS_URL = os.getenv("REDIS_URL", "")
_redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

ORG_SERVICE_URL = os.getenv("ORG_SERVICE_URL", "http://org-service:8000")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000")
TASK_SERVICE_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8000")
BADGE_SERVICE_URL = os.getenv("BADGE_SERVICE_URL", "http://badge-service:8000")
SAGA_ORCHESTRATOR_URL = os.getenv("SAGA_ORCHESTRATOR_URL", "http://saga-orchestrator:8000")
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai-service:8000")

app = FastAPI(
    title="ONGSec BFF Gestão",
    description="Backend For Frontend voltado para o Painel Web de Gestão e Auditores da plataforma ONGSec.",
    version="1.0.0",
)

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
            "detail": exc.detail,
        },
        headers=headers,
        media_type="application/problem+json",
    )


async def require_jwt(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token JWT ausente ou inválido")
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token JWT ausente ou inválido")

    jti = payload.get("jti")
    if jti and _redis_client:
        try:
            if _redis_client.exists(f"revoked:jti:{jti}"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão encerrada")
        except HTTPException:
            raise
        except Exception:
            pass
    return payload


def _ensure_org_access(ong_id: str, user: Dict[str, Any]) -> None:
    if user.get("role") == "ADMIN":
        return
    if user.get("ong_id") != ong_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão sobre esta organização")


async def require_admin(user: Dict[str, Any] = Depends(require_jwt)) -> Dict[str, Any]:
    if user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao perfil ADMIN",
        )
    return user


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
@app.get("/api/gestao/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "bff-gestao"}


# Models
class CadastroRequest(BaseModel):
    nome_instituicao: str
    cnpj: str
    responsavel_legal: str
    email: str
    senha: str


class LoginRequest(BaseModel):
    email: str
    senha: str


class OrganizacaoUpdateRequest(BaseModel):
    nome_instituicao: Optional[str] = None
    responsavel_legal: Optional[str] = None
    email: Optional[str] = None


class SessaoResponse(BaseModel):
    tipo: str
    token: str
    expira_em: int
    usuario_id: str
    ong_id: str
    role: str = "GESTOR"
    nome_instituicao: Optional[str] = None


class EventoSaga(BaseModel):
    evento: str
    servico: str
    sucesso: bool


class InstituicaoInfo(BaseModel):
    ong_id: str
    nome_instituicao: Optional[str] = None
    cnpj: Optional[str] = None
    responsavel_legal: str
    descricao_atividades: Optional[str] = None
    publico_atendido: List[str] = Field(default_factory=list)
    canais_coleta_dados: List[str] = Field(default_factory=list)
    perfil_completo: bool = False


class PerfilOngRequest(BaseModel):
    descricao_atividades: str = Field(min_length=5, max_length=2000)
    publico_atendido: List[str] = Field(default_factory=list)
    canais_coleta_dados: List[str] = Field(default_factory=list)


class GerarHibridoRequest(BaseModel):
    forcar_regeneracao: bool = True


class DetalheSeloGestao(BaseModel):
    id_selo: Optional[str] = None
    status_conformidade: str
    score_auditoria: int
    diagnostico_id: Optional[str] = None
    plano_id: Optional[str] = None
    instituicao: InstituicaoInfo
    historico_saga_emissao: List[EventoSaga]
    tarefas_pendentes: int
    links: Dict[str, Dict[str, str]] = Field(default_factory=dict, alias="_links", serialization_alias="_links")


class RespostaItem(BaseModel):
    pergunta_id: str
    valor: str


class ResponderDiagnosticoRequest(BaseModel):
    respostas: List[RespostaItem]
    diagnostico_id: Optional[str] = None


class ConcluirTarefaRequest(BaseModel):
    evidencia: Optional[str] = None


class ExecucaoSagaRequest(BaseModel):
    simular_falha: bool = False
    diagnostico_id: str = "auto"
    plano_id: str = "auto"


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
    acao: str


# Cadastro completo (ONG + Gestor + JWT)
@app.post("/api/gestao/cadastro", status_code=status.HTTP_201_CREATED, tags=["Autenticação"])
@app.post("/cadastro", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def cadastrar_ong(body: CadastroRequest, request: Request):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{ORG_SERVICE_URL}/v1/cadastro",
                json=body.model_dump(),
                headers={"X-Correlation-ID": corr_id},
            )
            if resp.status_code == 201:
                return resp.json()
            detail = resp.json().get("detail", "Erro ao cadastrar organização") if resp.content else "Erro ao cadastrar"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


# Autenticação / Emissão e Revogação de JWT
@app.post("/api/gestao/sessoes", response_model=SessaoResponse, tags=["Autenticação"])
@app.post("/sessoes", response_model=SessaoResponse, include_in_schema=False)
async def criar_sessao(body: LoginRequest, request: Request):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                f"{ORG_SERVICE_URL}/v1/sessoes",
                json=body.model_dump(),
                headers={"X-Correlation-ID": corr_id},
            )
            if resp.status_code == 200:
                return resp.json()
            detail = resp.json().get("detail", "Credenciais inválidas") if resp.content else "Credenciais inválidas"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


@app.delete("/api/gestao/sessoes/atual", status_code=status.HTTP_204_NO_CONTENT, tags=["Autenticação"])
@app.delete("/sessoes/atual", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def encerrar_sessao(request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.delete(f"{ORG_SERVICE_URL}/v1/sessoes/atual", headers=headers)
            if resp.status_code in (200, 204):
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            raise HTTPException(status_code=resp.status_code, detail="Erro ao encerrar sessão")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


@app.get("/api/gestao/ong/perfil", tags=["Organizações"])
async def obter_perfil_minha_ong(request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    ong_id = user.get("ong_id")
    if not ong_id:
        raise HTTPException(status_code=400, detail="Organização não identificada")
    return await obter_perfil_ong(ong_id, request, user)


@app.put("/api/gestao/ong/perfil", tags=["Organizações"])
async def salvar_perfil_minha_ong(
    body: PerfilOngRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_jwt),
):
    ong_id = user.get("ong_id")
    if not ong_id:
        raise HTTPException(status_code=400, detail="Organização não identificada")
    return await salvar_perfil_ong(ong_id, body, request, user)


@app.get("/api/gestao/organizacoes/{ong_id}/perfil", tags=["Organizações"])
async def obter_perfil_ong(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}/perfil", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao consultar perfil da ONG")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


@app.put("/api/gestao/organizacoes/{ong_id}/perfil", tags=["Organizações"])
async def salvar_perfil_ong(
    ong_id: str,
    body: PerfilOngRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_jwt),
):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.put(
                f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}/perfil",
                json=body.model_dump(),
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
            detail = resp.json().get("detail", "Erro ao salvar perfil da ONG") if resp.content else "Erro"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


# Atualização cadastral da ONG (propaga ORGANIZACAO_ATUALIZADA para CQRS via Redis)
@app.patch("/api/gestao/organizacoes/{ong_id}", tags=["Organizações"])
async def atualizar_organizacao(
    ong_id: str,
    body: OrganizacaoUpdateRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_jwt),
):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    payload = body.model_dump(exclude_none=True)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.patch(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}", json=payload, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            detail = resp.json().get("detail", "Erro ao atualizar organização") if resp.content else "Erro"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"org-service indisponível: {exc}")


# Composição principal do Painel de Gestão (suporta ONG nova sem selo/diagnóstico ainda)
@app.get(
    "/api/gestao/selos/{ong_id}/detalhes",
    response_model=DetalheSeloGestao,
    summary="Consulta composta do selo da ONG com histórico da SAGA e HATEOAS",
    tags=["Gestão do Selo"],
)
@app.get("/selos/{ong_id}/detalhes", response_model=DetalheSeloGestao, include_in_schema=False)
async def obter_detalhes_selo(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}

    async def fetch_json(url: str):
        try:
            async with httpx.AsyncClient(timeout=3.5) as client:
                r = await client.get(url, headers=headers)
                return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    badge_data, audit_data, org_data, task_data, saga_data = await asyncio.gather(
        fetch_json(f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/certificacao"),
        fetch_json(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos"),
        fetch_json(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}"),
        fetch_json(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/plano-atual"),
        fetch_json(f"{SAGA_ORCHESTRATOR_URL}/v1/organizacoes/{ong_id}/ultima-solicitacao"),
    )

    if not org_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organização não encontrada no org-service")

    score = 0
    diagnostico_id = None
    if isinstance(audit_data, dict):
        itens = audit_data.get("itens") or []
        concluido = next((d for d in itens if d.get("status") == "CONCLUIDO" and d.get("score") is not None), None)
        alvo = concluido or (itens[0] if itens else None)
        if alvo:
            score = alvo.get("score") or 0
            diagnostico_id = alvo.get("diagnostico_id")

    tarefas_pendentes = 0
    plano_id = None
    if isinstance(task_data, dict):
        tarefas_pendentes = task_data.get("tarefas_pendentes", 0)
        plano_id = task_data.get("plano_id")

    id_selo = badge_data.get("id_selo") if isinstance(badge_data, dict) else None
    status_conf = badge_data.get("status_conformidade") if isinstance(badge_data, dict) else "PENDENTE"

    historico_saga = (
        saga_data.get("historico_saga_emissao")
        if isinstance(saga_data, dict) and saga_data.get("historico_saga_emissao")
        else (badge_data.get("historico_saga_emissao", []) if isinstance(badge_data, dict) else [])
    )

    links: Dict[str, Dict[str, str]] = {
        "self": {"href": f"/api/gestao/selos/{ong_id}/detalhes", "method": "GET"},
        "auditoria": {"href": f"/api/gestao/{ong_id}/auditoria", "method": "GET"},
        "responder_diagnostico": {"href": f"/api/gestao/{ong_id}/diagnosticos/responder", "method": "POST"},
    }
    if score >= 80 and tarefas_pendentes == 0 and plano_id:
        links["emitir_selo"] = {"href": f"/api/gestao/saga/{ong_id}/executar", "method": "POST"}
    if id_selo and status_conf == "ATIVO" and user.get("role") == "ADMIN":
        links["revogar_selo"] = {"href": f"/api/gestao/selos/{ong_id}/revogar", "method": "POST"}

    return {
        "id_selo": id_selo,
        "status_conformidade": status_conf,
        "score_auditoria": score,
        "diagnostico_id": diagnostico_id,
        "plano_id": plano_id,
        "instituicao": {
            "ong_id": ong_id,
            "nome_instituicao": org_data.get("nome_instituicao"),
            "cnpj": org_data.get("cnpj"),
            "responsavel_legal": org_data.get("responsavel_legal", "Gestor"),
            "descricao_atividades": org_data.get("descricao_atividades"),
            "publico_atendido": org_data.get("publico_atendido") or [],
            "canais_coleta_dados": org_data.get("canais_coleta_dados") or [],
            "perfil_completo": bool(org_data.get("perfil_completo", False)),
        },
        "historico_saga_emissao": historico_saga,
        "tarefas_pendentes": tarefas_pendentes,
        "_links": links,
    }


@app.get("/api/gestao/{ong_id}/auditoria", tags=["Auditoria"])
@app.get("/{ong_id}/auditoria", include_in_schema=False)
async def obter_auditoria(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao consultar auditoria")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"audit-service indisponível: {exc}")


@app.get("/api/gestao/questionario", tags=["Auditoria"])
async def obter_questionario(request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/questionario", headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao carregar questionário")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"audit-service indisponível: {exc}")


@app.post("/api/gestao/{ong_id}/diagnosticos/gerar-hibrido", tags=["Auditoria"])
async def gerar_diagnostico_hibrido(
    ong_id: str,
    request: Request,
    body: Optional[GerarHibridoRequest] = None,
    user: Dict[str, Any] = Depends(require_jwt),
):
    """Compõe questionário híbrido (5 fixas + 5 dinâmicas via IA/fallback) com base no perfil da ONG."""
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}
    forcar = body.forcar_regeneracao if body is not None else True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            org_resp, q_resp, list_resp = await asyncio.gather(
                client.get(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}", headers=headers),
                client.get(f"{AUDIT_SERVICE_URL}/v1/questionario", headers=headers),
                client.get(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers=headers),
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Serviço indisponível: {exc}")

    if org_resp.status_code != 200:
        raise HTTPException(status_code=org_resp.status_code, detail="Organização não encontrada")
    org_data = org_resp.json()
    if not org_data.get("perfil_completo"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Complete o perfil da ONG antes de iniciar o diagnóstico personalizado.",
        )

    if q_resp.status_code != 200:
        raise HTTPException(status_code=q_resp.status_code, detail="Erro ao carregar núcleo fixo de perguntas")
    q_json = q_resp.json()
    perguntas_fixas = q_json.get("perguntas_fixas") or q_json.get("perguntas", [])[:5]
    perguntas_fallback = q_json.get("perguntas_fallback") or q_json.get("perguntas", [])[5:10]

    # Se já existir um rascunho híbrido aberto e não for solicitada regeneração, reaproveita-o rapidamente
    if not forcar and list_resp.status_code == 200:
        abertos = [d for d in list_resp.json().get("itens", []) if d.get("status") in ("RASCUNHO", "EM_ANDAMENTO")]
        if abertos and abertos[0].get("perguntas"):
            return {
                "diagnostico_id": abertos[0]["diagnostico_id"],
                "questionario_id": abertos[0].get("questionario_id", "q-lgpd-hibrido"),
                "perguntas": abertos[0]["perguntas"],
                "modo_geracao": "REAPROVEITADO",
            }

    # Solicita 5 perguntas dinâmicas ao ai-service com timeout longo; fallback local se indisponível
    perguntas_dinamicas = None
    modo_geracao = "FALLBACK_LOCAL"
    try:
        async with httpx.AsyncClient(timeout=100.0) as ai_client:
            ai_resp = await ai_client.post(
                f"{AI_SERVICE_URL}/v1/ia/diagnostico/perguntas-dinamicas",
                json={
                    "ong_id": ong_id,
                    "nome_instituicao": org_data.get("nome_instituicao"),
                    "descricao_atividades": org_data.get("descricao_atividades") or "",
                    "publico_atendido": org_data.get("publico_atendido") or [],
                    "canais_coleta_dados": org_data.get("canais_coleta_dados") or [],
                    "quantidade": 5,
                },
                headers=headers,
            )
            if ai_resp.status_code == 200:
                ai_json = ai_resp.json()
                if ai_json.get("perguntas"):
                    perguntas_dinamicas = ai_json["perguntas"]
                    modo_geracao = ai_json.get("modo_geracao", "OLLAMA_DEEPHAT")
    except Exception:
        perguntas_dinamicas = None

    if not perguntas_dinamicas:
        perguntas_dinamicas = perguntas_fallback

    perguntas_hibridas = []
    ids_vistos = set()
    for p in list(perguntas_fixas) + list(perguntas_dinamicas):
        pid = str(p.get("pergunta_id") or p.get("id") or f"p-{len(perguntas_hibridas)+1}")
        if pid in ids_vistos:
            pid = f"{pid}-{len(perguntas_hibridas)+1}"
        ids_vistos.add(pid)
        item = dict(p)
        item["id"] = pid
        item["pergunta_id"] = pid
        item["enunciado"] = item.get("enunciado") or item.get("pergunta") or ""
        item["pergunta"] = item.get("pergunta") or item["enunciado"]
        perguntas_hibridas.append(item)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            open_resp = await client.post(
                f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos",
                json={"perguntas": perguntas_hibridas, "substituir_rascunho": True},
                headers={**headers, "Idempotency-Key": f"abertura-{uuid.uuid4().hex}"},
            )
            if open_resp.status_code not in (200, 201):
                raise HTTPException(
                    status_code=open_resp.status_code,
                    detail=open_resp.json().get("detail", "Erro ao abrir diagnóstico híbrido"),
                )
            diag_criado = open_resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"audit-service indisponível: {exc}")

    return {
        "diagnostico_id": diag_criado["diagnostico_id"],
        "questionario_id": diag_criado.get("questionario_id", "q-lgpd-hibrido"),
        "perguntas": diag_criado.get("perguntas") or perguntas_hibridas,
        "modo_geracao": modo_geracao,
    }


@app.post("/api/gestao/{ong_id}/diagnosticos/responder", tags=["Auditoria"])
async def responder_e_concluir_diagnostico(
    ong_id: str,
    body: ResponderDiagnosticoRequest,
    request: Request,
    user: Dict[str, Any] = Depends(require_jwt),
):
    """Abre/reutiliza diagnóstico em aberto, grava respostas, conclui o score e cria plano personalizado no task-service."""
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            org_data = {}
            org_resp = await client.get(f"{ORG_SERVICE_URL}/v1/organizacoes/{ong_id}", headers=headers)
            if org_resp.status_code == 200:
                org_data = org_resp.json()

            diag_id = body.diagnostico_id
            perguntas = []

            if diag_id:
                d_resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/diagnosticos/{diag_id}", headers=headers)
                if d_resp.status_code == 200:
                    d_json = d_resp.json()
                    if d_json.get("status") in ("RASCUNHO", "EM_ANDAMENTO"):
                        perguntas = d_json.get("perguntas") or []
                    else:
                        diag_id = None
                else:
                    diag_id = None

            if not diag_id:
                list_resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers=headers)
                if list_resp.status_code == 200:
                    abertos = [d for d in list_resp.json().get("itens", []) if d.get("status") in ("RASCUNHO", "EM_ANDAMENTO")]
                    if abertos:
                        diag_id = abertos[0]["diagnostico_id"]
                        perguntas = abertos[0].get("perguntas") or []

            if not perguntas:
                q_resp = await client.get(f"{AUDIT_SERVICE_URL}/v1/questionario", headers=headers)
                if q_resp.status_code != 200:
                    raise HTTPException(status_code=q_resp.status_code, detail="Erro ao carregar questionário")
                perguntas = q_resp.json().get("perguntas", [])

            if not diag_id:
                open_resp = await client.post(
                    f"{AUDIT_SERVICE_URL}/v1/organizacoes/{ong_id}/diagnosticos",
                    json={"perguntas": perguntas},
                    headers={**headers, "Idempotency-Key": f"abertura-{uuid.uuid4().hex}"},
                )
                if open_resp.status_code not in (200, 201):
                    raise HTTPException(status_code=open_resp.status_code, detail=open_resp.json().get("detail", "Erro ao abrir diagnóstico"))
                diag_id = open_resp.json()["diagnostico_id"]

            mapa_perguntas = {(p.get("pergunta_id") or p.get("id")): p for p in perguntas}

            put_resp = await client.put(
                f"{AUDIT_SERVICE_URL}/v1/diagnosticos/{diag_id}/respostas",
                json={"respostas": [r.model_dump() for r in body.respostas]},
                headers=headers,
            )
            if put_resp.status_code != 200:
                raise HTTPException(status_code=put_resp.status_code, detail=put_resp.json().get("detail", "Erro ao salvar respostas"))

            conc_resp = await client.post(
                f"{AUDIT_SERVICE_URL}/v1/diagnosticos/{diag_id}/conclusao",
                headers={**headers, "Idempotency-Key": f"conclusao-{diag_id}"},
            )
            if conc_resp.status_code != 200:
                raise HTTPException(status_code=conc_resp.status_code, detail=conc_resp.json().get("detail", "Erro ao concluir diagnóstico"))
            diag_final = conc_resp.json()

            # Prepara itens não conformes para personalização do plano de ação com contexto da ONG
            nao_conformes = []
            for resp_item in body.respostas:
                if resp_item.valor == "NAO":
                    p_info = mapa_perguntas.get(resp_item.pergunta_id, {})
                    nao_conformes.append({
                        "pergunta_id": resp_item.pergunta_id,
                        "categoria": p_info.get("categoria", "LGPD"),
                        "pergunta": p_info.get("pergunta") or p_info.get("enunciado") or resp_item.pergunta_id,
                        "tarefa_remediacao": p_info.get("tarefa_remediacao") or f"Remediar controle {resp_item.pergunta_id}",
                    })

            tarefas_novas = []
            if nao_conformes:
                personalizadas = None
                try:
                    async with httpx.AsyncClient(timeout=100.0) as ai_client:
                        p_resp = await ai_client.post(
                            f"{AI_SERVICE_URL}/v1/ia/plano-acao/personalizar",
                            json={
                                "ong_id": ong_id,
                                "perfil_ong": {
                                    "nome_instituicao": org_data.get("nome_instituicao"),
                                    "descricao_atividades": org_data.get("descricao_atividades") or "",
                                    "publico_atendido": org_data.get("publico_atendido") or [],
                                    "canais_coleta_dados": org_data.get("canais_coleta_dados") or [],
                                },
                                "nao_conformes": nao_conformes,
                                "score": diag_final.get("score") or 0,
                            },
                            headers=headers,
                        )
                        if p_resp.status_code == 200:
                            personalizadas = p_resp.json().get("tarefas")
                except Exception:
                    personalizadas = None

                if personalizadas:
                    for item in personalizadas:
                        dias = int(item.get("prazo_dias") or 15)
                        prazo = (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()
                        tarefas_novas.append({"titulo": item["titulo"], "prazo": prazo})
                else:
                    prazo_padrao = (datetime.date.today() + datetime.timedelta(days=15)).isoformat()
                    for item in nao_conformes:
                        tarefas_novas.append({"titulo": item["tarefa_remediacao"], "prazo": prazo_padrao})

            plano_resp = await client.post(
                f"{TASK_SERVICE_URL}/v1/planos",
                json={"ong_id": ong_id, "diagnostico_id": diag_id, "tarefas": tarefas_novas},
                headers={"X-Correlation-ID": corr_id, "Idempotency-Key": f"plano-{diag_id}"},
            )
            if plano_resp.status_code not in (200, 201):
                raise HTTPException(status_code=plano_resp.status_code, detail="Erro ao gerar plano de tarefas")

            # Revogação automática se a ONG refez o diagnóstico e ficou com conformidade abaixo de 80%
            selo_revogado_auto = False
            if (diag_final.get("score") or 0) < 80:
                try:
                    rev_resp = await client.post(
                        f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/revogacao",
                        headers={
                            **headers,
                            "Idempotency-Key": f"auto-rev-{diag_id}",
                        },
                    )
                    if rev_resp.status_code in (200, 204):
                        selo_revogado_auto = True
                except Exception:
                    selo_revogado_auto = False

            return {
                "diagnostico": diag_final,
                "plano": plano_resp.json(),
                "tarefas_criadas": len(tarefas_novas),
                "selo_revogado_automaticamente": selo_revogado_auto,
            }
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Serviço indisponível: {exc}")


@app.post("/api/gestao/selos/{ong_id}/revogar", tags=["Gestão do Selo"])
@app.post("/selos/{ong_id}/revogar", include_in_schema=False)
async def revogar_selo(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_admin)):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {
        "X-Correlation-ID": corr_id,
        "Idempotency-Key": request.headers.get("Idempotency-Key", str(uuid.uuid4())),
        "Authorization": request.headers.get("Authorization", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(f"{BADGE_SERVICE_URL}/v1/organizacoes/{ong_id}/revogacao", headers=headers)
            if resp.status_code in (200, 204):
                return resp.json() if resp.content else {"status": "REVOGADO"}
            detail = resp.json().get("detail", "Conflito ao revogar") if resp.content else "Erro ao revogar"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"badge-service indisponível: {exc}")


@app.post("/api/gestao/selos/{ong_id}/solicitar", tags=["Gestão do Selo"])
async def solicitar_emissao_selo(
    ong_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(require_jwt),
):
    """Endpoint limpo de produto para o Gestor solicitar a emissão do selo de conformidade."""
    return await executar_saga_ao_vivo(
        ong_id,
        ExecucaoSagaRequest(simular_falha=False, diagnostico_id="auto", plano_id="auto"),
        request,
        user,
    )


@app.post("/api/gestao/saga/{ong_id}/executar", tags=["SAGA Orquestrada"])
async def executar_saga_ao_vivo(ong_id: str, body: ExecucaoSagaRequest, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    _ensure_org_access(ong_id, user)
    if body.simular_falha and user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Simulação de falha restrita ao perfil ADMIN")
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
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/tarefas", headers={"X-Correlation-ID": corr_id})
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return {"plano_id": None, "ong_id": ong_id, "tarefas_pendentes": 0, "tarefas": []}
            raise HTTPException(status_code=resp.status_code, detail="Erro ao buscar tarefas")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"task-service indisponível: {exc}")


@app.post("/api/gestao/tarefas/{tarefa_id}/concluir", tags=["Tarefas"])
async def concluir_tarefa_individual(
    tarefa_id: str,
    request: Request,
    body: Optional[ConcluirTarefaRequest] = None,
    user: Dict[str, Any] = Depends(require_jwt),
):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            t_resp = await client.get(f"{TASK_SERVICE_URL}/v1/tarefas/{tarefa_id}", headers={"X-Correlation-ID": corr_id})
            if t_resp.status_code != 200:
                raise HTTPException(status_code=t_resp.status_code, detail="Tarefa não encontrada")
            _ensure_org_access(t_resp.json().get("ong_id", ""), user)

            payload = {"evidencia": body.evidencia} if body and body.evidencia else None
            resp = await client.post(
                f"{TASK_SERVICE_URL}/v1/tarefas/{tarefa_id}/conclusao",
                json=payload,
                headers={"X-Correlation-ID": corr_id},
            )
            if resp.status_code == 200:
                return resp.json()
            detail = resp.json().get("detail", "Erro ao concluir tarefa") if resp.content else "Erro"
            raise HTTPException(status_code=resp.status_code, detail=detail)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"task-service indisponível: {exc}")


@app.post("/api/gestao/tarefas/{ong_id}/concluir-todas", tags=["Tarefas"])
async def concluir_todas_tarefas(ong_id: str, request: Request, user: Dict[str, Any] = Depends(require_jwt)):
    _ensure_org_access(ong_id, user)
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            plano_resp = await client.get(f"{TASK_SERVICE_URL}/v1/organizacoes/{ong_id}/plano-atual", headers={"X-Correlation-ID": corr_id})
            if plano_resp.status_code != 200:
                raise HTTPException(status_code=404, detail="Nenhum plano de ação encontrado para a organização")
            plano_id = plano_resp.json().get("plano_id")
            resp = await client.post(f"{TASK_SERVICE_URL}/v1/planos/{plano_id}/conclusao", headers={"X-Correlation-ID": corr_id})
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail="Erro ao concluir plano")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"task-service indisponível: {exc}")


@app.get("/api/gestao/evidencia-bancos", tags=["Observabilidade"])
async def evidencia_bancos_separados(request: Request, ong_id: Optional[str] = None, user: Dict[str, Any] = Depends(require_admin)):
    alvo_ong = ong_id or user.get("ong_id", "ong-123")
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    headers = {"X-Correlation-ID": corr_id, "Authorization": request.headers.get("Authorization", "")}

    async def consultar(url: str):
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(url, headers=headers)
                return {"status": r.status_code, "dados": r.json() if r.content else None}
        except Exception as e:
            return {"status": 503, "erro": str(e)}

    org_r, audit_r, task_r, badge_w_r, badge_cqrs_r, saga_r = await asyncio.gather(
        consultar(f"{ORG_SERVICE_URL}/v1/organizacoes/{alvo_ong}"),
        consultar(f"{AUDIT_SERVICE_URL}/v1/organizacoes/{alvo_ong}/diagnosticos"),
        consultar(f"{TASK_SERVICE_URL}/v1/organizacoes/{alvo_ong}/tarefas"),
        consultar(f"{BADGE_SERVICE_URL}/v1/organizacoes/{alvo_ong}/certificacao"),
        consultar(f"{BADGE_SERVICE_URL}/v1/consulta/organizacoes/{alvo_ong}"),
        consultar(f"{SAGA_ORCHESTRATOR_URL}/v1/organizacoes/{alvo_ong}/ultima-solicitacao"),
    )
    return {
        "ong_id": alvo_ong,
        "padrao": "Database per Service (4 instâncias PostgreSQL em redes privadas isoladas + Orquestrador SAGA + Redis Broker)",
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
    _ensure_org_access(body.ong_id, user)
    if body.simular_falha_llm and user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Simulação de falha do LLM restrita ao perfil ADMIN")
    return await _proxy_ai("POST", "/v1/ia/consultoria", request, body.model_dump())


@app.post("/api/gestao/ia/comparar-rag", tags=["Assistente IA (RAG + LangChain)"])
async def ia_comparar_rag(body: CompararRagRequest, request: Request, user: Dict[str, Any] = Depends(require_admin)):
    return await _proxy_ai("POST", "/v1/ia/comparar-rag", request, body.model_dump())


@app.get("/api/gestao/ia/metricas", tags=["Assistente IA (RAG + LangChain)"])
async def ia_metricas(request: Request, user: Dict[str, Any] = Depends(require_admin)):
    return await _proxy_ai("GET", "/v1/ia/metricas", request)


@app.post("/api/gestao/ia/circuit-breaker", tags=["Assistente IA (RAG + LangChain)"])
async def ia_circuit_breaker(body: CircuitBreakerRequest, request: Request, user: Dict[str, Any] = Depends(require_admin)):
    return await _proxy_ai("POST", "/v1/ia/circuit-breaker", request, body.model_dump())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
