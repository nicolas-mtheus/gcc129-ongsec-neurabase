# CIS Critical Security Controls v8 (IG1) para Pequenas Organizações e ONGs

## 1. Inventário e Controle de Ativos Corporativos e Dados (CIS Control 1 e 3)
A organização deve manter uma lista atualizada de todos os equipamentos (notebooks, celulares institucionais, servidores) e das bases onde armazena dados pessoais. Dados em trânsito na web devem usar HTTPS (TLS 1.2+) e discos de dispositivos portáteis devem usar criptografia completa (BitLocker ou LUKS).

## 2. Gestão de Contas e Revogação de Credenciais em até 24 Horas (CIS Control 5 e 6)
Voluntários temporários, estagiários ou ex-colaboradores frequentemente mantêm acesso a planilhas e e-mails após o desligamento. O controle IG1 exige **revogação de todas as credenciais e tokens em no máximo 24 horas** após o encerramento do vínculo. Contas genéricas compartilhadas (como `admin@ong.org` usado por várias pessoas) devem ser eliminadas.

## 3. Princípio do Menor Privilégio (Least Privilege)
Cada integrante da ONG deve acessar somente os dados estritamente necessários à sua função: a equipe de captação de recursos acessa dados de doadores para recibos fiscais, mas não deve ter acesso a prontuários médicos ou fichas sociais de assistidos em situação de vulnerabilidade.

## 4. Atualizações Automáticas e Antimalware (CIS Control 7 e 10)
Sistemas operacionais, navegadores e pacotes de software devem receber atualizações de segurança automaticamente em até 7 dias após publicação de correções críticas, acompanhados de proteção antimalware ativa e firewall local habilitado.

