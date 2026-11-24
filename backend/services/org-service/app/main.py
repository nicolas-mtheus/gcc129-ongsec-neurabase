import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import redis as redis_lib
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from pwdlib import PasswordHash
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Organizacao, Usuario

app = FastAPI(title='ONGSec org-service', version='1.0.0')
security = HTTPBearer(auto_error=False)
password_hash = PasswordHash.recommended()
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY') or os.getenv('JWT_SECRET') or 'ongsec-secret-key-2026'
ADMIN_DEFAULT_PASSWORD = os.getenv('ADMIN_DEFAULT_PASSWORD', 'admin123')
REDIS_URL = os.getenv('REDIS_URL', '')

_redis_client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
revoked_tokens_fallback: set[str] = set()


def _revogar_jti(jti: str, exp_ts: int | float | None) -> None:
    ttl = max(60, int(exp_ts - datetime.now(timezone.utc).timestamp())) if exp_ts else 3600
    if _redis_client:
        try:
            _redis_client.setex(f"revoked:jti:{jti}", ttl, "1")
            return
        except Exception:
            pass
    revoked_tokens_fallback.add(jti)


def _jti_revogado(jti: str | None) -> bool:
    if not jti:
        return False
    if _redis_client:
        try:
            if _redis_client.exists(f"revoked:jti:{jti}"):
                return True
        except Exception:
            pass
    return jti in revoked_tokens_fallback


def _publicar_evento(tipo_evento: str, ong_id: str, payload: dict) -> None:
    if not _redis_client:
        return
    try:
        msg = json.dumps({"tipo_evento": tipo_evento, "ong_id": ong_id, "payload": payload}, ensure_ascii=False)
        _redis_client.publish("ongsec:events", msg)
    except Exception:
        pass


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


class CadastroCompleto(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nome_instituicao: str = Field(min_length=2)
    cnpj: str = Field(pattern=r'^\d{14}$')
    responsavel_legal: str = Field(min_length=2)
    email: EmailStr
    senha: str = Field(min_length=8)


class OrganizacaoParcial(BaseModel):
    model_config = ConfigDict(extra='forbid')
    nome_instituicao: str | None = None
    responsavel_legal: str | None = None
    email: EmailStr | None = None


class OrganizacaoOut(NovaOrganizacao):
    ong_id: str
    descricao_atividades: str | None = None
    publico_atendido: list[str] = Field(default_factory=list)
    canais_coleta_dados: list[str] = Field(default_factory=list)
    perfil_completo: bool = False
    criada_em: datetime
    model_config = ConfigDict(from_attributes=True)


class PerfilOngIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    descricao_atividades: str = Field(min_length=5, max_length=2000)
    publico_atendido: list[str] = Field(default_factory=list)
    canais_coleta_dados: list[str] = Field(default_factory=list)


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
    role: str = 'GESTOR'
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
    if _jti_revogado(payload.get('jti')):
        raise HTTPException(401, 'Sessão encerrada')
    return payload


def permitted(ong_id: str, payload: dict):
    if payload.get('role') == 'ADMIN':
        return
    if payload.get('ong_id') != ong_id:
        raise HTTPException(403, 'Sem permissão sobre a organização')


def find_org(db: Session, ong_id: str):
    obj = db.get(Organizacao, ong_id)
    if obj is None:
        raise HTTPException(404, 'Organização não encontrada')
    return obj


def _emitir_jwt(usuario: Usuario, org: Organizacao | None = None) -> dict:
    expira = 3600
    role = getattr(usuario, 'role', None) or 'GESTOR'
    payload = {
        'sub': usuario.usuario_id,
        'usuario_id': usuario.usuario_id,
        'ong_id': usuario.ong_id,
        'email': usuario.email,
        'role': role,
        'jti': uuid4().hex,
        'exp': datetime.now(timezone.utc) + timedelta(seconds=expira),
    }
    resp = {
        'tipo': 'Bearer',
        'token': jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM),
        'expira_em': expira,
        'usuario_id': usuario.usuario_id,
        'ong_id': usuario.ong_id,
        'role': role,
    }
    if org:
        resp['nome_instituicao'] = org.nome_instituicao
    return resp


@app.on_event('startup')
def create_tables():
    import time
    for _ in range(30):
        try:
            Base.metadata.create_all(bind=engine)
            if 'postgresql' in str(engine.url):
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'GESTOR'"))
                    conn.execute(text("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS descricao_atividades TEXT"))
                    conn.execute(text("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS publico_atendido JSONB NOT NULL DEFAULT '[]'::jsonb"))
                    conn.execute(text("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS canais_coleta_dados JSONB NOT NULL DEFAULT '[]'::jsonb"))
                    conn.execute(text("ALTER TABLE organizacoes ADD COLUMN IF NOT EXISTS perfil_completo BOOLEAN NOT NULL DEFAULT FALSE"))
            break
        except Exception:
            time.sleep(2)
    try:
        with Session(engine) as s:
            org = s.get(Organizacao, 'ong-123')
            if not org:
                old = s.scalar(select(Organizacao).where(Organizacao.cnpj == '12345678000199'))
                if old and old.ong_id != 'ong-123':
                    s.delete(old)
                    s.commit()
                org = Organizacao(
                    ong_id='ong-123',
                    nome_instituicao='Associação Cuidar',
                    cnpj='12345678000199',
                    responsavel_legal='Maria da Silva',
                    email='maria@associacaocuidar.org',
                    descricao_atividades='Acolhimento social, reforço escolar e acompanhamento psicossocial de crianças e famílias em vulnerabilidade.',
                    publico_atendido=['Crianças/Adolescentes', 'Comunidade Geral', 'Doadores/Voluntários'],
                    canais_coleta_dados=['Formulários em papel', 'WhatsApp', 'Planilhas'],
                    perfil_completo=True,
                )
                s.add(org)
                s.commit()
            elif not getattr(org, 'perfil_completo', False):
                org.descricao_atividades = 'Acolhimento social, reforço escolar e acompanhamento psicossocial de crianças e famílias em vulnerabilidade.'
                org.publico_atendido = ['Crianças/Adolescentes', 'Comunidade Geral', 'Doadores/Voluntários']
                org.canais_coleta_dados = ['Formulários em papel', 'WhatsApp', 'Planilhas']
                org.perfil_completo = True
                s.commit()

            usr = s.scalar(select(Usuario).where(Usuario.email == 'maria@associacaocuidar.org'))
            if not usr:
                usr = Usuario(usuario_id='usr-1', ong_id='ong-123', nome='Maria da Silva',
                              email='maria@associacaocuidar.org', role='GESTOR',
                              senha_hash=password_hash.hash('senha-segura-123'))
                s.add(usr)
                s.commit()
            elif not usr.role:
                usr.role = 'GESTOR'
                s.commit()

            # Seed do usuário ADMIN exclusivo para monitoramento técnico e debug
            admin = s.scalar(select(Usuario).where(Usuario.email == 'admin@gmail.com'))
            if not admin:
                admin = Usuario(usuario_id='usr-admin', ong_id='ong-123', nome='Administrador Técnico',
                                email='admin@gmail.com', role='ADMIN',
                                senha_hash=password_hash.hash(ADMIN_DEFAULT_PASSWORD))
                s.add(admin)
                s.commit()
    except Exception:
        pass


@app.get('/healthz')
def healthz():
    return {'status': 'ok', 'service': 'org-service'}


@app.post('/v1/cadastro', status_code=201)
def cadastrar_ong_e_gestor(dados: CadastroCompleto, response: Response, db: Session = Depends(get_db)):
    """Autocadastro completo: cria ONG + primeiro usuário gestor na mesma transação e já emite JWT."""
    if db.scalar(select(Organizacao).where(Organizacao.cnpj == dados.cnpj)):
        raise HTTPException(409, 'CNPJ já cadastrado')
    if db.scalar(select(Usuario).where(Usuario.email == dados.email)):
        raise HTTPException(409, 'E-mail já cadastrado')

    ong_id = 'ong-' + uuid4().hex[:8]
    org = Organizacao(
        ong_id=ong_id,
        nome_instituicao=dados.nome_instituicao.strip(),
        cnpj=dados.cnpj,
        responsavel_legal=dados.responsavel_legal.strip(),
        email=dados.email,
    )
    usr = Usuario(
        usuario_id='usr-' + uuid4().hex[:8],
        ong_id=ong_id,
        nome=dados.responsavel_legal.strip(),
        email=dados.email,
        role='GESTOR',
        senha_hash=password_hash.hash(dados.senha),
    )
    db.add(org)
    db.add(usr)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Organização ou e-mail já cadastrado')
    db.refresh(org)
    db.refresh(usr)
    response.headers['Location'] = f'/v1/organizacoes/{org.ong_id}'
    return _emitir_jwt(usr, org)


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


def _serializar_perfil(obj: Organizacao) -> dict:
    return {
        'ong_id': obj.ong_id,
        'nome_instituicao': obj.nome_instituicao,
        'descricao_atividades': obj.descricao_atividades or '',
        'publico_atendido': list(obj.publico_atendido or []),
        'canais_coleta_dados': list(obj.canais_coleta_dados or []),
        'perfil_completo': bool(obj.perfil_completo),
    }


def _salvar_perfil(db: Session, ong_id: str, dados: PerfilOngIn) -> dict:
    obj = find_org(db, ong_id)
    obj.descricao_atividades = dados.descricao_atividades.strip()
    obj.publico_atendido = [str(x).strip() for x in dados.publico_atendido if str(x).strip()]
    obj.canais_coleta_dados = [str(x).strip() for x in dados.canais_coleta_dados if str(x).strip()]
    obj.perfil_completo = True
    db.commit()
    db.refresh(obj)
    return _serializar_perfil(obj)


@app.get('/v1/ong/perfil')
def obter_perfil_propria_ong(db: Session = Depends(get_db), user: dict = Depends(auth)):
    ong_id = user.get('ong_id')
    if not ong_id:
        raise HTTPException(400, 'Organização não identificada no token')
    return _serializar_perfil(find_org(db, ong_id))


@app.put('/v1/ong/perfil')
def atualizar_perfil_propria_ong(dados: PerfilOngIn, db: Session = Depends(get_db), user: dict = Depends(auth)):
    ong_id = user.get('ong_id')
    if not ong_id:
        raise HTTPException(400, 'Organização não identificada no token')
    return _salvar_perfil(db, ong_id, dados)


@app.get('/v1/organizacoes/{ongId}/perfil')
def obter_perfil_organizacao(ongId: str, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    return _serializar_perfil(find_org(db, ongId))


@app.put('/v1/organizacoes/{ongId}/perfil')
def atualizar_perfil_organizacao(ongId: str, dados: PerfilOngIn, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    return _salvar_perfil(db, ongId, dados)


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
    if 'nome_instituicao' in changes:
        _publicar_evento(
            'ORGANIZACAO_ATUALIZADA',
            obj.ong_id,
            {'nome_instituicao': obj.nome_instituicao, 'cnpj': obj.cnpj},
        )
    return obj


@app.post('/v1/organizacoes/{ongId}/usuarios', response_model=UsuarioOut, status_code=201)
def criar_usuario(ongId: str, dados: NovoUsuario, response: Response, db: Session = Depends(get_db), user: dict = Depends(auth)):
    permitted(ongId, user)
    find_org(db, ongId)
    obj = Usuario(usuario_id='usr-' + uuid4().hex[:12], ong_id=ongId, nome=dados.nome,
                  email=dados.email, role='GESTOR', senha_hash=password_hash.hash(dados.senha))
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
    org = db.get(Organizacao, usuario.ong_id)
    return _emitir_jwt(usuario, org)


@app.delete('/v1/sessoes/atual', status_code=204)
def encerrar_sessao(user: dict = Depends(auth)):
    if user.get('jti'):
        _revogar_jti(user['jti'], user.get('exp'))
    return Response(status_code=204)
