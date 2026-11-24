import os
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Diagnostico

app = FastAPI(title='ONGSec audit-service', version='1.0.0')
security = HTTPBearer(auto_error=False)
SECRET = os.getenv('JWT_SECRET_KEY') or os.getenv('JWT_SECRET') or 'ongsec-secret-key-2026'
ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

# Núcleo fixo (5 perguntas essenciais válidas para qualquer organização)
PERGUNTAS_FIXAS = [
    {
        'id': 'p1',
        'pergunta_id': 'p1',
        'categoria': 'Governança & ANPD',
        'pergunta': 'A organização mantém inventário simplificado dos dados pessoais e sensíveis que trata (ROPA)?',
        'enunciado': 'A organização mantém inventário simplificado dos dados pessoais e sensíveis que trata (ROPA)?',
        'peso': 3,
        'justificativa_curta': 'Mapear quais dados entram, onde ficam guardados e quem acessa é a base exigida pela ANPD para entidades sem fins lucrativos.',
        'obrigatoria': True,
        'origem': 'fixa',
        'tarefa_remediacao': 'Criar inventário simplificado de dados pessoais (ROPA)',
    },
    {
        'id': 'p2',
        'pergunta_id': 'p2',
        'categoria': 'Transparência & Titulares',
        'pergunta': 'Existe Política de Privacidade clara e acessível explicando como dados de beneficiários, doadores e voluntários são usados?',
        'enunciado': 'Existe Política de Privacidade clara e acessível explicando como dados de beneficiários, doadores e voluntários são usados?',
        'peso': 2,
        'justificativa_curta': 'O princípio da transparência da LGPD obriga informar de forma simples por que os dados são coletados e com quem são compartilhados.',
        'obrigatoria': True,
        'origem': 'fixa',
        'tarefa_remediacao': 'Elaborar e publicar Política de Privacidade em linguagem simples',
    },
    {
        'id': 'p3',
        'pergunta_id': 'p3',
        'categoria': 'Governança & ANPD',
        'pergunta': 'A ONG disponibiliza canal exclusivo de contato para solicitações de titulares e comunicações da ANPD (ex.: privacidade@ong.org)?',
        'enunciado': 'A ONG disponibiliza canal exclusivo de contato para solicitações de titulares e comunicações da ANPD (ex.: privacidade@ong.org)?',
        'peso': 2,
        'justificativa_curta': 'Agentes de pequeno porte podem ser dispensados de DPO formal, mas precisam manter canal ativo de atendimento aos titulares.',
        'obrigatoria': True,
        'origem': 'fixa',
        'tarefa_remediacao': 'Publicar canal oficial de atendimento ao titular (ANPD)',
    },
    {
        'id': 'p4',
        'pergunta_id': 'p4',
        'categoria': 'Controle de Acesso & Segurança',
        'pergunta': 'Cada colaborador e voluntário utiliza conta individual protegida por autenticação em dois fatores (2FA), com revogação rápida ao sair?',
        'enunciado': 'Cada colaborador e voluntário utiliza conta individual protegida por autenticação em dois fatores (2FA), com revogação rápida ao sair?',
        'peso': 3,
        'justificativa_curta': 'Contas compartilhadas impedem rastreabilidade e 2FA bloqueia a maioria das invasões por vazamento de senha.',
        'obrigatoria': True,
        'origem': 'fixa',
        'tarefa_remediacao': 'Implantar contas individuais com 2FA e checklist de desligamento em 24h',
    },
    {
        'id': 'p5',
        'pergunta_id': 'p5',
        'categoria': 'Retenção & Descarte Seguro',
        'pergunta': 'Existe rotina definida para eliminar ou anonimizar dados antigos após o fim da finalidade legal, com descarte seguro de arquivos e papéis?',
        'enunciado': 'Existe rotina definida para eliminar ou anonimizar dados antigos após o fim da finalidade legal, com descarte seguro de arquivos e papéis?',
        'peso': 2,
        'justificativa_curta': 'Guardar fichas antigas indefinidamente amplia o impacto de qualquer incidente e contraria o princípio da necessidade da LGPD.',
        'obrigatoria': True,
        'origem': 'fixa',
        'tarefa_remediacao': 'Definir tabela de temporalidade e rotina de descarte seguro de dados',
    },
]

# Conjunto padrão de fallback caso a IA esteja indisponível ao compor as 5 perguntas dinâmicas
PERGUNTAS_FALLBACK = [
    {
        'id': 'p6',
        'pergunta_id': 'p6',
        'categoria': 'Proteção de Canais & Mensageria',
        'pergunta': 'Documentos, CPFs e informações sensíveis deixaram de circular sem proteção em grupos de WhatsApp ou pastas públicas?',
        'enunciado': 'Documentos, CPFs e informações sensíveis deixaram de circular sem proteção em grupos de WhatsApp ou pastas públicas?',
        'peso': 3,
        'justificativa_curta': 'Mensagens em celulares pessoais multiplicam cópias sem controle e facilitam vazamentos acidentais.',
        'obrigatoria': True,
        'origem': 'fallback',
        'tarefa_remediacao': 'Migrar troca de arquivos sensíveis do WhatsApp para repositório com controle de acesso',
    },
    {
        'id': 'p7',
        'pergunta_id': 'p7',
        'categoria': 'Continuidade & Backup',
        'pergunta': 'A instituição realiza backups regulares (regra 3-2-1) com criptografia e testa a restauração periodicamente?',
        'enunciado': 'A instituição realiza backups regulares (regra 3-2-1) com criptografia e testa a restauração periodicamente?',
        'peso': 2,
        'justificativa_curta': 'Cópias offline criptografadas protegem os cadastros assistenciais contra ransomware e falhas de equipamento.',
        'obrigatoria': True,
        'origem': 'fallback',
        'tarefa_remediacao': 'Configurar backup 3-2-1 criptografado e testar restauração',
    },
    {
        'id': 'p8',
        'pergunta_id': 'p8',
        'categoria': 'Dispositivos & Rede',
        'pergunta': 'Os computadores e celulares usados pela equipe têm atualizações automáticas, antimalware e bloqueio por senha ou criptografia de disco?',
        'enunciado': 'Os computadores e celulares usados pela equipe têm atualizações automáticas, antimalware e bloqueio por senha ou criptografia de disco?',
        'peso': 2,
        'justificativa_curta': 'Dispositivos perdidos ou desatualizados são uma das principais portas de entrada para exposição de dados.',
        'obrigatoria': True,
        'origem': 'fallback',
        'tarefa_remediacao': 'Habilitar atualizações automáticas, antimalware e proteção de tela nos dispositivos',
    },
    {
        'id': 'p9',
        'pergunta_id': 'p9',
        'categoria': 'Dados Sensíveis & Menores',
        'pergunta': 'Quando a ONG trata dados de saúde ou de crianças e adolescentes, há registro de base legal ou consentimento específico dos responsáveis (Arts. 11 e 14 LGPD)?',
        'enunciado': 'Quando a ONG trata dados de saúde ou de crianças e adolescentes, há registro de base legal ou consentimento específico dos responsáveis (Arts. 11 e 14 LGPD)?',
        'peso': 3,
        'justificativa_curta': 'Dados sensíveis e de menores possuem proteção reforçada na LGPD e exigem cuidado jurídico específico.',
        'obrigatoria': True,
        'origem': 'fallback',
        'tarefa_remediacao': 'Adequar termos de consentimento específico para menores e dados sensíveis',
    },
    {
        'id': 'p10',
        'pergunta_id': 'p10',
        'categoria': 'Planilhas & Registros Físicos',
        'pergunta': 'Fichas em papel e planilhas cadastrais ficam guardadas em armários trancados ou arquivos protegidos por senha, acessíveis apenas a quem precisa?',
        'enunciado': 'Fichas em papel e planilhas cadastrais ficam guardadas em armários trancados ou arquivos protegidos por senha, acessíveis apenas a quem precisa?',
        'peso': 2,
        'justificativa_curta': 'A LGPD também protege dados em suporte físico e planilhas locais compartilhadas na equipe.',
        'obrigatoria': True,
        'origem': 'fallback',
        'tarefa_remediacao': 'Restringir acesso físico às fichas em papel e proteger planilhas com senha',
    },
]

PERGUNTAS = PERGUNTAS_FIXAS + PERGUNTAS_FALLBACK
QUESTIONARIO_ID = 'q-lgpd-ig1'


def problem(code, detail):
    return JSONResponse(status_code=code, media_type='application/problem+json', content={
        'type': f'https://ongsec.local/erros/{code}', 'title': 'Erro na requisição',
        'status': code, 'detail': detail})


@app.exception_handler(HTTPException)
async def http_error(_request, exc):
    return problem(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    return problem(400, str(exc.errors()))


class Resposta(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pergunta_id: str
    valor: str


class ConjuntoRespostas(BaseModel):
    model_config = ConfigDict(extra='forbid')
    respostas: list[Resposta]


class AberturaDiagnostico(BaseModel):
    model_config = ConfigDict(extra='ignore')
    perguntas: list[dict] | None = None
    substituir_rascunho: bool = False


def auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if not credentials:
        raise HTTPException(401, 'Token JWT ausente')
    try:
        return jwt.decode(credentials.credentials, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, 'Token JWT inválido ou expirado')


def permitted(ong_id, user):
    if user.get('role') == 'ADMIN':
        return
    if user.get('ong_id') != ong_id:
        raise HTTPException(403, 'Sem permissão sobre a organização')


def find_diag(db, diagnostico_id, user):
    obj = db.get(Diagnostico, diagnostico_id)
    if obj is None:
        raise HTTPException(404, 'Diagnóstico não encontrado')
    permitted(obj.ong_id, user)
    return obj


def serialize(obj):
    return {
        'diagnostico_id': obj.diagnostico_id,
        'ong_id': obj.ong_id,
        'questionario_id': obj.questionario_id,
        'status': obj.status,
        'score': obj.score,
        'perguntas': obj.perguntas if getattr(obj, 'perguntas', None) else PERGUNTAS,
        'respostas': obj.respostas,
        'concluido_em': obj.concluido_em.isoformat() if obj.concluido_em else None,
    }


@app.on_event('startup')
def create_tables():
    import time
    for _ in range(30):
        try:
            Base.metadata.create_all(bind=engine)
            if 'postgresql' in str(engine.url):
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS perguntas JSONB NOT NULL DEFAULT '[]'::jsonb"))
            break
        except Exception:
            time.sleep(2)
    try:
        with Session(engine) as s:
            if not s.scalar(select(Diagnostico).where(Diagnostico.ong_id == 'ong-123')):
                diag = Diagnostico(diagnostico_id='diag-55', ong_id='ong-123',
                                   questionario_id=QUESTIONARIO_ID, status='CONCLUIDO',
                                   score=92, concluido_em=datetime.now(timezone.utc),
                                   respostas=[{'pergunta_id': 'p1', 'valor': 'SIM'},
                                              {'pergunta_id': 'p2', 'valor': 'SIM'}],
                                   abertura_key='seed-abertura', conclusao_key='seed-conclusao')
                s.add(diag)
                s.commit()
    except Exception:
        pass


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


@app.get('/v1/questionario')
def questionario(_user: dict = Depends(auth)):
    return {
        'questionario_id': QUESTIONARIO_ID,
        'versao': '2026.2',
        'perguntas': PERGUNTAS,
        'perguntas_fixas': PERGUNTAS_FIXAS,
        'perguntas_fallback': PERGUNTAS_FALLBACK,
    }


@app.post('/v1/organizacoes/{ongId}/diagnosticos', status_code=201)
def abrir_diagnostico(
    ongId: str,
    response: Response,
    dados: AberturaDiagnostico | None = Body(default=None),
    idempotency_key: str = Header(..., alias='Idempotency-Key'),
    db: Session = Depends(get_db),
    user: dict = Depends(auth),
):
    permitted(ongId, user)
    antigo = db.scalar(select(Diagnostico).where(Diagnostico.abertura_key == idempotency_key))
    if antigo:
        if antigo.ong_id != ongId:
            raise HTTPException(409, 'Chave de idempotência utilizada por outra organização')
        response.status_code = 200
        return serialize(antigo)
    perguntas_escolhidas = dados.perguntas if (dados and dados.perguntas) else PERGUNTAS
    q_id = 'q-lgpd-hibrido' if (dados and dados.perguntas) else QUESTIONARIO_ID

    pendente = db.scalar(select(Diagnostico).where(Diagnostico.ong_id == ongId,
                     Diagnostico.status.in_(['RASCUNHO', 'EM_ANDAMENTO'])))
    if pendente:
        if dados and dados.substituir_rascunho:
            pendente.perguntas = perguntas_escolhidas
            pendente.questionario_id = q_id
            pendente.respostas = []
            pendente.status = 'RASCUNHO'
            db.commit()
            db.refresh(pendente)
            response.status_code = 200
            return serialize(pendente)
        raise HTTPException(409, 'Já existe diagnóstico em andamento')
    obj = Diagnostico(diagnostico_id='diag-' + uuid4().hex[:12], ong_id=ongId,
                      questionario_id=q_id, status='RASCUNHO',
                      score=None, concluido_em=None, perguntas=perguntas_escolhidas,
                      respostas=[], abertura_key=idempotency_key)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    response.headers['Location'] = f'/v1/diagnosticos/{obj.diagnostico_id}'
    return serialize(obj)


@app.get('/v1/organizacoes/{ongId}/diagnosticos')
def listar_diagnosticos(ongId: str, status: str | None = None,
                         db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    if status is not None and status not in ('RASCUNHO', 'EM_ANDAMENTO', 'CONCLUIDO'):
        raise HTTPException(400, 'Status inválido')
    query = select(Diagnostico).where(Diagnostico.ong_id == ongId).order_by(Diagnostico.concluido_em.desc().nulls_first())
    if status:
        query = query.where(Diagnostico.status == status)
    return {'itens': [serialize(x) for x in db.scalars(query).all()]}


@app.get('/v1/diagnosticos/{diagnosticoId}')
def obter_diagnostico(diagnosticoId: str, db: Session = Depends(get_db), user: dict = Depends(auth)):
    return serialize(find_diag(db, diagnosticoId, user))


@app.put('/v1/diagnosticos/{diagnosticoId}/respostas')
def substituir_respostas(diagnosticoId: str, dados: ConjuntoRespostas,
                        db: Session = Depends(get_db), user: dict = Depends(auth)):
    obj = find_diag(db, diagnosticoId, user)
    if obj.status == 'CONCLUIDO':
        raise HTTPException(409, 'Diagnóstico já concluído')
    perguntas_diag = obj.perguntas if getattr(obj, 'perguntas', None) else PERGUNTAS
    allowed = {p.get('pergunta_id') or p.get('id') for p in perguntas_diag}
    ids = [r.pergunta_id for r in dados.respostas]
    if len(ids) != len(set(ids)) or any(x not in allowed for x in ids) or any(r.valor not in ('SIM', 'NAO', 'NAO_SE_APLICA') for r in dados.respostas):
        raise HTTPException(400, 'Respostas inválidas')
    obj.respostas = [r.model_dump() for r in dados.respostas]
    obj.status = 'EM_ANDAMENTO'
    db.commit()
    db.refresh(obj)
    return serialize(obj)


@app.post('/v1/diagnosticos/{diagnosticoId}/conclusao')
def concluir_diagnostico(diagnosticoId: str, idempotency_key: str = Header(..., alias='Idempotency-Key'),
                        db: Session = Depends(get_db), user: dict = Depends(auth)):
    obj = find_diag(db, diagnosticoId, user)
    if obj.status == 'CONCLUIDO':
        if obj.conclusao_key == idempotency_key:
            return serialize(obj)
        raise HTTPException(409, 'Diagnóstico já concluído com outra chave')
    perguntas_diag = obj.perguntas if getattr(obj, 'perguntas', None) else PERGUNTAS
    answers = {r['pergunta_id']: r['valor'] for r in obj.respostas}
    if any(p.get('obrigatoria', True) and (p.get('pergunta_id') or p.get('id')) not in answers for p in perguntas_diag):
        raise HTTPException(422, 'Pergunta obrigatória sem resposta')

    total_peso = 0.0
    peso_sim = 0.0
    for p in perguntas_diag:
        pid = p.get('pergunta_id') or p.get('id')
        val = answers.get(pid)
        if val and val != 'NAO_SE_APLICA':
            w = float(p.get('peso') or 1)
            total_peso += w
            if val == 'SIM':
                peso_sim += w
    obj.score = round(100 * peso_sim / total_peso) if total_peso > 0 else 0
    obj.status = 'CONCLUIDO'
    obj.concluido_em = datetime.now(timezone.utc)
    obj.conclusao_key = idempotency_key
    db.commit()
    db.refresh(obj)
    return serialize(obj)
