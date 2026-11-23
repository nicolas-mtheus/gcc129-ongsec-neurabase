# Cartilha de Higiene Digital CERT.br Aplicada ao Terceiro Setor

## 1. Autenticação Multifator (2FA / MFA) Obrigatória
Contas de e-mail institucional, sistemas de gestão de doadores e painéis administrativos da ONG devem utilizar **autenticação em dois fatores (2FA)** baseada em aplicativo autenticador (TOTP) ou chave física, evitando depender apenas de SMS. Essa medida mitiga mais de 90% dos ataques por roubo de senha e phishing.

## 2. Proibição de Tráfego de Dados Sensíveis em Aplicativos de Mensagem
É terminantemente desaconselhado enviar fichas médicas, CPFs, comprovantes bancários ou planilhas de beneficiários em grupos de WhatsApp ou Telegram sem criptografia de arquivo e controle de acesso. Documentos sensíveis devem permanecer exclusivamente em repositório institucional autenticado com registro de auditoria.

## 3. Política de Backup 3-2-1 Criptografado
Para proteger cadastros sociais e financeiros contra ransomware e falhas de hardware, recomenda-se a regra **3-2-1**:
- Manter **3 cópias** dos dados críticos;
- Em **2 tipos diferentes de mídia** (ex.: servidor/nuvem institucional e disco externo criptografado);
- Com **1 cópia fora do local físico** (off-site) e desconectada da rede principal (imutável ou offline).
Testes periódicos de restauração devem ser registrados semestralmente.

## 4. Gestão de Senhas e Dispositivos Compartilhados
Computadores compartilhados em abrigos e sedes administrativas devem possuir contas individuais por colaborador/voluntário, bloqueio automático de tela após 5 minutos de inatividade e gerenciador de senhas institucional (proibido anotar senhas em post-its ou usar senhas padrão).

