import os
import uuid
import logging
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("bff-publico")

BADGE_SERVICE_URL = os.getenv("BADGE_SERVICE_URL", "http://badge-service:8000")
MOCK_FALLBACK = os.getenv("MOCK_FALLBACK", "true").lower() in ("true", "1", "yes")

app = FastAPI(
    title="ONGSec BFF Público",
    description="Backend For Frontend voltado para o aplicativo mobile e consultas públicas anônimas de selos.",
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

# Health endpoint (root and prefixed)
@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
@app.get("/api/publico/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "bff-publico"}

# Public Seal Query Models
class ConsultaPublicaSelo(BaseModel):
    id_selo: str
    ong_id: str
    nome_instituicao: str
    status_conformidade: str
    emitido_em: str
    mensagem: str

async def _obter_selo_publico(ong_id: str, correlation_id: str):
    url = f"{BADGE_SERVICE_URL}/v1/consulta/organizacoes/{ong_id}"
    headers = {"X-Correlation-ID": correlation_id}
    
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Selo para a organização '{ong_id}' não encontrado."
                )
            else:
                logger.warning("badge-service retornou status %s", resp.status_code)
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"badge-service retornou status {resp.status_code}"
                )
    except httpx.RequestError as exc:
        logger.warning("Não foi possível conectar ao badge-service (%s): %s", url, exc)
        if MOCK_FALLBACK:
            # Dados padrão de exemplo conforme documentação (docs/gateway-bffs.md e docs/api/alinhamento-bff.md)
            if ong_id in ("ong-123", "default"):
                return {
                    "id_selo": "CERT-2026-998",
                    "ong_id": ong_id,
                    "nome_instituicao": "Associação Cuidar",
                    "status_conformidade": "ATIVO",
                    "emitido_em": "2026-10-10T14:00:00Z",
                    "mensagem": "Instituição verificada e em conformidade com as diretrizes da LGPD."
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Selo para a organização '{ong_id}' não encontrado."
                )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Serviço de consulta de selos indisponível no momento."
        )

@app.get(
    "/api/publico/selos/{ong_id}",
    response_model=ConsultaPublicaSelo,
    summary="Consulta pública anônima do selo da ONG",
    tags=["Consulta Pública"]
)
@app.get(
    "/selos/{ong_id}",
    response_model=ConsultaPublicaSelo,
    include_in_schema=False
)
async def consultar_selo(ong_id: str, request: Request):
    corr_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    return await _obter_selo_publico(ong_id, corr_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

