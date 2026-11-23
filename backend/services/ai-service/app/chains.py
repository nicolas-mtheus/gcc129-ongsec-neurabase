"""Composição do fluxo com LangChain (Prompt | ChatOllama | StrOutputParser)."""
from __future__ import annotations

import json
import os
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
            "Responda SEMPRE em português do Brasil, de forma objetiva e fundamentada EXCLUSIVAMENTE "
            "nos dados reais da ONG obtidos pelas tools internas e nos trechos normativos recuperados pelo RAG. "
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
            "Você é um assistente de cibersegurança e LGPD. Responda em português do Brasil de forma concisa "
            "com base apenas no seu conhecimento geral e nos dados básicos da ONG, sem acesso à base normativa RAG.",
        ),
        (
            "human",
            "Dados da ONG:\n{dados_sistema}\n\nPergunta:\n{pergunta}",
        ),
    ]
)


def criar_llm() -> ChatOllama:
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.2,
        num_predict=320,
        client_kwargs={"timeout": LLM_TIMEOUT_SECONDS},
    )


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

    if usar_rag:
        contexto_txt = "\n\n".join(
            f"[{c['documento']} | similaridade={c['score_similaridade']}]\n{c['trecho']}"
            for c in chunks_rag
        )
        chain = _PROMPT_COM_RAG | llm | parser
        return chain.invoke(
            {
                "dados_sistema": dados_txt,
                "contexto_rag": contexto_txt,
                "pergunta": pergunta,
            }
        )

    chain = _PROMPT_SEM_RAG | llm | parser
    return chain.invoke({"dados_sistema": dados_txt, "pergunta": pergunta})

