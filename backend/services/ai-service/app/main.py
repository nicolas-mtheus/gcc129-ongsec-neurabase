"""API REST do ai-service (RAG + LangChain + LLM como serviço distribuído)."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .chains import OLLAMA_BASE_URL, OLLAMA_MODEL, PERGUNTAS_AVALIACAO_RAG, executar_chain_consultoria
from .rag import rag_store
from .resilience import (
    cache_respostas,
    circuit_breaker,
    executar_com_resiliencia,
    telemetria,
)
from .tools import coletar_contexto_ong

app = FastAPI(title="ONGSec ai-service (RAG + LangChain + Ollama)", version="1.0.0")


class ConsultoriaIn(BaseModel):
    ong_id: str = "ong-123"
    pergunta: str
    usar_rag: bool = True
    usar_cache: bool = True
    simular_falha_llm: bool = False


class ComparacaoRagIn(BaseModel):
    ong_id: str = "ong-123"
    pergunta: str


class CircuitBreakerIn(BaseModel):
    acao: str  # abrir | fechar | limpar_cache


@app.on_event("startup")
def startup_rag():
    rag_store.ingerir_e_indexar(forcar=True)


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "service": "ai-service",
        "modelo": OLLAMA_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
        "rag": rag_store.status(),
        "circuit_breaker": circuit_breaker.snapshot(),
    }


@app.get("/v1/ia/rag/status")
def status_rag():
    return rag_store.status()


@app.get("/v1/ia/perguntas-teste")
def listar_perguntas_teste():
    return {"perguntas": PERGUNTAS_AVALIACAO_RAG}


@app.post("/v1/ia/consultoria")
def consultoria_ia(body: ConsultoriaIn):
    # 1. Executa Tools LangChain para consultar dados reais dos microsserviços
    contexto_ong = coletar_contexto_ong(body.ong_id)

    # 2. Executa recuperação vetorial (RAG) quando habilitado
    chunks_rag = rag_store.recuperar_contexto(body.pergunta, top_k=3) if body.usar_rag else []

    # 3. Executa Chain LangChain com Circuit Breaker, Timeout+Retry(Backoff), Cache e Fallback
    res = executar_com_resiliencia(
        ong_id=body.ong_id,
        pergunta=body.pergunta,
        usar_rag=body.usar_rag,
        usar_cache=body.usar_cache,
        simular_falha_llm=body.simular_falha_llm,
        contexto_ong=contexto_ong,
        chunks_rag=chunks_rag,
        chamar_llm=lambda: executar_chain_consultoria(
            body.pergunta, contexto_ong, chunks_rag, usar_rag=body.usar_rag
        ),
    )

    return {
        "ong_id": body.ong_id,
        "pergunta": body.pergunta,
        "usar_rag": body.usar_rag,
        "modelo": OLLAMA_MODEL,
        **res,
        "rag_fontes": chunks_rag,
        "dados_tools": contexto_ong,
    }


@app.post("/v1/ia/comparar-rag")
def comparar_com_e_sem_rag(body: ComparacaoRagIn):
    contexto_ong = coletar_contexto_ong(body.ong_id)
    chunks_rag = rag_store.recuperar_contexto(body.pergunta, top_k=3)

    com_rag = executar_com_resiliencia(
        ong_id=body.ong_id,
        pergunta=body.pergunta,
        usar_rag=True,
        usar_cache=False,
        simular_falha_llm=False,
        contexto_ong=contexto_ong,
        chunks_rag=chunks_rag,
        chamar_llm=lambda: executar_chain_consultoria(
            body.pergunta, contexto_ong, chunks_rag, usar_rag=True
        ),
    )

    sem_rag = executar_com_resiliencia(
        ong_id=body.ong_id,
        pergunta=body.pergunta,
        usar_rag=False,
        usar_cache=False,
        simular_falha_llm=False,
        contexto_ong=contexto_ong,
        chunks_rag=[],
        chamar_llm=lambda: executar_chain_consultoria(
            body.pergunta, contexto_ong, [], usar_rag=False
        ),
    )

    return {
        "ong_id": body.ong_id,
        "pergunta": body.pergunta,
        "modelo": OLLAMA_MODEL,
        "chunks_recuperados": chunks_rag,
        "com_rag": com_rag,
        "sem_rag": sem_rag,
    }


@app.get("/v1/ia/metricas")
def obter_metricas():
    return telemetria.relatorio(cache_respostas, circuit_breaker, OLLAMA_MODEL)


@app.post("/v1/ia/circuit-breaker")
def controlar_circuit_breaker(body: CircuitBreakerIn):
    acao = body.acao.strip().lower()
    if acao == "abrir":
        circuit_breaker.force_open()
    elif acao == "fechar":
        circuit_breaker.reset()
    elif acao == "limpar_cache":
        cache_respostas.clear()
    return {
        "acao_executada": acao,
        "circuit_breaker": circuit_breaker.snapshot(),
        "cache": {"hits": cache_respostas.hits, "misses": cache_respostas.misses},
    }

