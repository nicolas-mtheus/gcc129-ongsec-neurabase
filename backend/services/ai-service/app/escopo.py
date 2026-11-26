"""Filtro de escopo do assistente: só responde sobre LGPD, segurança da informação e o ONGSec."""
from __future__ import annotations

import re
import unicodedata

MENSAGEM_FORA_DO_ESCOPO = (
    "Sou o Consultor Virtual do ONGSec e só posso ajudar com LGPD, segurança da informação "
    "e o uso da plataforma (diagnóstico, tarefas e selo). Pode reformular a pergunta nesse tema?"
)

_PALAVRAS_DO_DOMINIO = (
    "lgpd", "anpd", "privacidade", "dado", "dados", "seguranca", "senha", "backup", "criptograf",
    "vazamento", "incidente", "consentimento", "titular", "ong", "selo", "score", "diagnostico",
    "tarefa", "plano de acao", "auditoria", "conformidade", "phishing", "ransomware", "malware",
    "whatsapp", "planilha", "politica", "termo", "acesso", "autenticacao", "doador", "beneficiario",
    "cert.br", "cis", "sebrae", "ongsec", "saga", "certificacao", "risco", "ciberseguranca",
    "firewall", "antivirus", "2fa", "verificacao em duas", "compartilhamento", "retencao", "dpo",
    "encarregado", "adequacao", "controle",
)

# Pedidos de código: sempre fora do escopo (o assistente é consultor, não programador).
_PEDIDO_DE_CODIGO = re.compile(
    r"(c\+\+|\bc#|\bpython\b|\bjava\b|javascript|typescript|\bphp\b|\brust\b|golang|kotlin|\bswift\b|"
    r"\bhtml\b|\bcss\b|\bsql\b|"
    r"(escreva|gere|crie|faca|monte|implemente)\s+(um|uma)?\s*(codigo|programa|script|funcao|algoritmo|classe|app|aplicativo|site)|"
    r"\bcodigo\s+(em|de|para)\b|\balgoritmo\b)"
)

# Assuntos claramente alheios ao produto.
_ASSUNTO_ALHEIO = re.compile(
    r"(receita\s+de|piada|poema|poesia|letra\s+de\s+musica|horoscopo|futebol|previsao\s+do\s+tempo|"
    r"capital\s+d[aoe]|quem\s+(ganhou|foi|e)\s|quanto\s+e\s+\d|resolva|traduza|filme|serie\s+d[eo]|"
    r"namorad[oa]|dieta|jogo\s+d[eo])"
)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def fora_do_escopo(pergunta: str) -> bool:
    """True quando a pergunta não é sobre LGPD, segurança ou o ONGSec."""
    t = _normalizar(pergunta or "")
    if _PEDIDO_DE_CODIGO.search(t):
        return True
    tem_dominio = any(p in t for p in _PALAVRAS_DO_DOMINIO)
    if _ASSUNTO_ALHEIO.search(t) and not tem_dominio:
        return True
    # Perguntas longas sem nenhuma palavra do tema são recusadas; as curtas (ex.: "e como faço isso?")
    # passam, porque podem ser continuação da conversa.
    return not tem_dominio and len(t.split()) >= 7
