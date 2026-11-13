"""Orquestrador da SAGA de emissão do selo (módulo separado do restante do badge-service)."""
import os
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Outbox, Selo, SeloPublico, Solicitacao, agora, engine

AUDIT_URL = os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000")
TASK_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8000")
ORG_URL = os.getenv("ORG_SERVICE_URL", "http://org-service:8000")
SIMULAR_FALHA_ENV = os.getenv("SIMULAR_FALHA_SELO", "false").lower() == "true"

MENSAGENS = {
    "ATIVO": "Instituição verificada e em conformidade com as diretrizes da LGPD.",
    "REVOGADO": "Selo revogado: a instituição não está mais em conformidade.",
}


class PreCondicaoFalhou(Exception):
    """Diagnóstico sem score ou plano com tarefa pendente: a SAGA nem abre (HTTP 422)."""


class DependenciaIndisponivel(Exception):
    """Outro serviço não respondeu (HTTP 503)."""


# ---------- Chamadas aos outros serviços (pela rede interna) ----------
def _chamar(metodo: str, url: str, correlation_id: str | None):
    try:
        r = httpx.request(metodo, url, timeout=5.0,
                          headers={"X-Correlation-ID": correlation_id or ""})
    except httpx.HTTPError as e:
        raise DependenciaIndisponivel(url) from e
    return r.status_code, (r.json() if r.content else None)


def consultar_diagnostico(diagnostico_id, corr):
    return _chamar("GET", f"{AUDIT_URL}/v1/diagnosticos/{diagnostico_id}", corr)


def consultar_plano_atual(ong_id, corr):
    return _chamar("GET", f"{TASK_URL}/v1/organizacoes/{ong_id}/plano-atual", corr)


def reabrir_plano(plano_id, corr):
    return _chamar("POST", f"{TASK_URL}/v1/planos/{plano_id}/reabertura", corr)


def consultar_nome_instituicao(ong_id, corr) -> str:
    try:
        status, corpo = _chamar("GET", f"{ORG_URL}/v1/organizacoes/{ong_id}", corr)
        if status == 200 and corpo:
            return corpo["nome_instituicao"]
    except DependenciaIndisponivel:
        pass
    return f"Organização {ong_id}"  # plano B: a consulta pública não deve depender do org-service


# ---------- Outbox + projetor (relay e projeção do CQRS) ----------
def registrar_evento(s: Session, tipo: str, ong_id: str, payload: dict, corr: str | None):
    s.add(Outbox(id=uuid.uuid4().hex, tipo_evento=tipo, ong_id=ong_id, payload=payload,
                 correlation_id=corr, criado_em=agora()))


def processar_outbox():
    """Lê eventos pendentes, atualiza o modelo de leitura (upsert) e marca como enviado.
    Na Parte 4 o 'relay' publicará no broker; aqui o projetor roda no próprio serviço."""
    with Session(engine) as s:
        pendentes = s.scalars(select(Outbox).where(Outbox.enviado_em.is_(None))
                              .order_by(Outbox.criado_em)).all()
        for ev in pendentes:
            leitura = s.get(SeloPublico, ev.ong_id)
            if ev.tipo_evento == "SELO_GERADO":
                dados = dict(id_selo=ev.payload["id_selo"], nome_instituicao=ev.payload["nome_instituicao"],
                             status_conformidade="ATIVO", emitido_em=ev.payload["emitido_em"],
                             mensagem=MENSAGENS["ATIVO"])
                if leitura:
                    for k, v in dados.items():
                        setattr(leitura, k, v)
                else:
                    s.add(SeloPublico(ong_id=ev.ong_id, **dados))
            elif ev.tipo_evento == "SELO_REVOGADO" and leitura:
                leitura.status_conformidade = "REVOGADO"
                leitura.mensagem = MENSAGENS["REVOGADO"]
            ev.enviado_em = agora()
        s.commit()


def revogar_selo(s: Session, selo: Selo, corr: str | None):
    selo.status = "REVOGADO"
    registrar_evento(s, "SELO_REVOGADO", selo.ong_id, {"id_selo": selo.id_selo}, corr)


def _historico(s: Session, sol: Solicitacao, evento: str, servico: str, sucesso: bool = True):
    sol.historico = list(sol.historico) + [{"evento": evento, "servico": servico, "sucesso": sucesso}]


# ---------- A SAGA ----------
def iniciar_saga(ong_id, diagnostico_id, plano_id, idempotency_key, corr, simular_falha) -> str:
    # Repetir a mesma Idempotency-Key devolve a mesma solicitação (não duplica selo)
    if idempotency_key:
        with Session(engine) as s:
            ja = s.scalars(select(Solicitacao).where(
                Solicitacao.idempotency_key == idempotency_key)).first()
            if ja:
                return ja.solicitacao_id

    # Pré-condições: se falharem, a SAGA NEM ABRE (422) e nada é gravado
    status, diag = consultar_diagnostico(diagnostico_id, corr)
    if status != 200 or diag.get("status") != "CONCLUIDO" or diag.get("score") is None:
        raise PreCondicaoFalhou("Diagnóstico não concluído ou sem score")
    status, plano = consultar_plano_atual(ong_id, corr)
    if status != 200 or plano.get("plano_id") != plano_id or plano.get("tarefas_pendentes") != 0:
        raise PreCondicaoFalhou("O plano ainda tem tarefas pendentes")
    nome = consultar_nome_instituicao(ong_id, corr)

    # Passo 1: registra a solicitação (estado SOLICITADA) e os fatos confirmados
    sol_id = "sol-" + uuid.uuid4().hex[:6]
    with Session(engine) as s:
        sol = Solicitacao(solicitacao_id=sol_id, ong_id=ong_id, diagnostico_id=diagnostico_id,
                          plano_id=plano_id, estado="SOLICITADA", historico=[],
                          idempotency_key=idempotency_key)
        _historico(s, sol, "DIAGNOSTICO_CONCLUIDO", "audit-service")   # passo 2
        _historico(s, sol, "TAREFAS_REMEDIADAS", "task-service")       # passo 3
        s.add(sol)
        s.commit()

    # Passo 4: grava selo + evento na outbox, na MESMA transação
    try:
        with Session(engine) as s:
            sol = s.get(Solicitacao, sol_id)
            if simular_falha or SIMULAR_FALHA_ENV:
                raise RuntimeError("Falha simulada na gravação do selo")
            id_selo = "CERT-2026-" + uuid.uuid4().hex[:4].upper()
            emitido = agora()
            s.add(Selo(id_selo=id_selo, ong_id=ong_id, solicitacao_id=sol_id,
                       status="ATIVO", emitido_em=emitido))
            registrar_evento(s, "SELO_GERADO", ong_id,
                             {"id_selo": id_selo, "nome_instituicao": nome, "emitido_em": emitido}, corr)
            sol.estado, sol.id_selo = "SELO_EMITIDO", id_selo
            _historico(s, sol, "SELO_GERADO", "badge-service")
            s.commit()
        processar_outbox()
    except Exception:
        compensar(sol_id, plano_id, corr)  # desfaz o que já era visível
    return sol_id


def compensar(sol_id: str, plano_id: str, corr: str | None):
    """Compensações em ordem inversa: solicitação -> COMPENSADA, plano reaberto."""
    with Session(engine) as s:
        sol = s.get(Solicitacao, sol_id)
        sol.estado = "COMPENSADA"
        _historico(s, sol, "SOLICITACAO_COMPENSADA", "badge-service")
        s.commit()
    try:
        reabrir_plano(plano_id, corr)
        ok = True
    except DependenciaIndisponivel:
        ok = False
    with Session(engine) as s:
        sol = s.get(Solicitacao, sol_id)
        _historico(s, sol, "PLANO_REABERTO", "task-service", ok)
        s.commit()