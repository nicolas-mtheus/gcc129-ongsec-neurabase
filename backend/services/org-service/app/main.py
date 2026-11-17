import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Organizacao, Usuario

app = FastAPI(title='ONGSec org-service', version='1.0.0')
security = HTTPBearer(auto_error=False)
password_hash = PasswordHash.recommended()
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY') or os.getenv('JWT_SECRET') or 'ongsec-secret-key-2026'
revoked_tokens: set[str] = set()  # Apenas desenvolvimento; use armazenamento compartilhado em produção.


def problem(code: int, detail: str):
    return JSONResponse(status_code=code, media_type='application/problem+json', content={
        'type': f'https://ongsec.local/erros/{code}', 'title': 'Erro na requisição',
        'status': code, 'detail': detail})


@app.exception_handler(HTTPException)
async def handle_http(_request, exc):
    return problem(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def handle_validation(_request, exc):
    return problem(400, str(exc.errors()))


class NovaOrganizacao(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nome_instituicao: str = Field(min_length=1)
    cnpj: str = Field(pattern=r'^\d{14}$')
    responsavel_legal: str = Field(min_length=1)
    email: EmailStr


class OrganizacaoParcial(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nome_instituicao: str | None = None
    responsavel_legal: str | None = None
    email: EmailStr | None = None


class OrganizacaoOut(NovaOrganizacao):
    ong_id: str
    criada_em: datetime
    model_config = ConfigDict(from_attributes=True)


class NovoUsuario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nome: str = Field(min_length=1)
    email: EmailStr
    senha: str = Field(min_length=8)


class UsuarioOut(BaseModel):
    usuario_id: str
    ong_id: str
    nome: str
    email: EmailStr
    model_config = ConfigDict(from_attributes=True)


class Credenciais(BaseModel):
    email: EmailStr
    senha: str


def auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if not credentials:
        raise HTTPException(401, 'Token JWT ausente')
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, 'Token JWT inválido ou expirado')
    if payload.get('jti') in revoked_tokens:
        raise HTTPException(401, 'Sessão encerrada')
    return payload


def permitted(ong_id: str, payload: dict):
    if payload.get('ong_id') != ong_id:
        raise HTTPException(403, 'Sem permissão sobre a organização')


def find_org(db: Session, ong_id: str):
    obj = db.get(Organizacao, ong_id)
    if obj is None:
        raise HTTPException(404, 'Organização não encontrada')
    return obj


@app.on_event('startup')
def create_tables():
    import time
    for _ in range(30):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except Exception:
            time.sleep(2)
    # Seed inicial demonstrativo
    try:
        with Session(engine) as s:
            org = s.get(Organizacao, 'ong-123')
            if not org:
                old = s.scalar(select(Organizacao).where(Organizacao.cnpj == '12345678000199'))
                if old and old.ong_id != 'ong-123':
                    s.delete(old)
                    s.commit()
                org = Organizacao(ong_id='ong-123', nome_instituicao='Associação Cuidar',
                                  cnpj='12345678000199', responsavel_legal='Maria da Silva',
                                  email='maria@associacaocuidar.org')
                s.add(org)
                s.commit()

            usr = s.scalar(select(Usuario).where(Usuario.email == 'maria@associacaocuidar.org'))
            if not usr:
                usr = Usuario(usuario_id='usr-1', ong_id='ong-123', nome='Maria da Silva',
                              email='maria@associacaocuidar.org',
                              senha_hash=password_hash.hash('senha-segura-123'))
                s.add(usr)
                s.commit()
    except Exception as e:
        pass


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


@app.post('/v1/organizacoes', response_model=OrganizacaoOut, status_code=201)
def criar_organizacao(dados: NovaOrganizacao, response: Response, db: Session = Depends(get_db)):
    obj = Organizacao(ong_id='ong-' + uuid4().hex[:12], **dados.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'CNPJ já cadastrado')
    db.refresh(obj)
    response.headers['Location'] = f'/v1/organizacoes/{obj.ong_id}'
    return obj


@app.get('/v1/organizacoes', response_model=dict)
def listar_organizacoes(limite: int = 20, db: Session = Depends(get_db), user: dict = Depends(auth)):
    if not 1 <= limite <= 100:
        raise HTTPException(400, 'limite deve estar entre 1 e 100')
    return {'itens': db.scalars(select(Organizacao).where(Organizacao.ong_id == user.get('ong_id')).limit(limite)).all()}


@app.get('/v1/organizacoes/{ongId}', response_model=OrganizacaoOut)
def obter_organizacao(ongId: str, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    return find_org(db, ongId)


@app.patch('/v1/organizacoes/{ongId}', response_model=OrganizacaoOut)
def atualizar_organizacao(ongId: str, dados: OrganizacaoParcial, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    changes = dados.model_dump(exclude_unset=True)
    if not changes or any(v is None for v in changes.values()):
        raise HTTPException(400, 'Informe ao menos um campo válido')
    obj = find_org(db, ongId)
    for key, value in changes.items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return obj


@app.post('/v1/organizacoes/{ongId}/usuarios', response_model=UsuarioOut, status_code=201)
def criar_usuario(ongId: str, dados: NovoUsuario, response: Response, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    find_org(db, ongId)
    obj = Usuario(usuario_id='usr-' + uuid4().hex[:12], ong_id=ongId, nome=dados.nome,
                  email=dados.email, senha_hash=password_hash.hash(dados.senha))
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'E-mail já cadastrado')
    db.refresh(obj)
    response.headers['Location'] = f'/v1/organizacoes/{ongId}/usuarios/{obj.usuario_id}'
    return obj


@app.get('/v1/organizacoes/{ongId}/usuarios')
def listar_usuarios(ongId: str, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    find_org(db, ongId)
    users = db.scalars(select(Usuario).where(Usuario.ong_id == ongId)).all()
    return {'itens': [UsuarioOut.model_validate(u).model_dump(mode='json') for u in users]}


@app.post('/v1/sessoes')
def criar_sessao(dados: Credenciais, db: Session = Depends(get_db)):
    usuario = db.scalar(select(Usuario).where(Usuario.email == dados.email))
    if usuario is None or not password_hash.verify(dados.senha, usuario.senha_hash):
        raise HTTPException(401, 'E-mail ou senha incorretos')
    expira = 3600
    payload = {'sub': usuario.usuario_id, 'usuario_id': usuario.usuario_id,
               'ong_id': usuario.ong_id, 'email': usuario.email,
               'jti': uuid4().hex, 'exp': datetime.now(timezone.utc) + timedelta(seconds=expira)}
    return {'tipo': 'Bearer', 'token': jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM),
            'expira_em': expira, 'usuario_id': usuario.usuario_id, 'ong_id': usuario.ong_id}


@app.delete('/v1/sessoes/atual', status_code=204)
def encerrar_sessao(credentials: HTTPAuthorizationCredentials | None = Depends(security), user: dict = Depends(auth)):
    revoked_tokens.add(user['jti'])
    return Response(status_code=204)
