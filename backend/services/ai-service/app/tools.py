"""Tools LangChain integradas aos microsserviços reais do ONGSec."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from langchain_core.tools import tool

ORG_URL = os.getenv("ORG_SERVICE_URL", "http://org-service:8000")
AUDIT_URL = os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000")
TASK_URL = os.getenv("TASK_SERVICE_URL", "http://task-service:8000")
BADGE_URL = os.getenv("BADGE_SERVICE_URL", "http://badge-service:8000")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", "ongsec-secret-key-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def _auth_headers(ong_id: str, corr_id: str = "") -> dict[str, str]:
    payload = {
        "sub": "ai-service",
        "usuario_id": "ai-service",
        "ong_id": ong_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    headers = {"Authorization": f"Bearer {token}"}
    if corr_id:
        headers["X-Correlation-ID"] = corr_id
    return headers


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any] | None:
    try:
        r = httpx.get(url, headers=headers, timeout=4.0)
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        return None
    return None


@tool
def consultar_perfil_ong(ong_id: str) -> dict[str, Any]:
    """Consulta os dados cadastrais e o perfil operacional real da organização no org-service."""
    data = _get_json(f"{ORG_URL}/v1/organizacoes/{ong_id}", _auth_headers(ong_id))
    if not data:
        return {"ong_id": ong_id, "erro": "org-service indisponível ou ONG não encontrada"}
    return {
        "ong_id": data.get("ong_id", ong_id),
        "nome_instituicao": data.get("nome_instituicao"),
        "cnpj": data.get("cnpj"),
        "responsavel_legal": data.get("responsavel_legal"),
        "email": data.get("email"),
        "descricao_atividades": data.get("descricao_atividades") or "",
        "publico_atendido": data.get("publico_atendido") or [],
        "canais_coleta_dados": data.get("canais_coleta_dados") or [],
        "perfil_completo": bool(data.get("perfil_completo", False)),
    }


@tool
def consultar_diagnostico_e_plano(ong_id: str) -> dict[str, Any]:
    """Consulta o score real de auditoria no audit-service e o plano de tarefas pendentes/reabertas no task-service."""
    headers = _auth_headers(ong_id)
    diag_data = _get_json(f"{AUDIT_URL}/v1/organizacoes/{ong_id}/diagnosticos", headers)
    task_data = _get_json(f"{TASK_URL}/v1/organizacoes/{ong_id}/tarefas", headers)

    diag_info: dict[str, Any] = {"status": "INDISPONIVEL", "score": None}
    if isinstance(diag_data, dict):
        itens = diag_data.get("itens") or []
        if itens:
            d0 = itens[0]
            diag_info = {
                "diagnostico_id": d0.get("diagnostico_id"),
                "status": d0.get("status"),
                "score": d0.get("score"),
            }

    plano_info: dict[str, Any] = {"tarefas_pendentes": None, "tarefas": []}
    if isinstance(task_data, dict):
        plano_info = {
            "plano_id": task_data.get("plano_id"),
            "tarefas_pendentes": task_data.get("tarefas_pendentes"),
            "tarefas": [
                {"tarefa_id": t.get("tarefa_id"), "titulo": t.get("titulo"), "status": t.get("status"), "prazo": t.get("prazo")}
                for t in task_data.get("tarefas", [])
            ],
        }

    return {"diagnostico": diag_info, "plano_remediacao": plano_info}


@tool
def consultar_selo_publico_cqrs(ong_id: str) -> dict[str, Any]:
    """Consulta o status público vigente do Selo Digital LGPD na projeção CQRS do badge-service."""
    data = _get_json(f"{BADGE_URL}/v1/consulta/organizacoes/{ong_id}", {})
    if not data:
        return {"ong_id": ong_id, "status_conformidade": "SEM_SELO"}
    return data


TOOLS_DISPONIVEIS = [consultar_perfil_ong, consultar_diagnostico_e_plano, consultar_selo_publico_cqrs]


def coletar_contexto_ong(ong_id: str) -> dict[str, Any]:
    """Invoca explicitamente as tools LangChain para obter dados reais do sistema."""
    perfil = consultar_perfil_ong.invoke({"ong_id": ong_id})
    diag_plano = consultar_diagnostico_e_plano.invoke({"ong_id": ong_id})
    selo_cqrs = consultar_selo_publico_cqrs.invoke({"ong_id": ong_id})
    return {
        "tools_executadas": [
            "consultar_perfil_ong",
            "consultar_diagnostico_e_plano",
            "consultar_selo_publico_cqrs",
        ],
        "perfil_ong": perfil,
        "diagnostico_e_plano": diag_plano,
        "selo_publico_cqrs": selo_cqrs,
    }

