"""Serviço de Certificação (Emissão/Revogação de Selos, Outbox/Redis Relay e Consulta Pública CQRS)."""
import json
import os
import threading
import time
import uuid

import redis as redis_lib
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import Outbox, Selo, SeloPublico, Solicitacao, agora, criar_tabelas, engine

SIMULAR_FALHA_ENV = os.getenv("SIMULAR_FALHA_SELO", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "")
_redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

MENSAGENS = {
    "ATIVO": "Instituição verificada e em conformidade com as diretrizes da LGPD.",
    "REVOGADO": "Selo revogado: a instituição não está mais em conformidade.",
}

app = FastAPI(title="ONGSec badge-service", version="1.0.0")


class EmissaoSelo(BaseModel):
    ong_id: str
    solicitacao_id: str
    nome_instituicao: str
    cnpj: str | None = None
    historico_saga_emissao: list = []


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


def registrar_evento(s: Session, tipo: str, ong_id: str, payload: dict, corr: str | None):
    s.add(
        Outbox(
            id=uuid.uuid4().hex,
            tipo_evento=tipo,
            ong_id=ong_id,
            payload=payload,
            correlation_id=corr,
            criado_em=agora(),
        )
    )


def _aplicar_evento_cqrs(s: Session, tipo_evento: str, ong_id: str, payload: dict) -> None:
    """Projetor idempotente do modelo de leitura CQRS (selo_publico)."""
    leitura = s.get(SeloPublico, ong_id)
    if tipo_evento == "SELO_GERADO":
        dados = dict(
            id_selo=payload["id_selo"],
            nome_instituicao=payload["nome_instituicao"],
            cnpj=payload.get("cnpj") or (leitura.cnpj if leitura else None),
            status_conformidade="ATIVO",
            emitido_em=payload["emitido_em"],
            mensagem=MENSAGENS["ATIVO"],
        )
        s.merge(SeloPublico(ong_id=ong_id, **dados))
    elif tipo_evento == "SELO_REVOGADO" and leitura:
        leitura.status_conformidade = "REVOGADO"
        leitura.mensagem = MENSAGENS["REVOGADO"]
    elif tipo_evento == "ORGANIZACAO_ATUALIZADA" and leitura:
        if payload.get("nome_instituicao"):
            leitura.nome_instituicao = payload["nome_instituicao"]
        if payload.get("cnpj"):
            leitura.cnpj = payload["cnpj"]


def processar_outbox():
    """Relay da outbox: atualiza a projeção CQRS, commita e publica eventos no broker Redis."""
    mensagens_para_publicar = []
    with Session(engine) as s:
        pendentes = s.scalars(
            select(Outbox).where(Outbox.enviado_em.is_(None)).order_by(Outbox.criado_em)
        ).all()
        for ev in pendentes:
            _aplicar_evento_cqrs(s, ev.tipo_evento, ev.ong_id, ev.payload)
            ev.enviado_em = agora()
            mensagens_para_publicar.append(
                json.dumps(
                    {
                        "event_id": ev.id,
                        "tipo_evento": ev.tipo_evento,
                        "ong_id": ev.ong_id,
                        "payload": ev.payload,
                        "correlation_id": ev.correlation_id,
                    },
                    ensure_ascii=False,
                )
            )
        s.commit()

    if _redis_client:
        for msg in mensagens_para_publicar:
            try:
                _redis_client.publish("ongsec:events", msg)
            except Exception:
                pass


def _consumir_eventos_redis():
    """Consumidor assíncrono em Redis Pub/Sub para atualizar projeção CQRS (inclui ORGANIZACAO_ATUALIZADA)."""
    if not _redis_client:
        return
    while True:
        try:
            pubsub = _redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe("ongsec:events")
            for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    with Session(engine) as s:
                        _aplicar_evento_cqrs(
                            s,
                            data.get("tipo_evento", ""),
                            data.get("ong_id", ""),
                            data.get("payload", {}),
                        )
                        s.commit()
                except Exception:
                    pass
        except Exception:
            time.sleep(3)


@app.on_event("startup")
def iniciar():
    criar_tabelas()
    try:
        with Session(engine) as s:
            pub = s.get(SeloPublico, "ong-123")
            if not pub:
                sol = Solicitacao(
                    solicitacao_id="sol-998",
                    ong_id="ong-123",
                    diagnostico_id="diag-55",
                    plano_id="plano-1",
                    estado="SELO_EMITIDO",
                    id_selo="CERT-2026-998",
                    historico=[
                        {"evento": "DIAGNOSTICO_CONCLUIDO", "servico": "audit-service", "sucesso": True},
                        {"evento": "TAREFAS_REMEDIADAS", "servico": "task-service", "sucesso": True},
                        {"evento": "SELO_GERADO", "servico": "badge-service", "sucesso": True},
                    ],
                )
                s.add(sol)
                selo = Selo(
                    id_selo="CERT-2026-998",
                    ong_id="ong-123",
                    solicitacao_id="sol-998",
                    status="ATIVO",
                    emitido_em="2026-10-10T14:00:00Z",
                )
                s.add(selo)
                pub = SeloPublico(
                    ong_id="ong-123",
                    id_selo="CERT-2026-998",
                    nome_instituicao="Associação Cuidar",
                    cnpj="12345678000199",
                    status_conformidade="ATIVO",
                    emitido_em="2026-10-10T14:00:00Z",
                    mensagem=MENSAGENS["ATIVO"],
                )
                s.add(pub)
                s.commit()
            elif not pub.cnpj:
                pub.cnpj = "12345678000199"
                s.commit()
    except Exception:
        pass
    if _redis_client:
        threading.Thread(target=_consumir_eventos_redis, daemon=True).start()


def selo_json(selo: Selo) -> dict:
    return {
        "id_selo": selo.id_selo,
        "ong_id": selo.ong_id,
        "status_conformidade": selo.status,
        "emitido_em": selo.emitido_em,
    }


def leitura_json(leitura: SeloPublico) -> dict:
    return {
        "id_selo": leitura.id_selo,
        "ong_id": leitura.ong_id,
        "nome_instituicao": leitura.nome_instituicao,
        "cnpj": leitura.cnpj,
        "status_conformidade": leitura.status_conformidade,
        "emitido_em": leitura.emitido_em,
        "mensagem": leitura.mensagem,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "badge-service"}


# ---------- Escrita: emitir e revogar selos ----------
@app.post("/v1/selos", status_code=201)
def emitir_selo(
    corpo: EmissaoSelo,
    request: Request,
    x_correlation_id: str | None = Header(default=None),
    x_simular_falha: str | None = Header(default=None),
):
    if (x_simular_falha or "").lower() == "true" or SIMULAR_FALHA_ENV:
        return erro(500, "Falha na emissão", "Falha simulada na gravação do selo", request)

    id_selo = "CERT-2026-" + uuid.uuid4().hex[:4].upper()
    emitido = agora()
    with Session(engine) as s:
        selo = Selo(
            id_selo=id_selo,
            ong_id=corpo.ong_id,
            solicitacao_id=corpo.solicitacao_id,
            status="ATIVO",
            emitido_em=emitido,
        )
        s.add(selo)
        registrar_evento(
            s,
            "SELO_GERADO",
            corpo.ong_id,
            {
                "id_selo": id_selo,
                "nome_instituicao": corpo.nome_instituicao,
                "cnpj": corpo.cnpj,
                "emitido_em": emitido,
            },
            x_correlation_id,
        )
        s.commit()
    processar_outbox()
    with Session(engine) as s:
        return selo_json(s.get(Selo, id_selo))


@app.post("/v1/selos/{id_selo}/revogacao")
def revogar(id_selo: str, request: Request, x_correlation_id: str | None = Header(default=None)):
    with Session(engine) as s:
        selo = s.get(Selo, id_selo)
        if not selo:
            return erro(404, "Selo não encontrado", id_selo, request)
        if selo.status == "REVOGADO":
            return erro(409, "Conflito de estado", "O selo já está revogado", request)
        selo.status = "REVOGADO"
        registrar_evento(s, "SELO_REVOGADO", selo.ong_id, {"id_selo": selo.id_selo}, x_correlation_id)
        s.commit()
    processar_outbox()
    with Session(engine) as s:
        return selo_json(s.get(Selo, id_selo))


@app.post("/v1/organizacoes/{ong_id}/revogacao")
def revogar_por_organizacao(ong_id: str, request: Request, x_correlation_id: str | None = Header(default=None)):
    with Session(engine) as s:
        selo = s.scalars(
            select(Selo).where(Selo.ong_id == ong_id).order_by(Selo.emitido_em.desc())
        ).first()
        if not selo:
            return erro(404, "Selo não encontrado para a organização", ong_id, request)
        if selo.status == "REVOGADO":
            return erro(409, "Conflito de estado", "O selo já está revogado", request)
        id_selo = selo.id_selo
        selo.status = "REVOGADO"
        registrar_evento(s, "SELO_REVOGADO", selo.ong_id, {"id_selo": id_selo}, x_correlation_id)
        s.commit()
    processar_outbox()
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
        selo = s.scalars(
            select(Selo).where(Selo.ong_id == ong_id).order_by(Selo.emitido_em.desc())
        ).first()
        if not selo:
            return erro(404, "Certificação não encontrada", ong_id, request)
        sol = s.get(Solicitacao, selo.solicitacao_id)
        hist = sol.historico if sol else [
            {"evento": "DIAGNOSTICO_CONCLUIDO", "servico": "audit-service", "sucesso": True},
            {"evento": "TAREFAS_REMEDIADAS", "servico": "task-service", "sucesso": True},
            {"evento": "SELO_GERADO", "servico": "badge-service", "sucesso": True},
        ]
        return {**selo_json(selo), "historico_saga_emissao": hist}


# ---------- Leitura (CQRS): lê só a tabela pronta, sem junções ----------
@app.get("/v1/consulta/organizacoes")
def listar_consulta_publica(q: str | None = None):
    with Session(engine) as s:
        stmt = select(SeloPublico).order_by(SeloPublico.emitido_em.desc())
        if q and q.strip():
            termo = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    SeloPublico.nome_instituicao.ilike(termo),
                    SeloPublico.ong_id.ilike(termo),
                    SeloPublico.id_selo.ilike(termo),
                    SeloPublico.cnpj.ilike(termo),
                )
            )
        itens = [leitura_json(r) for r in s.scalars(stmt).all()]
        return {"itens": itens, "total": len(itens)}


@app.get("/v1/consulta/organizacoes/{ong_id}")
def consulta_publica(ong_id: str, request: Request):
    with Session(engine) as s:
        leitura = s.get(SeloPublico, ong_id)
        if not leitura:
            return erro(404, "Selo não encontrado", ong_id, request)
        return leitura_json(leitura)
