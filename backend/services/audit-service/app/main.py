import os
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Diagnostico

app = FastAPI(title='ONGSec audit-service', version='1.0.0')
security = HTTPBearer(auto_error=False)
SECRET = os.getenv('JWT_SECRET_KEY') or os.getenv('JWT_SECRET') or 'ongsec-secret-key-2026'
ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

# Questionário demonstrativo baseado nas perguntas exemplificadas no OpenAPI.
# A regra de pontuação deve ser validada com o grupo antes de produção.
PERGUNTAS = [
    {'pergunta_id': 'p1', 'enunciado': 'A organização mantém inventário dos dados pessoais que trata?', 'obrigatoria': True},
    {'pergunta_id': 'p2', 'enunciado': 'Existe política de privacidade publicada e revisada?', 'obrigatoria': True},
]
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


def auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if not credentials:
        raise HTTPException(401, 'Token JWT ausente')
    try:
        return jwt.decode(credentials.credentials, SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, 'Token JWT inválido ou expirado')


def permitted(ong_id, user):
    if user.get('ong_id') != ong_id:
        raise HTTPException(403, 'Sem permissão sobre a organização')


def find_diag(db, diagnostico_id, user):
    obj = db.get(Diagnostico, diagnostico_id)
    if obj is None:
        raise HTTPException(404, 'Diagnóstico não encontrado')
    permitted(obj.ong_id, user)
    return obj


def serialize(obj):
    return {'diagnostico_id': obj.diagnostico_id, 'ong_id': obj.ong_id,
            'questionario_id': obj.questionario_id, 'status': obj.status,
            'score': obj.score, 'concluido_em': obj.concluido_em.isoformat() if obj.concluido_em else None}


@app.on_event('startup')
def create_tables():
    import time
    for _ in range(30):
        try:
            Base.metadata.create_all(bind=engine)
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
    return {'questionario_id': QUESTIONARIO_ID, 'versao': '2026.1', 'perguntas': PERGUNTAS}


@app.post('/v1/organizacoes/{ongId}/diagnosticos', status_code=201)
def abrir_diagnostico(ongId: str, response: Response, idempotency_key: str = Header(..., alias='Idempotency-Key'),
                       db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    antigo = db.scalar(select(Diagnostico).where(Diagnostico.abertura_key == idempotency_key))
    if antigo:
        if antigo.ong_id != ongId:
            raise HTTPException(409, 'Chave de idempotência utilizada por outra organização')
        response.status_code = 200
        return serialize(antigo)
    pendente = db.scalar(select(Diagnostico).where(Diagnostico.ong_id == ongId,
                     Diagnostico.status.in_(['RASCUNHO', 'EM_ANDAMENTO'])))
    if pendente:
        raise HTTPException(409, 'Já existe diagnóstico em andamento')
    obj = Diagnostico(diagnostico_id='diag-' + uuid4().hex[:12], ong_id=ongId,
                      questionario_id=QUESTIONARIO_ID, status='RASCUNHO',
                      score=None, concluido_em=None, respostas=[], abertura_key=idempotency_key)
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
    query = select(Diagnostico).where(Diagnostico.ong_id == ongId)
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
    allowed = {p['pergunta_id'] for p in PERGUNTAS}
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
    answers = {r['pergunta_id']: r['valor'] for r in obj.respostas}
    if any(p['obrigatoria'] and p['pergunta_id'] not in answers for p in PERGUNTAS):
        raise HTTPException(422, 'Pergunta obrigatória sem resposta')
    applicable = [v for v in answers.values() if v != 'NAO_SE_APLICA']
    obj.score = round(100 * sum(v == 'SIM' for v in applicable) / len(applicable)) if applicable else 0
    obj.status = 'CONCLUIDO'
    obj.concluido_em = datetime.now(timezone.utc)
    obj.conclusao_key = idempotency_key
    db.commit()
    db.refresh(obj)
    return serialize(obj)
