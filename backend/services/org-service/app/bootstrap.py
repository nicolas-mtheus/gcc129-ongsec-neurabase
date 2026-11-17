"""Cria usuário inicial de desenvolvimento após cadastrar uma ONG.
Uso: python -m app.bootstrap <ong_id> <nome> <email> <senha>
"""
import sys
from uuid import uuid4
from pwdlib import PasswordHash
from sqlalchemy import select
from .database import SessionLocal
from .models import Organizacao, Usuario


def main():
    if len(sys.argv) != 5:
        raise SystemExit('Uso: python -m app.bootstrap <ong_id> <nome> <email> <senha>')
    _, ong_id, nome, email, senha = sys.argv
    if len(senha) < 8:
        raise SystemExit('A senha deve ter pelo menos 8 caracteres')
    with SessionLocal() as db:
        if not db.get(Organizacao, ong_id):
            raise SystemExit('Organização não encontrada')
        if db.scalar(select(Usuario).where(Usuario.email == email)):
            raise SystemExit('E-mail já cadastrado')
        db.add(Usuario(usuario_id='usr-' + uuid4().hex[:12], ong_id=ong_id, nome=nome,
                       email=email, senha_hash=PasswordHash.recommended().hash(senha)))
        db.commit()
    print('Usuário inicial criado')

if __name__ == '__main__':
    main()
