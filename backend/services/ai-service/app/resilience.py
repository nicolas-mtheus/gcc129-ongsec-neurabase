"""Mecanismos de resiliência para o LLM como serviço distribuído (Circuit Breaker, Timeout+Retry, Cache e Fallback)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable


class ResponseCache:
    """Cache em memória por chave normalizada com TTL configurável."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def gerar_chave(ong_id: str, pergunta: str, usar_rag: bool, estado_hash: str) -> str:
        norm = f"{ong_id.strip().lower()}|{' '.join(pergunta.lower().split())}|{usar_rag}|{estado_hash}"
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._store.get(key)
        if not item:
            self.misses += 1
            return None
        exp, val = item
        if time.time() > exp:
            self._store.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return val

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = (time.time() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()


class CircuitBreaker:
    """Circuit Breaker clássico (CLOSED -> OPEN -> HALF_OPEN) para proteger chamadas ao Ollama."""

    def __init__(self, failure_threshold: int = 2, recovery_timeout: float = 25.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "CLOSED"
        self.failures = 0
        self.opened_at: float | None = None
        self.forced_open = False

    def allow_request(self) -> bool:
        if self.forced_open:
            self.state = "OPEN"
            return False
        if self.state == "OPEN":
            if self.opened_at is not None and (time.time() - self.opened_at) >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.forced_open = False
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold or self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.opened_at = time.time()

    def force_open(self) -> None:
        self.forced_open = True
        self.state = "OPEN"
        self.opened_at = time.time()

    def reset(self) -> None:
        self.forced_open = False
        self.failures = 0
        self.opened_at = None
        self.state = "CLOSED"

    def snapshot(self) -> dict[str, Any]:
        return {
            "estado": self.state,
            "falhas_consecutivas": self.failures,
            "limiar_abertura": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout,
            "forcado_aberto": self.forced_open,
        }


class TelemetryTracker:
    """Coleta latência real medida e métricas para análise de desempenho e custo."""

    def __init__(self) -> None:
        self.latencias_llm_ms: list[float] = []
        self.latencias_cache_ms: list[float] = []
        self.latencias_fallback_ms: list[float] = []
        self.total_chamadas = 0
        self.total_retries = 0
        self.total_fallbacks = 0
        self.total_tokens_estimados = 0

    def registrar(self, modo: str, latencia_ms: float, retries: int = 0, tokens_est: int = 0) -> None:
        self.total_chamadas += 1
        self.total_retries += retries
        self.total_tokens_estimados += tokens_est
        if modo == "CACHE_HIT":
            self.latencias_cache_ms.append(latencia_ms)
        elif modo == "FALLBACK_RESILIENTE":
            self.total_fallbacks += 1
            self.latencias_fallback_ms.append(latencia_ms)
        else:
            self.latencias_llm_ms.append(latencia_ms)

    @staticmethod
    def _resumo(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {"amostras": 0, "media_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
        return {
            "amostras": len(vals),
            "media_ms": round(sum(vals) / len(vals), 2),
            "min_ms": round(min(vals), 2),
            "max_ms": round(max(vals), 2),
        }

    def relatorio(self, cache: ResponseCache, cb: CircuitBreaker, modelo: str) -> dict[str, Any]:
        # Estimativa de custo por operação (Ollama local = custo marginal de infra/energia vs API cloud equivalente)
        tokens_medios_op = 850
        custo_api_cloud_1k_usd = 0.0015  # referência GPT-4o-mini / modelo compacto equivalente (~$0.15-$0.60/1M tokens)
        custo_op_cloud_usd = round((tokens_medios_op / 1000.0) * custo_api_cloud_1k_usd, 6)
        taxa_cache = (cache.hits / max(1, cache.hits + cache.misses)) * 100.0
        return {
            "modelo_configurado": modelo,
            "provedor": "Ollama Local (self-hosted)",
            "total_requisicoes": self.total_chamadas,
            "retries_executados": self.total_retries,
            "fallbacks_acionados": self.total_fallbacks,
            "cache": {
                "hits": cache.hits,
                "misses": cache.misses,
                "taxa_acerto_pct": round(taxa_cache, 1),
            },
            "circuit_breaker": cb.snapshot(),
            "latencia_medida": {
                "llm_ollama": self._resumo(self.latencias_llm_ms),
                "cache_hit": self._resumo(self.latencias_cache_ms),
                "fallback": self._resumo(self.latencias_fallback_ms),
            },
            "estimativa_custo_escala": {
                "tokens_medios_por_consulta": tokens_medios_op,
                "custo_ollama_local_por_consulta_usd": 0.0,
                "custo_referencia_cloud_por_consulta_usd": custo_op_cloud_usd,
                "custo_cloud_1000_consultas_usd": round(custo_op_cloud_usd * 1000, 2),
                "economia_com_cache_30pct_usd_por_1000": round(custo_op_cloud_usd * 1000 * 0.30, 2),
            },
        }


cache_respostas = ResponseCache(ttl_seconds=600)
circuit_breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=25.0)
telemetria = TelemetryTracker()

LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60.0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))


def gerar_fallback_contextualizado(
    pergunta: str,
    contexto_ong: dict[str, Any],
    chunks_rag: list[dict[str, Any]],
    motivo: str,
) -> str:
    """Fallback determinístico usando os dados reais das Tools e os trechos recuperados do RAG."""
    perfil = contexto_ong.get("perfil_ong", {})
    diag_plano = contexto_ong.get("diagnostico_e_plano", {})
    diag = diag_plano.get("diagnostico", {})
    plano = diag_plano.get("plano_remediacao", {})
    selo = contexto_ong.get("selo_publico_cqrs", {})

    nome = perfil.get("nome_instituicao") or perfil.get("ong_id", "Organização")
    resp = perfil.get("responsavel_legal") or "Responsável Legal"
    desc = perfil.get("descricao_atividades") or ""
    publico = ", ".join(perfil.get("publico_atendido") or [])
    canais = ", ".join(perfil.get("canais_coleta_dados") or [])
    score = diag.get("score", "N/A")
    pendentes = plano.get("tarefas_pendentes", 0)
    tarefas = plano.get("tarefas", [])
    status_selo = selo.get("status_conformidade", "N/A")

    linhas = [
        f"[Modo Resiliente / Fallback — {motivo}]",
        f"Organização consultada via LangChain Tools: {nome} (CNPJ: {perfil.get('cnpj', 'N/A')}, Responsável: {resp}).",
    ]
    if desc or publico or canais:
        linhas.append(
            f"Perfil da ONG: atividades='{desc[:120] or 'N/I'}' | público={publico or 'N/I'} | canais={canais or 'N/I'}."
        )
    linhas.append(
        f"Estado atual no sistema: Score LGPD = {score}%, Tarefas pendentes = {pendentes}, Selo CQRS = {status_selo}."
    )
    if tarefas:
        resumo_t = "; ".join(f"{t['titulo']} [{t['status']}]" for t in tarefas)
        linhas.append(f"Plano de ação ({plano.get('plano_id', 'plano-1')}): {resumo_t}.")
    if chunks_rag:
        linhas.append("Recomendações normativas recuperadas via RAG:")
        for ch in chunks_rag[:2]:
            trecho_curto = ch["trecho"].replace("\n", " ")[:240]
            linhas.append(f"- ({ch['documento']} | sim={ch['score_similaridade']}) {trecho_curto}...")
    else:
        linhas.append("Sem recuperação RAG ativa nesta chamada; recomenda-se validar política de privacidade, 2FA e canal de atendimento ao titular (ANPD).")
    return "\n".join(linhas)


def executar_com_resiliencia(
    ong_id: str,
    pergunta: str,
    usar_rag: bool,
    usar_cache: bool,
    simular_falha_llm: bool,
    contexto_ong: dict[str, Any],
    chunks_rag: list[dict[str, Any]],
    chamar_llm: Callable[[], str],
) -> dict[str, Any]:
    t_inicio = time.perf_counter()
    estado_compacto = json.dumps(contexto_ong.get("diagnostico_e_plano", {}), sort_keys=True) + str(
        contexto_ong.get("selo_publico_cqrs", {}).get("status_conformidade")
    )
    estado_hash = hashlib.md5(estado_compacto.encode("utf-8")).hexdigest()[:10]
    cache_key = ResponseCache.gerar_chave(ong_id, pergunta, usar_rag, estado_hash)

    # 1. Cache hit (somente se não estiver simulando falha)
    if usar_cache and not simular_falha_llm:
        cached = cache_respostas.get(cache_key)
        if cached is not None:
            lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
            telemetria.registrar("CACHE_HIT", lat_ms, retries=0, tokens_est=0)
            return {
                **cached,
                "modo_operacao": "CACHE_HIT",
                "cache_hit": True,
                "retries": 0,
                "latencia_ms": lat_ms,
                "circuit_breaker": circuit_breaker.snapshot(),
            }

    # 2. Verificar Circuit Breaker
    if not circuit_breaker.allow_request():
        resposta_fb = gerar_fallback_contextualizado(
            pergunta, contexto_ong, chunks_rag, "Circuit Breaker OPEN (proteção contra falhas em cascata)"
        )
        lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
        telemetria.registrar("FALLBACK_RESILIENTE", lat_ms, retries=0, tokens_est=0)
        return {
            "resposta": resposta_fb,
            "modo_operacao": "FALLBACK_RESILIENTE",
            "cache_hit": False,
            "retries": 0,
            "latencia_ms": lat_ms,
            "circuit_breaker": circuit_breaker.snapshot(),
            "motivo_fallback": "Circuit Breaker aberto",
        }

    # 3. Chamada ao LLM remoto (Ollama) com Timeout e Retry com Exponential Backoff
    retries_feitos = 0
    ultimo_erro = ""
    for tentativa in range(LLM_MAX_RETRIES + 1):
        try:
            if simular_falha_llm:
                raise TimeoutError("Falha simulada na chamada remota ao provedor Ollama")
            resposta_llm = chamar_llm()
            circuit_breaker.record_success()
            lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
            tokens_est = max(50, int((len(pergunta) + len(resposta_llm)) / 3.5))
            telemetria.registrar("OLLAMA_DEEPHAT", lat_ms, retries=retries_feitos, tokens_est=tokens_est)

            resultado = {
                "resposta": resposta_llm,
                "modo_operacao": "OLLAMA_DEEPHAT",
                "cache_hit": False,
                "retries": retries_feitos,
                "latencia_ms": lat_ms,
                "circuit_breaker": circuit_breaker.snapshot(),
            }
            if usar_cache:
                cache_respostas.set(cache_key, {"resposta": resposta_llm})
            return resultado
        except Exception as exc:
            ultimo_erro = str(exc)
            circuit_breaker.record_failure()
            if tentativa < LLM_MAX_RETRIES and circuit_breaker.allow_request():
                retries_feitos += 1
                backoff_s = 0.4 * (2 ** (tentativa))
                time.sleep(backoff_s)
            else:
                break

    # 4. Estratégia de Fallback para indisponibilidade do modelo
    resposta_fb = gerar_fallback_contextualizado(
        pergunta, contexto_ong, chunks_rag, f"Ollama indisponível após {retries_feitos} retry(s): {ultimo_erro}"
    )
    lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
    telemetria.registrar("FALLBACK_RESILIENTE", lat_ms, retries=retries_feitos, tokens_est=0)
    return {
        "resposta": resposta_fb,
        "modo_operacao": "FALLBACK_RESILIENTE",
        "cache_hit": False,
        "retries": retries_feitos,
        "latencia_ms": lat_ms,
        "circuit_breaker": circuit_breaker.snapshot(),
        "motivo_fallback": ultimo_erro,
    }


def gerar_perguntas_fallback_perfil(perfil_ong: dict[str, Any], quantidade: int = 5) -> list[dict[str, Any]]:
    """Gera perguntas de fallback contextualizadas pelo público atendido e canais de coleta."""
    publicos = [str(p).lower() for p in (perfil_ong.get("publico_atendido") or [])]
    canais = [str(c).lower() for c in (perfil_ong.get("canais_coleta_dados") or [])]
    banco: list[dict[str, Any]] = []

    if any("criança" in p or "crianca" in p or "adolescente" in p for p in publicos):
        banco.append({
            "categoria": "Proteção de Menores (Art. 14)",
            "pergunta": "Para dados e imagens de crianças e adolescentes, a ONG obtém termo de consentimento específico assinado por um dos pais ou responsável legal?",
            "peso": 3,
            "justificativa_curta": "O Art. 14 da LGPD exige consentimento específico e destacado de pelo menos um dos pais ou responsável.",
            "tarefa_remediacao": "Implantar termo de consentimento parental para dados de crianças e adolescentes",
        })
    if any("saúde" in p or "saude" in p or "paciente" in p for p in publicos):
        banco.append({
            "categoria": "Dados Sensíveis de Saúde (Art. 11)",
            "pergunta": "Prontuários, laudos médicos e informações de saúde dos pacientes têm acesso restrito apenas à equipe técnica autorizada?",
            "peso": 3,
            "justificativa_curta": "Dados referentes à saúde são considerados sensíveis pela LGPD e exigem sigilo e controle de acesso rigorosos.",
            "tarefa_remediacao": "Restringir acesso a prontuários e laudos de saúde apenas à equipe autorizada",
        })
    if any("idoso" in p for p in publicos):
        banco.append({
            "categoria": "Atendimento a Idosos",
            "pergunta": "Os avisos de privacidade para pessoas idosas e seus familiares são apresentados com linguagem acessível e letra legível antes da coleta?",
            "peso": 2,
            "justificativa_curta": "A transparência exige que pessoas idosas e curadores compreendam facilmente o uso de seus dados.",
            "tarefa_remediacao": "Adaptar aviso de privacidade em linguagem simples para idosos e familiares",
        })
    if any("whatsapp" in c for c in canais):
        banco.append({
            "categoria": "Segurança no WhatsApp",
            "pergunta": "A equipe evita enviar CPFs, documentos ou planilhas de beneficiários em grupos abertos de WhatsApp e usa verificação em duas etapas no aplicativo?",
            "peso": 3,
            "justificativa_curta": "Celulares pessoais e grupos de WhatsApp sem PIN aumentam o risco de compartilhamento indevido de dados.",
            "tarefa_remediacao": "Proibir tráfego de fichas sensíveis no WhatsApp e ativar PIN de 2 etapas",
        })
    if any("papel" in c or "físic" in c for c in canais):
        banco.append({
            "categoria": "Fichas em Papel",
            "pergunta": "Os formulários em papel preenchidos no atendimento são armazenados em armários trancados e picotados antes do descarte?",
            "peso": 2,
            "justificativa_curta": "Documentos físicos também são regulados pela LGPD e precisam de guarda segura e descarte destrutivo.",
            "tarefa_remediacao": "Proteger fichas em papel em arquivo trancado e adotar fragmentadora no descarte",
        })
    if any("planilha" in c for c in canais):
        banco.append({
            "categoria": "Planilhas e Controle",
            "pergunta": "As planilhas de beneficiários, doadores ou voluntários possuem senha de proteção, histórico de alterações e permissão limitada por função?",
            "peso": 2,
            "justificativa_curta": "Planilhas compartilhadas sem restrição frequentemente levam à exposição acidental de CPFs e contatos.",
            "tarefa_remediacao": "Aplicar controle de acesso e proteção por senha nas planilhas da ONG",
        })
    if any("site" in c or "rede" in c or "social" in c for c in canais):
        banco.append({
            "categoria": "Site e Redes Sociais",
            "pergunta": "O site e os formulários digitais da ONG usam HTTPS e exibem aviso de privacidade antes de coletar dados de doadores ou voluntários?",
            "peso": 2,
            "justificativa_curta": "Coletas digitais precisam informar finalidade do cadastro e proteger o tráfego com criptografia HTTPS.",
            "tarefa_remediacao": "Adicionar aviso de privacidade e HTTPS nos formulários do site e redes sociais",
        })

    padrao_extra = [
        {
            "categoria": "Continuidade & Backup",
            "pergunta": "A instituição realiza backups criptografados (regra 3-2-1) dos cadastros essenciais com teste periódico de restauração?",
            "peso": 2,
            "justificativa_curta": "Cópias seguras garantem que a ONG não perca o histórico de atendimentos em falhas ou ataques.",
            "tarefa_remediacao": "Configurar rotina semanal de backup 3-2-1 criptografado",
        },
        {
            "categoria": "Doadores & Voluntários",
            "pergunta": "Os termos de voluntariado e cadastros de doadores contêm cláusula de confidencialidade e finalidade clara de contato?",
            "peso": 2,
            "justificativa_curta": "Voluntários acessam dados da comunidade e devem assumir compromisso formal de sigilo.",
            "tarefa_remediacao": "Incluir termo de confidencialidade LGPD nos cadastros de voluntários e doadores",
        },
        {
            "categoria": "Dispositivos da Equipe",
            "pergunta": "Os computadores e celulares usados pela ONG possuem senha de bloqueio, antimalware ativo e atualizações automáticas habilitadas?",
            "peso": 2,
            "justificativa_curta": "Higiene básica de dispositivos reduz vulnerabilidades exploradas por sequestro de dados.",
            "tarefa_remediacao": "Ativar bloqueio automático, antimalware e atualizações nos equipamentos da equipe",
        },
    ]
    for extra in padrao_extra:
        if len(banco) >= quantidade:
            break
        banco.append(extra)

    resultado = []
    for idx, item in enumerate(banco[:quantidade], start=1):
        pid = f"dyn-fb-{idx}"
        resultado.append({
            "id": pid,
            "pergunta_id": pid,
            "pergunta": item["pergunta"],
            "enunciado": item["pergunta"],
            "categoria": item["categoria"],
            "peso": item["peso"],
            "justificativa_curta": item["justificativa_curta"],
            "obrigatoria": True,
            "origem": "fallback",
            "tarefa_remediacao": item["tarefa_remediacao"],
        })
    return resultado


def personalizar_plano_fallback(
    perfil_ong: dict[str, Any],
    nao_conformes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enriquece as tarefas do plano com o contexto da ONG quando o LLM estiver indisponível."""
    publicos = ", ".join(perfil_ong.get("publico_atendido") or [])
    canais = ", ".join(perfil_ong.get("canais_coleta_dados") or [])
    sufixo = ""
    if publicos and canais:
        sufixo = f" (foco em {publicos} via {canais})"
    elif publicos:
        sufixo = f" (foco em {publicos})"
    elif canais:
        sufixo = f" (foco em {canais})"

    tarefas = []
    for item in nao_conformes:
        pid = str(item.get("pergunta_id") or "")
        base = str(item.get("tarefa_remediacao") or f"Adequar controle {pid}").strip()
        titulo = f"{base}{sufixo}" if sufixo and len(base) + len(sufixo) <= 155 else base[:155]
        tarefas.append({"pergunta_id": pid, "titulo": titulo, "prazo_dias": 15})
    return tarefas


def executar_json_com_resiliencia(
    simular_falha_llm: bool,
    chamar_llm_json: Callable[[], Any],
    fallback_fn: Callable[[], Any],
) -> tuple[Any, str, float]:
    """Executa chamada estruturada ao LLM com Circuit Breaker + Fallback sem travar o fluxo."""
    t_inicio = time.perf_counter()
    if simular_falha_llm or not circuit_breaker.allow_request():
        res = fallback_fn()
        lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
        telemetria.registrar("FALLBACK_RESILIENTE", lat_ms, retries=0, tokens_est=0)
        return res, "FALLBACK_ESTRUTURADO", lat_ms

    for tentativa in range(2):
        try:
            res = chamar_llm_json()
            circuit_breaker.record_success()
            lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
            telemetria.registrar("OLLAMA_DEEPHAT", lat_ms, retries=tentativa, tokens_est=240)
            return res, "OLLAMA_DEEPHAT", lat_ms
        except Exception:
            circuit_breaker.record_failure()
            if not circuit_breaker.allow_request():
                break

    res = fallback_fn()
    lat_ms = round((time.perf_counter() - t_inicio) * 1000.0, 2)
    telemetria.registrar("FALLBACK_RESILIENTE", lat_ms, retries=1, tokens_est=0)
    return res, "FALLBACK_ESTRUTURADO", lat_ms

