"""Composição do fluxo com LangChain (Prompt | ChatOllama | StrOutputParser)."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deephat:latest")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60.0"))

PERGUNTAS_AVALIACAO_RAG = [
    {
        "id": "q1",
        "titulo": "Dispensa de DPO pela ANPD",
        "pergunta": "Segundo a Resolução CD/ANPD nº 2/2022, uma ONG de pequeno porte precisa indicar um Encarregado (DPO) formal ou basta um canal de comunicação?",
    },
    {
        "id": "q2",
        "titulo": "Política de Privacidade para Abrigo Infantil",
        "pergunta": "Quais itens obrigatórios a Política de Privacidade da Associação Cuidar deve conter para tratar dados de crianças e adolescentes?",
    },
    {
        "id": "q3",
        "titulo": "Regra de Backup e WhatsApp (CERT.br)",
        "pergunta": "Qual é a política de backup recomendada pela cartilha CERT.br e como devemos tratar planilhas de beneficiários enviadas por WhatsApp?",
    },
    {
        "id": "q4",
        "titulo": "Desligamento de Voluntários (CIS IG1)",
        "pergunta": "Em quanto tempo devemos revogar as credenciais de ex-voluntários segundo o CIS Controls v8 IG1?",
    },
    {
        "id": "q5",
        "titulo": "Elegibilidade ao Selo e Compensação SAGA",
        "pergunta": "Qual o score mínimo e a condição das tarefas no ONGSec para emitir o selo, e o que acontece com o score se a SAGA precisar compensar?",
    },
]

_PROMPT_COM_RAG = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Você é o Consultor Virtual de Cibersegurança e Conformidade LGPD da plataforma ONGSec. "
            "Responda somente sobre LGPD, segurança da informação e o uso do ONGSec. Se a pergunta for de outro assunto, "
            "ou pedir código, receitas ou qualquer coisa fora desse tema, recuse educadamente em uma frase e não atenda ao pedido. "
            "Responda SEMPRE em português do Brasil, de forma objetiva, prática e fundamentada "
            "nos dados reais da ONG obtidos pelas tools internas e nos trechos normativos recuperados pelo RAG.\n\n"
            "Contexto automático da ONG atendida:\n{perfil_resumo}\n\n"
            "Sempre considere o público atendido e os canais de coleta reais da instituição ao responder. "
            "Cite os normativos (ANPD, CERT.br, CIS IG1, SEBRAE ou regras ONGSec) presentes no contexto.",
        ),
        (
            "human",
            "Dados reais da ONG consultados via LangChain Tools:\n{dados_sistema}\n\n"
            "Trechos normativos recuperados pelo RAG:\n{contexto_rag}\n\n"
            "Pergunta do gestor:\n{pergunta}",
        ),
    ]
)

_PROMPT_SEM_RAG = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Você é um assistente de cibersegurança e LGPD. "
            "Responda somente sobre LGPD, segurança da informação e o uso do ONGSec. Se a pergunta for de outro assunto, "
            "ou pedir código, receitas ou qualquer coisa fora desse tema, recuse educadamente em uma frase e não atenda ao pedido. "
            "Responda em português do Brasil de forma concisa "
            "considerando o perfil real da ONG:\n{perfil_resumo}\n"
            "Use apenas seu conhecimento geral e os dados básicos da ONG, sem acesso à base normativa RAG.",
        ),
        (
            "human",
            "Dados da ONG:\n{dados_sistema}\n\nPergunta:\n{pergunta}",
        ),
    ]
)

_PROMPT_PERGUNTAS_DINAMICAS = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Você é um auditor especialista em LGPD (Lei 13.709/2018) e segurança da informação para ONGs brasileiras. "
            "Sua tarefa é gerar perguntas de diagnóstico LGPD personalizadas para a realidade de uma ONG.\n"
            "REGRAS ESTRITAS:\n"
            "1. Retorne EXCLUSIVAMENTE um JSON válido, sem markdown, sem explicações fora do JSON.\n"
            "2. O JSON deve seguir exatamente este contrato:\n"
            '{{"perguntas": [{{"id": "dyn-1", "pergunta": "...", "categoria": "...", "peso": 3, '
            '"justificativa_curta": "...", "tarefa_remediacao": "..."}}]}}\n'
            "3. Gere exatamente {quantidade} perguntas respondíveis com SIM / NÃO / NÃO SE APLICA.\n"
            "4. Adapte diretamente ao público atendido (ex.: consentimento parental Art. 14 para crianças, dados sensíveis Art. 11 para saúde) "
            "e aos canais de coleta (ex.: WhatsApp, formulários em papel, planilhas, site próprio, redes sociais).\n"
            "5. Campo 'peso' deve ser inteiro 1, 2 ou 3. 'justificativa_curta' deve ter no máximo 180 caracteres. Escreva em português do Brasil.",
        ),
        (
            "human",
            "Perfil da ONG:\n{perfil_json}\n\nGere exatamente {quantidade} perguntas dinâmicas em JSON estrito.",
        ),
    ]
)

_PROMPT_PLANO_ACAO = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Você é um consultor prático de adequação à LGPD para organizações do terceiro setor no Brasil.\n"
            "REGRAS ESTRITAS:\n"
            "1. Retorne EXCLUSIVAMENTE um JSON válido, sem texto fora do JSON.\n"
            "2. Contrato obrigatório:\n"
            '{{"tarefas": [{{"pergunta_id": "p1", "titulo": "ação prática citando o público/canal da ONG", "prazo_dias": 15}}]}}\n'
            "3. Para cada item não conforme recebido, crie 1 tarefa prática e acionável citando diretamente "
            "a realidade da ONG (atividades, público atendido e canais de coleta de dados).\n"
            "4. 'titulo' deve ser claro, objetivo e direto para um gestor não técnico (máx. 140 caracteres).",
        ),
        (
            "human",
            "Perfil da ONG:\n{perfil_json}\n\nScore do diagnóstico: {score}%\n"
            "Controles marcados como NÃO conformes:\n{nao_conformes_json}\n\nGere as tarefas personalizadas em JSON estrito.",
        ),
    ]
)


def _formatar_perfil_ong(contexto_ong: dict[str, Any]) -> str:
    perfil = contexto_ong.get("perfil_ong") or {}
    nome = perfil.get("nome_instituicao") or perfil.get("ong_id") or "ONG"
    desc = perfil.get("descricao_atividades") or "Atividades sociais não detalhadas ainda"
    publico = ", ".join(perfil.get("publico_atendido") or []) or "Não informado"
    canais = ", ".join(perfil.get("canais_coleta_dados") or []) or "Não informado"
    return (
        f"- Organização: {nome}\n"
        f"- Atividades: {desc}\n"
        f"- Público atendido: {publico}\n"
        f"- Canais de coleta de dados: {canais}"
    )


def criar_llm(num_predict: int = 320, temperature: float = 0.2) -> ChatOllama:
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
        num_predict=num_predict,
        client_kwargs={"timeout": LLM_TIMEOUT_SECONDS},
    )


def _extrair_json_seguro(texto: str) -> Any:
    limpo = (texto or "").strip()
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpo, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", limpo)
        if not m:
            raise ValueError("Resposta do modelo não contém JSON válido")
        return json.loads(m.group(1))


def executar_chain_consultoria(
    pergunta: str,
    contexto_ong: dict[str, Any],
    chunks_rag: list[dict[str, Any]],
    usar_rag: bool = True,
) -> str:
    """Executa a chain LCEL (ChatPromptTemplate | ChatOllama | StrOutputParser)."""
    llm = criar_llm()
    parser = StrOutputParser()
    dados_txt = json.dumps(contexto_ong, ensure_ascii=False, indent=2)
    perfil_resumo = _formatar_perfil_ong(contexto_ong)

    if usar_rag:
        contexto_txt = "\n\n".join(
            f"[{c['documento']} | similaridade={c['score_similaridade']}]\n{c['trecho']}"
            for c in chunks_rag
        )
        chain = _PROMPT_COM_RAG | llm | parser
        return chain.invoke(
            {
                "perfil_resumo": perfil_resumo,
                "dados_sistema": dados_txt,
                "contexto_rag": contexto_txt,
                "pergunta": pergunta,
            }
        )

    chain = _PROMPT_SEM_RAG | llm | parser
    return chain.invoke({"perfil_resumo": perfil_resumo, "dados_sistema": dados_txt, "pergunta": pergunta})


def gerar_perguntas_dinamicas_llm(perfil_ong: dict[str, Any], quantidade: int = 5) -> list[dict[str, Any]]:
    """Gera perguntas dinâmicas personalizadas em JSON estrito via LangChain + ChatOllama."""
    llm = criar_llm(num_predict=950, temperature=0.15)
    chain = _PROMPT_PERGUNTAS_DINAMICAS | llm | StrOutputParser()
    bruto = chain.invoke(
        {
            "perfil_json": json.dumps(perfil_ong, ensure_ascii=False, indent=2),
            "quantidade": quantidade,
        }
    )
    parsed = _extrair_json_seguro(bruto)
    lista = parsed.get("perguntas") if isinstance(parsed, dict) else parsed
    if not isinstance(lista, list):
        raise ValueError("JSON sem lista de perguntas")

    normalizadas: list[dict[str, Any]] = []
    for idx, item in enumerate(lista[:quantidade], start=1):
        if not isinstance(item, dict):
            continue
        enunciado = str(item.get("pergunta") or item.get("enunciado") or "").strip()
        if len(enunciado) < 12:
            continue
        peso_raw = item.get("peso", 2)
        try:
            peso = max(1, min(3, int(peso_raw)))
        except Exception:
            peso = 2
        pid = f"dyn-{idx}"
        categoria = str(item.get("categoria") or "Riscos Específicos da ONG").strip()[:60]
        justificativa = str(
            item.get("justificativa_curta") or "Controle específico para o público e canais da organização."
        ).strip()[:220]
        tarefa = str(
            item.get("tarefa_remediacao") or f"Adequar controle: {enunciado[:90]}"
        ).strip()[:160]
        normalizadas.append(
            {
                "id": pid,
                "pergunta_id": pid,
                "pergunta": enunciado,
                "enunciado": enunciado,
                "categoria": categoria,
                "peso": peso,
                "justificativa_curta": justificativa,
                "obrigatoria": True,
                "origem": "dinamica",
                "tarefa_remediacao": tarefa,
            }
        )
    if len(normalizadas) < min(3, quantidade):
        raise ValueError(f"Quantidade insuficiente de perguntas válidas ({len(normalizadas)})")
    return normalizadas


def personalizar_plano_acao_llm(
    perfil_ong: dict[str, Any],
    nao_conformes: list[dict[str, Any]],
    score: int,
) -> list[dict[str, Any]]:
    """Personaliza títulos e prazos das tarefas do Plano de Ação citando público e canais da ONG."""
    if not nao_conformes:
        return []
    llm = criar_llm(num_predict=850, temperature=0.2)
    chain = _PROMPT_PLANO_ACAO | llm | StrOutputParser()
    bruto = chain.invoke(
        {
            "perfil_json": json.dumps(perfil_ong, ensure_ascii=False, indent=2),
            "score": score,
            "nao_conformes_json": json.dumps(nao_conformes, ensure_ascii=False, indent=2),
        }
    )
    parsed = _extrair_json_seguro(bruto)
    lista = parsed.get("tarefas") if isinstance(parsed, dict) else parsed
    if not isinstance(lista, list) or not lista:
        raise ValueError("JSON sem lista de tarefas")

    mapa_entrada = {str(x.get("pergunta_id")): x for x in nao_conformes if x.get("pergunta_id")}
    resultado: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for idx, item in enumerate(lista):
        if not isinstance(item, dict):
            continue
        pid = str(item.get("pergunta_id") or "").strip()
        if pid not in mapa_entrada and idx < len(nao_conformes):
            pid = str(nao_conformes[idx].get("pergunta_id") or "").strip()
        if not pid or pid not in mapa_entrada or pid in vistos:
            continue
        titulo = str(item.get("titulo") or "").strip()
        if not titulo:
            continue
        try:
            prazo_dias = max(5, min(90, int(item.get("prazo_dias") or 15)))
        except Exception:
            prazo_dias = 15
        vistos.add(pid)
        resultado.append({"pergunta_id": pid, "titulo": titulo[:160], "prazo_dias": prazo_dias})

    for pid, orig in mapa_entrada.items():
        if pid not in vistos:
            resultado.append(
                {
                    "pergunta_id": pid,
                    "titulo": str(orig.get("tarefa_remediacao") or f"Adequar controle {pid}")[:160],
                    "prazo_dias": 15,
                }
            )
    if not resultado:
        raise ValueError("Lista de tarefas vazia após validação")
    return resultado[:len(nao_conformes)]

