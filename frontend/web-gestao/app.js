/**
 * ONGSec — Frontend Controller com RBAC (GESTOR vs ADMIN)
 */

let jwtToken = localStorage.getItem('ongsec_jwt_token') || '';
let currentOngId = localStorage.getItem('ongsec_ong_id') || 'ong-123';
let currentOrgName = localStorage.getItem('ongsec_org_name') || 'Associação Cuidar';
let currentUserRole = localStorage.getItem('ongsec_user_role') || 'GESTOR';
let currentDiagId = 'auto';
let currentPlanoId = 'auto';
let ultimaRespostaIA = '';
let tarefasCache = [];
let currentOngProfile = {
  descricao_atividades: '',
  publico_atendido: [],
  canais_coleta_dados: [],
  perfil_completo: false,
};

// Estado do Wizard de Diagnóstico (Gestor)
let wizardDiagId = null;
let wizardPerguntas = [];
let wizardRespostas = {};
let wizardIdx = 0;

// DOM Elements
const authSection = document.getElementById('authSection');
const userProfile = document.getElementById('userProfile');
const mainTabs = document.getElementById('mainTabs');
const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const btnShowLogin = document.getElementById('btnShowLogin');
const btnShowRegister = document.getElementById('btnShowRegister');
const toastContainer = document.getElementById('toast');

function switchTab(targetTabId) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === targetTabId);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === targetTabId);
  });
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab')));
});

if (btnShowLogin && btnShowRegister) {
  btnShowLogin.addEventListener('click', () => {
    loginForm.style.display = 'flex';
    registerForm.style.display = 'none';
    btnShowLogin.className = 'btn btn-primary btn-sm';
    btnShowRegister.className = 'btn btn-outline btn-sm';
  });
  btnShowRegister.addEventListener('click', () => {
    loginForm.style.display = 'none';
    registerForm.style.display = 'flex';
    btnShowRegister.className = 'btn btn-primary btn-sm';
    btnShowLogin.className = 'btn btn-outline btn-sm';
  });
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  let iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#3b82f6" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
  if (type === 'success') {
    iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
  } else if (type === 'error') {
    iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
  }
  toast.innerHTML = `${iconSvg} <span>${escapeHtml(message)}</span>`;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(30px)';
    toast.style.transition = 'all 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function decodeJwtRole(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return payload.role || 'GESTOR';
  } catch {
    return 'GESTOR';
  }
}

function salvarSessao(data, email) {
  jwtToken = data.token;
  currentOngId = data.ong_id || 'ong-123';
  currentOrgName = data.nome_instituicao || currentOngId;
  currentUserRole = data.role || decodeJwtRole(jwtToken);
  localStorage.setItem('ongsec_jwt_token', jwtToken);
  localStorage.setItem('ongsec_ong_id', currentOngId);
  localStorage.setItem('ongsec_org_name', currentOrgName);
  localStorage.setItem('ongsec_user_role', currentUserRole);
  localStorage.setItem('ongsec_user_email', email);
}

function aplicarVisibilidadePorPerfil(isLoggedIn, email = '') {
  if (!isLoggedIn) {
    authSection.classList.remove('hidden');
    userProfile.style.display = 'none';
    mainTabs.style.display = 'none';
    document.querySelectorAll('.admin-only').forEach(el => { el.style.display = 'none'; });
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    return;
  }

  authSection.classList.add('hidden');
  userProfile.style.display = 'flex';
  mainTabs.style.display = 'block';

  const isAdmin = currentUserRole === 'ADMIN';
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.display = isAdmin ? (el.classList.contains('tab-btn') ? 'inline-flex' : 'inline-flex') : 'none';
  });
  document.querySelectorAll('.gestor-only').forEach(el => {
    el.style.display = isAdmin ? 'none' : 'inline-flex';
  });

  document.getElementById('userName').textContent = email ? email.split('@')[0] : (isAdmin ? 'Admin' : 'Gestor');
  document.getElementById('userAvatar').textContent = isAdmin ? 'AD' : 'GS';
  document.getElementById('userRoleLabel').textContent = isAdmin ? 'Administrador Técnico (Debug)' : currentOrgName;
  document.getElementById('brandSubtitle').textContent = isAdmin
    ? 'Monitoramento Técnico & Orquestração Distribuída'
    : 'Plataforma de Adequação e Selo LGPD';
  document.getElementById('footerRightText').textContent = isAdmin
    ? 'Arquitetura de Microsserviços • Painel Administrativo'
    : 'Segurança da Informação para o Terceiro Setor';

  if (isAdmin) {
    checkEdgeHealth();
    switchTab('tab-admin-debug');
  } else {
    switchTab('tab-overview');
  }
}

document.getElementById('btnFillDemo')?.addEventListener('click', () => {
  document.getElementById('email').value = 'maria@associacaocuidar.org';
  document.getElementById('senha').value = 'senha-segura-123';
  showToast('Credenciais demo preenchidas!', 'info');
});

async function login(e) {
  if (e) e.preventDefault();
  const email = document.getElementById('email').value.trim();
  const senha = document.getElementById('senha').value;
  if (!email || !senha) {
    showToast('Informe seu e-mail e senha.', 'error');
    return;
  }
  const btn = document.getElementById('btnLogin');
  btn.disabled = true;
  try {
    const res = await fetch('/api/gestao/sessoes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, senha })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Credenciais inválidas');
    salvarSessao(data, email);
    aplicarVisibilidadePorPerfil(true, email);
    showToast(currentUserRole === 'ADMIN' ? 'Acesso técnico ADMIN liberado.' : 'Bem-vindo(a) ao painel da sua ONG!', 'success');
    await inicializarPainel();
  } catch (err) {
    showToast('Erro de login: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function cadastrarNovaOng(e) {
  if (e) e.preventDefault();
  const nome_instituicao = document.getElementById('regNome').value.trim();
  const cnpj = document.getElementById('regCnpj').value.replace(/\D/g, '');
  const responsavel_legal = document.getElementById('regResp').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const senha = document.getElementById('regSenha').value;

  if (!nome_instituicao || cnpj.length !== 14 || !responsavel_legal || !email || senha.length < 8) {
    showToast('Preencha todos os campos (CNPJ com 14 dígitos e senha de no mínimo 8 caracteres).', 'error');
    return;
  }
  const btn = document.getElementById('btnRegister');
  btn.disabled = true;
  try {
    const res = await fetch('/api/gestao/cadastro', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome_instituicao, cnpj, responsavel_legal, email, senha })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    salvarSessao(data, email);
    aplicarVisibilidadePorPerfil(true, email);
    showToast(`ONG "${nome_instituicao}" cadastrada com sucesso!`, 'success');
    await inicializarPainel();
  } catch (err) {
    showToast('Erro no cadastro: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function logout() {
  const tokenAtual = jwtToken;
  if (tokenAtual) {
    fetch('/api/gestao/sessoes/atual', {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${tokenAtual}` }
    }).catch(() => {});
  }
  jwtToken = '';
  currentUserRole = 'GESTOR';
  localStorage.removeItem('ongsec_jwt_token');
  localStorage.removeItem('ongsec_ong_id');
  localStorage.removeItem('ongsec_org_name');
  localStorage.removeItem('ongsec_user_role');
  localStorage.removeItem('ongsec_user_email');
  aplicarVisibilidadePorPerfil(false);
  showToast('Sessão encerrada com segurança.', 'info');
}

async function inicializarPainel() {
  await carregarDados();
  if (currentUserRole === 'ADMIN') {
    await Promise.all([inspecionarBancos(), atualizarMetricasIA()]);
  } else {
    await carregarQuestionarioWizard();
  }
}

async function carregarDados() {
  if (!jwtToken) {
    aplicarVisibilidadePorPerfil(false);
    return;
  }
  try {
    const res = await fetch(`/api/gestao/selos/${encodeURIComponent(currentOngId)}/detalhes`, {
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    if (res.status === 401) {
      await logout();
      return;
    }
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();

    currentDiagId = data.diagnostico_id || 'auto';
    currentPlanoId = data.plano_id || 'auto';

    if (data.instituicao) {
      currentOrgName = data.instituicao.nome_instituicao || currentOngId;
      localStorage.setItem('ongsec_org_name', currentOrgName);
      currentOngProfile = {
        descricao_atividades: data.instituicao.descricao_atividades || '',
        publico_atendido: Array.isArray(data.instituicao.publico_atendido) ? data.instituicao.publico_atendido : [],
        canais_coleta_dados: Array.isArray(data.instituicao.canais_coleta_dados) ? data.instituicao.canais_coleta_dados : [],
        perfil_completo: Boolean(data.instituicao.perfil_completo),
      };
    }

    // Preenche Visão Geral do Gestor
    const statusConf = (data.status_conformidade || 'PENDENTE').toUpperCase();
    const isAtivo = statusConf === 'ATIVO';
    const scoreVal = data.score_auditoria ?? 0;
    const pendentes = data.tarefas_pendentes ?? 0;

    const statusEl = document.getElementById('statusSelo');
    if (statusEl) {
      statusEl.textContent = statusConf;
      statusEl.className = isAtivo ? 'status-pill status-active' : 'status-pill status-revoked';
    }
    const idSeloEl = document.getElementById('idSelo');
    if (idSeloEl) idSeloEl.textContent = data.id_selo || 'Aguardando conclusão';
    const scoreEl = document.getElementById('scoreAuditoria');
    if (scoreEl) scoreEl.textContent = `${scoreVal}%`;
    const scoreBar = document.getElementById('scoreBar');
    if (scoreBar) scoreBar.style.width = `${Math.min(100, Math.max(0, scoreVal))}%`;
    const pendEl = document.getElementById('tarefasPendentes');
    if (pendEl) pendEl.textContent = pendentes;

    const orgNomeEl = document.getElementById('orgNome');
    if (orgNomeEl) orgNomeEl.textContent = currentOrgName;
    const respEl = document.getElementById('responsavelLegal');
    if (respEl) respEl.textContent = data.instituicao?.responsavel_legal || '—';
    const certOrgEl = document.getElementById('certOrg');
    if (certOrgEl) certOrgEl.textContent = currentOrgName;
    const greetEl = document.getElementById('overviewGreeting');
    if (greetEl) greetEl.textContent = currentOrgName;

    const linkPortal = document.getElementById('linkPortalPublico');
    const linkSeloPub = document.getElementById('btnVerSeloPublico');
    const pubUrl = `/publico/?ong=${encodeURIComponent(currentOngId)}`;
    if (linkPortal) linkPortal.href = pubUrl;
    if (linkSeloPub) linkSeloPub.href = pubUrl;

    // Orientação clara de próximo passo para o Gestor
    const proxEl = document.getElementById('proximoPassoTexto');
    const certStamp = document.getElementById('certStamp');
    const certBodyText = document.getElementById('certBodyText');
    const btnSolGestor = document.getElementById('btnSolicitarSeloGestor');
    const btnSolPlano = document.getElementById('btnSolicitarSeloPlano');

    const elegivel = scoreVal >= 80 && pendentes === 0 && Boolean(data.plano_id);

    if (isAtivo) {
      if (proxEl) proxEl.textContent = 'Tudo em ordem! Selo ativo e visível para doadores.';
      if (certStamp) certStamp.textContent = 'VERIFICADO';
      if (certBodyText) certBodyText.innerHTML = `A instituição <strong>${escapeHtml(currentOrgName)}</strong> concluiu a auditoria LGPD (${scoreVal}%) e possui Selo Digital <strong>ATIVO</strong> (${escapeHtml(data.id_selo || '')}) disponível para consulta pública de doadores.`;
      if (btnSolGestor) btnSolGestor.style.display = 'none';
      if (btnSolPlano) btnSolPlano.style.display = 'none';
      if (btnSeloPub(linkSeloPub)) linkSeloPub.style.display = 'inline-flex';
    } else if (elegivel) {
      if (proxEl) proxEl.textContent = 'Sem pendências! Você já pode emitir o selo.';
      if (certStamp) certStamp.textContent = 'PRONTO P/ SELO';
      if (certBodyText) certBodyText.innerHTML = `Parabéns! <strong>${escapeHtml(currentOrgName)}</strong> atingiu <strong>${scoreVal}%</strong> de conformidade e zerou o Plano de Ação. Clique abaixo para emitir seu Selo Digital.`;
      if (btnSolGestor) btnSolGestor.style.display = 'inline-flex';
      if (btnSolPlano) btnSolPlano.style.display = 'inline-flex';
      if (linkSeloPub) linkSeloPub.style.display = 'none';
    } else {
      if (proxEl) proxEl.textContent = pendentes > 0 ? `Conclua as ${pendentes} ação(ões) no Plano de Ação.` : 'Responda o Diagnóstico LGPD para avaliar sua ONG.';
      if (certStamp) certStamp.textContent = statusConf === 'REVOGADO' ? 'REVOGADO' : 'EM ADEQUAÇÃO';
      if (certBodyText) certBodyText.innerHTML = statusConf === 'REVOGADO'
        ? `O selo de <strong>${escapeHtml(currentOrgName)}</strong> foi <strong>REVOGADO</strong>. Refaça o Diagnóstico LGPD com ao menos <strong>80%</strong> e conclua todas as ações pendentes para reemitir o Selo Digital.`
        : `A instituição <strong>${escapeHtml(currentOrgName)}</strong> precisa atingir ao menos <strong>80%</strong> no Diagnóstico LGPD e concluir todas as ações pendentes para conquistar o Selo Digital.`;
      if (btnSolGestor) btnSolGestor.style.display = 'none';
      if (btnSolPlano) btnSolPlano.style.display = 'none';
      if (linkSeloPub) linkSeloPub.style.display = statusConf === 'REVOGADO' ? 'inline-flex' : 'none';
    }

    if (currentUserRole === 'ADMIN') {
      renderSagaEvents(data.historico_saga_emissao || []);
      renderHateoasLinks(data._links || {});
      const pubInput = document.getElementById('inputPublicOngId');
      if (pubInput) pubInput.value = currentOngId;
    }

    await carregarTarefas();
  } catch (err) {
    console.error(err);
    showToast('Erro ao carregar dados: ' + err.message, 'error');
  }
}

function btnSeloPub(el) { return Boolean(el); }

// ---------- PASSO 0 (PERFIL DA ONG) & WIZARD DE DIAGNÓSTICO (GESTOR) ----------
function atualizarViewsDiagnostico(estado) {
  const passo0 = document.getElementById('perfilPasso0Card');
  const loading = document.getElementById('wizardLoadingCard');
  const wizard = document.getElementById('wizardCard');
  const btnEditarPerfil = document.getElementById('btnAuditEditarPerfil');
  if (passo0) passo0.style.display = estado === 'passo0' ? 'block' : 'none';
  if (loading) loading.style.display = estado === 'loading' ? 'block' : 'none';
  if (wizard) wizard.style.display = estado === 'wizard' ? 'block' : 'none';
  if (btnEditarPerfil) btnEditarPerfil.style.display = estado === 'wizard' ? 'inline-flex' : 'none';
}

function preencherCheckboxesGrupo(name, valores) {
  const selecionados = new Set(valores || []);
  document.querySelectorAll(`input[name="${name}"]`).forEach(cb => {
    cb.checked = selecionados.has(cb.value);
  });
}

function coletarCheckboxesGrupo(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(cb => cb.value);
}

async function carregarPerfilOng() {
  if (!jwtToken || currentUserRole !== 'GESTOR') return;
  try {
    const res = await fetch(`/api/gestao/organizacoes/${encodeURIComponent(currentOngId)}/perfil`, {
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    if (res.ok) {
      const p = await res.json();
      currentOngProfile = {
        descricao_atividades: p.descricao_atividades || '',
        publico_atendido: Array.isArray(p.publico_atendido) ? p.publico_atendido : [],
        canais_coleta_dados: Array.isArray(p.canais_coleta_dados) ? p.canais_coleta_dados : [],
        perfil_completo: Boolean(p.perfil_completo),
      };
    }
  } catch (err) {
    console.warn('Erro ao consultar perfil da ONG:', err);
  }
}

async function salvarPerfilOngApi(descricao, publicos, canais) {
  const res = await fetch(`/api/gestao/organizacoes/${encodeURIComponent(currentOngId)}/perfil`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
    body: JSON.stringify({
      descricao_atividades: descricao,
      publico_atendido: publicos,
      canais_coleta_dados: canais,
    })
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  currentOngProfile = {
    descricao_atividades: data.descricao_atividades || descricao,
    publico_atendido: data.publico_atendido || publicos,
    canais_coleta_dados: data.canais_coleta_dados || canais,
    perfil_completo: Boolean(data.perfil_completo),
  };
  return data;
}

function abrirModalPerfil() {
  const modal = document.getElementById('perfilModalOverlay');
  if (!modal) return;
  document.getElementById('modalPerfilDescricao').value = currentOngProfile.descricao_atividades || '';
  preencherCheckboxesGrupo('modalPublico', currentOngProfile.publico_atendido);
  preencherCheckboxesGrupo('modalCanais', currentOngProfile.canais_coleta_dados);
  modal.style.display = 'flex';
}

function fecharModalPerfil() {
  const modal = document.getElementById('perfilModalOverlay');
  if (modal) modal.style.display = 'none';
}

async function carregarQuestionarioWizard(forcarRegeneracao = false) {
  if (!jwtToken) return;
  await carregarPerfilOng();

  if (!currentOngProfile.perfil_completo) {
    document.getElementById('passo0Descricao').value = currentOngProfile.descricao_atividades || '';
    preencherCheckboxesGrupo('passo0Publico', currentOngProfile.publico_atendido);
    preencherCheckboxesGrupo('passo0Canais', currentOngProfile.canais_coleta_dados);
    atualizarViewsDiagnostico('passo0');
    return;
  }

  atualizarViewsDiagnostico('loading');
  const titleEl = document.getElementById('wizardLoadingTitle');
  const subEl = document.getElementById('wizardLoadingSubtitle');
  if (titleEl) titleEl.textContent = 'Personalizando seu diagnóstico LGPD com base no perfil da ONG...';
  if (subEl) subEl.textContent = 'Isso leva apenas alguns instantes. Estamos preparando perguntas alinhadas ao público e aos canais da sua instituição.';

  try {
    const res = await fetch(`/api/gestao/${encodeURIComponent(currentOngId)}/diagnosticos/gerar-hibrido`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ forcar_regeneracao: forcarRegeneracao })
    });
    if (!res.ok) {
      const qRes = await fetch('/api/gestao/questionario', {
        headers: { 'Authorization': `Bearer ${jwtToken}` }
      });
      if (!qRes.ok) {
        atualizarViewsDiagnostico('passo0');
        return;
      }
      const qData = await qRes.json();
      wizardDiagId = null;
      wizardPerguntas = qData.perguntas || [];
    } else {
      const data = await res.json();
      wizardDiagId = data.diagnostico_id || null;
      wizardPerguntas = data.perguntas || [];
    }
    wizardIdx = 0;
    wizardRespostas = {};
    atualizarViewsDiagnostico('wizard');
    renderWizardStep();
  } catch (err) {
    console.warn('Erro ao carregar questionário híbrido:', err);
    atualizarViewsDiagnostico('passo0');
  }
}

function renderWizardStep() {
  if (!wizardPerguntas.length) return;
  const total = wizardPerguntas.length;
  const p = wizardPerguntas[wizardIdx];
  const pid = p.pergunta_id || p.id;
  const respAtual = wizardRespostas[pid] || null;

  document.getElementById('wizardStepLabel').textContent = `Pergunta ${wizardIdx + 1} de ${total}`;
  document.getElementById('wizardCategoryBadge').textContent = p.categoria || 'LGPD';
  document.getElementById('wizardProgressFill').style.width = `${Math.round(((wizardIdx + 1) / total) * 100)}%`;
  document.getElementById('wizardQuestionText').textContent = p.enunciado || p.pergunta || '';

  const justEl = document.getElementById('wizardJustification');
  if (justEl) {
    if (p.justificativa_curta) {
      justEl.textContent = p.justificativa_curta;
      justEl.style.display = 'block';
    } else {
      justEl.style.display = 'none';
    }
  }

  document.querySelectorAll('.wizard-option-btn').forEach(btn => {
    btn.classList.toggle('selected', btn.dataset.val === respAtual);
  });

  document.getElementById('btnWizardPrev').disabled = wizardIdx === 0;
  const isLast = wizardIdx === total - 1;
  document.getElementById('btnWizardNext').style.display = isLast ? 'none' : 'inline-flex';
  document.getElementById('btnEnviarDiagnostico').style.display = isLast ? 'inline-flex' : 'none';
}

document.querySelectorAll('.wizard-option-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!wizardPerguntas.length) return;
    const p = wizardPerguntas[wizardIdx];
    const pid = p.pergunta_id || p.id;
    wizardRespostas[pid] = btn.dataset.val;
    renderWizardStep();

    if (wizardIdx < wizardPerguntas.length - 1) {
      setTimeout(() => {
        wizardIdx++;
        renderWizardStep();
      }, 180);
    }
  });
});

document.getElementById('btnWizardPrev')?.addEventListener('click', () => {
  if (wizardIdx > 0) {
    wizardIdx--;
    renderWizardStep();
  }
});

document.getElementById('btnWizardNext')?.addEventListener('click', () => {
  const p = wizardPerguntas[wizardIdx];
  const pid = p.pergunta_id || p.id;
  if (!wizardRespostas[pid]) {
    showToast('Escolha uma opção para continuar.', 'info');
    return;
  }
  if (wizardIdx < wizardPerguntas.length - 1) {
    wizardIdx++;
    renderWizardStep();
  }
});

async function concluirDiagnosticoWizard() {
  if (!jwtToken || !wizardPerguntas.length) return;
  const faltando = wizardPerguntas.findIndex(p => !wizardRespostas[p.pergunta_id || p.id]);
  if (faltando !== -1) {
    wizardIdx = faltando;
    renderWizardStep();
    showToast(`Responda a pergunta ${faltando + 1} antes de concluir.`, 'error');
    return;
  }
  const respostas = wizardPerguntas.map(p => {
    const pid = p.pergunta_id || p.id;
    return { pergunta_id: pid, valor: wizardRespostas[pid] };
  });
  await enviarDiagnosticoPayload(respostas, true);
}

async function enviarDiagnosticoPayload(respostas, redirecionarPlano = true) {
  const btn = document.getElementById('btnEnviarDiagnostico');
  if (btn) btn.disabled = true;
  if (redirecionarPlano && currentUserRole === 'GESTOR') {
    const titleEl = document.getElementById('wizardLoadingTitle');
    const subEl = document.getElementById('wizardLoadingSubtitle');
    if (titleEl) titleEl.textContent = 'Montando seu Plano de Ação personalizado...';
    if (subEl) subEl.textContent = 'Estamos adaptando as ações prioritárias à realidade e aos canais da sua ONG.';
    atualizarViewsDiagnostico('loading');
  }
  try {
    const res = await fetch(`/api/gestao/${encodeURIComponent(currentOngId)}/diagnosticos/responder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ respostas, diagnostico_id: wizardDiagId })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    wizardDiagId = null;
    const score = data.diagnostico?.score ?? 0;
    const criadas = data.tarefas_criadas ?? 0;
    const revogadoAuto = Boolean(data.selo_revogado_automaticamente);
    const banner = document.getElementById('auditResultadoBanner');
    if (banner) {
      banner.style.display = 'block';
      const avisoRev = revogadoAuto
        ? `<br><span style="color:#f87171;"><strong>Atenção:</strong> Como a conformidade atual (${score}%) ficou abaixo de 80%, o selo anterior foi suspenso/revogado automaticamente até a conclusão das pendências.</span>`
        : '';
      banner.innerHTML = (criadas > 0
        ? `<strong>Diagnóstico concluído!</strong> Nível atual: <strong>${score}%</strong>. Geramos <strong>${criadas}</strong> ação(ões) prática(s) sob medida para a realidade da sua ONG.`
        : `<strong>Diagnóstico concluído com ${score}%!</strong> Nenhuma pendência encontrada — sua instituição já pode solicitar o Selo Digital!`) + avisoRev;
    }

    if (revogadoAuto) {
      showToast(`Diagnóstico concluído (${score}%). Selo anterior revogado por conformidade abaixo de 80%.`, 'error');
    } else {
      showToast(`Diagnóstico concluído (${score}%)!`, 'success');
    }
    await carregarDados();
    if (redirecionarPlano) {
      await carregarQuestionarioWizard(false);
      switchTab('tab-plan');
    }
  } catch (err) {
    if (redirecionarPlano && currentUserRole === 'GESTOR') atualizarViewsDiagnostico('wizard');
    showToast('Erro ao concluir diagnóstico: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------- TAREFAS & EMISSÃO DO SELO ----------
async function carregarTarefas() {
  if (!jwtToken) return;
  try {
    const res = await fetch(`/api/gestao/tarefas/${encodeURIComponent(currentOngId)}`, {
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    tarefasCache = data.tarefas || [];
    const pend = data.tarefas_pendentes ?? 0;

    // Atualiza lista limpa do GESTOR
    const gBadge = document.getElementById('gestorPlanoBadge');
    const gList = document.getElementById('gestorTarefasList');
    if (gBadge) gBadge.textContent = `${pend} pendente(s)`;
    if (gList) {
      if (!tarefasCache.length) {
        gList.innerHTML = '<span style="color:var(--text-dim); font-size:0.86rem;">Nenhuma ação pendente no momento.</span>';
      } else {
        gList.innerHTML = tarefasCache.map(t => `
          <div class="task-live-item">
            <div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:center;">
              <strong>${escapeHtml(t.titulo)}</strong>
              <span class="status-pill ${t.status === 'CONCLUIDA' ? 'status-active' : 'status-revoked'}" style="font-size:0.7rem; padding:0.15rem 0.5rem;">
                ${t.status === 'CONCLUIDA' ? 'CONCLUÍDA' : 'PENDENTE'}
              </span>
            </div>
            <div style="color:var(--text-dim); margin-top:0.35rem; font-size:0.78rem;">Prazo sugerido: ${escapeHtml(t.prazo)}</div>
            ${t.evidencia ? `<div class="task-evidence-box"><strong>Documento/Evidência anexada:</strong> ${escapeHtml(t.evidencia.slice(0, 240))}${t.evidencia.length > 240 ? '...' : ''}</div>` : ''}
            ${t.status !== 'CONCLUIDA' ? `
              <div class="task-actions-row">
                <button class="btn btn-outline btn-sm" style="padding:0.28rem 0.6rem; font-size:0.76rem;" onclick="abrirIaParaTarefa('${escapeHtml(t.tarefa_id)}', '${escapeHtml(t.titulo)}')">🤖 Gerar com IA</button>
                <button class="btn btn-primary btn-sm" style="padding:0.28rem 0.6rem; font-size:0.76rem;" onclick="concluirTarefaIndividual('${escapeHtml(t.tarefa_id)}')">✓ Marcar Concluída</button>
              </div>
            ` : ''}
          </div>
        `).join('');
      }
    }

    // Atualiza lista técnica do ADMIN
    const aBadge = document.getElementById('adminPlanoBadge');
    const aList = document.getElementById('adminTarefasBox');
    if (aBadge) aBadge.textContent = data.plano_id ? `${data.plano_id} • ${pend} pendente(s)` : 'Sem plano';
    if (aList) {
      aList.innerHTML = tarefasCache.map(t => `
        <div class="task-live-item">
          <div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:center;">
            <strong>${escapeHtml(t.titulo)}</strong>
            <span class="status-pill ${t.status === 'CONCLUIDA' ? 'status-active' : 'status-revoked'}" style="font-size:0.7rem; padding:0.15rem 0.5rem;">${escapeHtml(t.status)}</span>
          </div>
          <div style="color:var(--text-dim); margin-top:0.3rem; font-size:0.76rem;">ID: <code>${escapeHtml(t.tarefa_id)}</code> • Prazo: ${escapeHtml(t.prazo)}</div>
        </div>
      `).join('');
    }

    atualizarSeletorTarefasIA();
  } catch (err) {
    console.warn(err);
  }
}

function atualizarSeletorTarefasIA() {
  const sel = document.getElementById('aiTargetTaskSelect');
  const row = document.getElementById('aiVincularTarefaRow');
  if (!sel || !row) return;
  const pendentes = tarefasCache.filter(t => t.status !== 'CONCLUIDA');
  if (!pendentes.length) {
    row.style.display = 'none';
    return;
  }
  sel.innerHTML = pendentes.map(t => `<option value="${escapeHtml(t.tarefa_id)}">${escapeHtml(t.titulo)}</option>`).join('');
  if (ultimaRespostaIA) row.style.display = 'flex';
}

window.abrirIaParaTarefa = function (tarefaId, titulo) {
  const input = document.getElementById('gestorChatInput');
  if (input) input.value = `Me ajude a cumprir a ação do meu plano: "${titulo}". Gere um texto ou passo a passo prático para nossa ONG.`;
  const sel = document.getElementById('aiTargetTaskSelect');
  if (sel) sel.value = tarefaId;
  switchTab('tab-ai');
  input?.focus();
};

window.concluirTarefaIndividual = async function (tarefaId, evidencia = null) {
  if (!jwtToken) return;
  try {
    const res = await fetch(`/api/gestao/tarefas/${encodeURIComponent(tarefaId)}/concluir`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify(evidencia ? { evidencia } : {})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    showToast('Ação marcada como concluída!', 'success');
    await carregarDados();
  } catch (err) {
    showToast('Erro ao concluir ação: ' + err.message, 'error');
  }
};

async function solicitarSeloLimpo() {
  if (!jwtToken) return;
  try {
    const res = await fetch(`/api/gestao/selos/${encodeURIComponent(currentOngId)}/solicitar`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    showToast(`Selo Digital ${data.id_selo || ''} emitido com sucesso!`, 'success');
    await carregarDados();
    switchTab('tab-overview');
  } catch (err) {
    showToast('Não foi possível emitir o selo: ' + err.message, 'error');
  }
}

async function revogarSelo() {
  if (!jwtToken) return;
  if (!confirm(`Deseja realmente revogar o selo LGPD de ${currentOrgName}?`)) return;
  try {
    const res = await fetch(`/api/gestao/selos/${encodeURIComponent(currentOngId)}/revogar`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    showToast('Selo revogado com sucesso.', 'info');
    await carregarDados();
    if (currentUserRole === 'ADMIN') await consultarSeloPublicoAdmin();
  } catch (err) {
    showToast('Erro ao revogar: ' + err.message, 'error');
  }
}

async function editarNomeOng() {
  if (!jwtToken) return;
  const novoNome = prompt('Novo nome da organização:', currentOrgName);
  if (!novoNome || !novoNome.trim() || novoNome.trim() === currentOrgName) return;
  try {
    const res = await fetch(`/api/gestao/organizacoes/${encodeURIComponent(currentOngId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ nome_instituicao: novoNome.trim() })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast('Nome atualizado com sucesso!', 'success');
    await carregarDados();
  } catch (err) {
    showToast('Erro ao renomear: ' + err.message, 'error');
  }
}

// ---------- CHAT LIMPO DO GESTOR (IA) ----------
function appendChatMessage(author, text, isUser) {
  const hist = document.getElementById('gestorChatHistory');
  if (!hist) return;
  const div = document.createElement('div');
  div.className = `chat-msg ${isUser ? 'chat-user' : 'chat-bot'}`;
  div.innerHTML = `<strong>${escapeHtml(author)}</strong><div>${escapeHtml(text)}</div>`;
  hist.appendChild(div);
  hist.scrollTop = hist.scrollHeight;
}

async function enviarMensagemGestorChat(perguntaParam = null) {
  if (!jwtToken) return;
  const input = document.getElementById('gestorChatInput');
  const pergunta = (perguntaParam || input.value).trim();
  if (!pergunta) return;
  if (!perguntaParam) input.value = '';

  appendChatMessage('Você', pergunta, true);
  const btn = document.getElementById('btnGestorChatSend');
  btn.disabled = true;
  btn.textContent = 'Pensando...';
  try {
    const res = await fetch('/api/gestao/ia/consultoria', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({
        ong_id: currentOngId,
        pergunta,
        usar_rag: true,
        usar_cache: true,
        simular_falha_llm: false
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    ultimaRespostaIA = data.resposta || 'Sem resposta no momento.';
    appendChatMessage('Consultor LGPD', ultimaRespostaIA, false);
    atualizarSeletorTarefasIA();
  } catch (err) {
    appendChatMessage('Consultor LGPD', `Não foi possível obter resposta agora: ${err.message}`, false);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Enviar';
  }
}

// ---------- FUNÇÕES EXCLUSIVAS ADMIN ----------
async function executarSagaAdmin(simularFalha) {
  if (!jwtToken) return;
  try {
    const res = await fetch(`/api/gestao/saga/${encodeURIComponent(currentOngId)}/executar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ simular_falha: simularFalha, diagnostico_id: currentDiagId || 'auto', plano_id: currentPlanoId || 'auto' })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    showToast(data.estado === 'COMPENSADA' ? 'Falha simulada! Compensação executada.' : `SAGA concluída (${data.id_selo}).`, 'info');
    await carregarDados();
  } catch (err) {
    showToast('Erro SAGA: ' + err.message, 'error');
  }
}

async function concluirTodasAdmin() {
  if (!jwtToken) return;
  try {
    const res = await fetch(`/api/gestao/tarefas/${encodeURIComponent(currentOngId)}/concluir-todas`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast('Todas as tarefas concluídas!', 'success');
    await carregarDados();
  } catch (err) {
    showToast('Erro: ' + err.message, 'error');
  }
}

async function simularDiagAdmin(comPendencias) {
  if (!jwtToken) return;
  try {
    const qRes = await fetch('/api/gestao/questionario', { headers: { 'Authorization': `Bearer ${jwtToken}` } });
    const perguntas = (await qRes.json()).perguntas || [];
    const respostas = perguntas.map((p, idx) => ({
      pergunta_id: p.pergunta_id,
      valor: comPendencias && (idx === 1 || idx === 3) ? 'NAO' : 'SIM',
    }));
    await enviarDiagnosticoPayload(respostas, false);
  } catch (err) {
    showToast('Erro na simulação: ' + err.message, 'error');
  }
}

async function inspecionarBancos() {
  if (!jwtToken || currentUserRole !== 'ADMIN') return;
  const grid = document.getElementById('bancosEvidenciaGrid');
  if (!grid) return;
  try {
    const res = await fetch(`/api/gestao/evidencia-bancos?ong_id=${encodeURIComponent(currentOngId)}`, {
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    grid.innerHTML = (data.bancos || []).map(b => `
      <div class="db-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong>${escapeHtml(b.banco)}</strong>
          <span class="status-pill ${b.status === 200 ? 'status-active' : 'status-revoked'}" style="font-size:0.7rem; padding:0.1rem 0.45rem;">HTTP ${b.status}</span>
        </div>
        <div style="color:var(--text-dim); font-size:0.76rem; margin-top:0.2rem;">Serviço: <code>${escapeHtml(b.servico)}</code> • Rede: <code>${escapeHtml(b.rede_isolada)}</code></div>
        <pre>${escapeHtml(JSON.stringify(b.dados || b.erro, null, 2))}</pre>
      </div>
    `).join('');
  } catch (err) {
    console.warn(err);
  }
}

function renderSagaEvents(events) {
  const tableBody = document.getElementById('sagaTableBody');
  const countBadge = document.getElementById('sagaEventsCount');
  if (countBadge) countBadge.textContent = `${events.length} evento(s)`;
  if (!tableBody) return;
  tableBody.innerHTML = events.length
    ? events.map((ev, idx) => `
        <tr>
          <td><span class="code-id">#0${idx + 1}</span></td>
          <td><strong>${escapeHtml(ev.servico)}</strong></td>
          <td><code>${escapeHtml(ev.evento)}</code></td>
          <td><span class="status-pill ${ev.sucesso ? 'status-active' : 'status-revoked'}" style="font-size:0.72rem; padding:0.15rem 0.5rem;">${ev.sucesso ? 'CONCLUÍDO' : 'FALHA'}</span></td>
          <td><span style="color:${ev.sucesso ? 'var(--text-dim)' : 'var(--danger)'}; font-size:0.75rem;">${ev.sucesso ? 'Não' : 'Sim (Compensação)'}</span></td>
        </tr>
      `).join('')
    : '<tr><td colspan="5" style="text-align:center; color:var(--text-dim);">Sem eventos registrados.</td></tr>';
}

function renderHateoasLinks(links) {
  const container = document.getElementById('hateoasList');
  if (!container) return;
  const entries = Object.entries(links);
  container.innerHTML = entries.map(([rel, item]) => `
    <div class="hateoas-item">
      <div class="hateoas-rel">
        <span class="hateoas-rel-name">rel: "${escapeHtml(rel)}"</span>
        <span class="hateoas-href">${escapeHtml(item.href || item)}</span>
      </div>
      <span class="hateoas-method method-${escapeHtml((item.method || 'GET').toLowerCase())}">${escapeHtml((item.method || 'GET').toUpperCase())}</span>
    </div>
  `).join('');
}

function atualizarBarraIa(data) {
  const cb = data.circuit_breaker || {};
  const cbEl = document.getElementById('aiCbEstado');
  const modoEl = document.getElementById('aiModoTag');
  const latEl = document.getElementById('aiLatenciaTag');
  const badgeEl = document.getElementById('aiModoBadge');
  if (cbEl && cb.estado) cbEl.textContent = `${cb.estado} (${cb.falhas_consecutivas || 0}/${cb.limiar_abertura || 2})`;
  if (modoEl && data.modo_operacao) modoEl.textContent = data.modo_operacao;
  if (latEl && data.latencia_ms !== undefined) latEl.textContent = `${data.latencia_ms} ms`;
  if (badgeEl && data.modo_operacao) badgeEl.textContent = data.modo_operacao;
}

async function consultarIAAdmin(simularFalha = false) {
  if (!jwtToken) return;
  const pergunta = document.getElementById('aiPerguntaInput').value.trim();
  const usarRag = document.getElementById('aiUsarRag').checked;
  const usarCache = document.getElementById('aiUsarCache').checked;
  const btn = document.getElementById('btnIaConsultar');
  if (!pergunta) return;
  btn.disabled = true;
  try {
    const res = await fetch('/api/gestao/ia/consultoria', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ ong_id: currentOngId, pergunta, usar_rag: usarRag, usar_cache: usarCache, simular_falha_llm: simularFalha })
    });
    const data = await res.json();
    document.getElementById('aiRespostaContainer').style.display = 'grid';
    document.getElementById('aiRespostaTexto').textContent = data.resposta || JSON.stringify(data);
    atualizarBarraIa(data);
    const chunks = data.rag_fontes || [];
    document.getElementById('aiChunksCount').textContent = `${chunks.length} chunk(s)`;
    const tools = data.dados_tools || {};
    document.getElementById('aiToolsResumo').innerHTML = `<strong>Tools:</strong> <code>${escapeHtml((tools.tools_executadas || []).join(', '))}</code><pre style="margin-top:0.35rem; white-space:pre-wrap; font-size:0.74rem;">${escapeHtml(JSON.stringify(tools, null, 2))}</pre>`;
    document.getElementById('aiRagResumo').innerHTML = chunks.map(c => `<div style="margin-top:0.35rem;"><code>${escapeHtml(c.documento)}</code> (sim: ${c.score_similaridade})</div>`).join('') || 'Sem RAG';
    await atualizarMetricasIA();
  } finally {
    btn.disabled = false;
  }
}

async function compararRagIAAdmin() {
  if (!jwtToken) return;
  const pergunta = document.getElementById('aiPerguntaInput').value.trim();
  if (!pergunta) return;
  const btn = document.getElementById('btnIaComparar');
  btn.disabled = true;
  try {
    const res = await fetch('/api/gestao/ia/comparar-rag', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
      body: JSON.stringify({ ong_id: currentOngId, pergunta })
    });
    const data = await res.json();
    document.getElementById('aiComparacaoContainer').style.display = 'block';
    document.getElementById('aiCompComRag').textContent = `[${data.com_rag?.modo_operacao} • ${data.com_rag?.latencia_ms} ms]\n\n${data.com_rag?.resposta || ''}`;
    document.getElementById('aiCompSemRag').textContent = `[${data.sem_rag?.modo_operacao} • ${data.sem_rag?.latencia_ms} ms]\n\n${data.sem_rag?.resposta || ''}`;
    await atualizarMetricasIA();
  } finally {
    btn.disabled = false;
  }
}

async function controlarCbIA(acao) {
  if (!jwtToken) return;
  const res = await fetch('/api/gestao/ia/circuit-breaker', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${jwtToken}` },
    body: JSON.stringify({ acao })
  });
  const data = await res.json();
  atualizarBarraIa(data);
  await atualizarMetricasIA();
}

async function atualizarMetricasIA() {
  if (!jwtToken || currentUserRole !== 'ADMIN') return;
  try {
    const res = await fetch('/api/gestao/ia/metricas', { headers: { 'Authorization': `Bearer ${jwtToken}` } });
    if (!res.ok) return;
    const m = await res.json();
    atualizarBarraIa(m);
    document.getElementById('aiCacheTag').textContent = `${m.cache?.hits || 0} (${m.cache?.taxa_acerto_pct || 0}%)`;
    const l = m.latencia_medida || {};
    const c = m.estimativa_custo_escala || {};
    document.getElementById('aiMetricasBox').innerHTML = `
      <div class="db-card"><strong>Requisições & Retries</strong><br>Total: ${m.total_requisicoes} • Retries: ${m.retries_executados} • Fallbacks: ${m.fallbacks_acionados}</div>
      <div class="db-card"><strong>Latência Ollama (ms)</strong><br>Média: ${l.llm_ollama?.media_ms || 0} ms • Min/Max: ${l.llm_ollama?.min_ms || 0}/${l.llm_ollama?.max_ms || 0} ms</div>
      <div class="db-card"><strong>Latência Cache & Fallback</strong><br>Cache: ${l.cache_hit?.media_ms || 0} ms • Fallback: ${l.fallback?.media_ms || 0} ms</div>
      <div class="db-card"><strong>Custo em Escala (1.000)</strong><br>Ollama Local: US$ 0,00 • Cloud ref.: US$ ${c.custo_cloud_1000_consultas_usd || 0}</div>
    `;
  } catch (err) {
    console.warn(err);
  }
}

async function consultarSeloPublicoAdmin() {
  const ongId = document.getElementById('inputPublicOngId').value.trim() || currentOngId;
  const res = await fetch(`/api/publico/selos/${encodeURIComponent(ongId)}`);
  if (!res.ok) { showToast(`HTTP ${res.status}`, 'error'); return; }
  const data = await res.json();
  document.getElementById('pubNomeInstituicao').textContent = data.nome_instituicao || ongId;
  document.getElementById('pubStatus').textContent = `STATUS: ${data.status_conformidade}`;
  document.getElementById('pubMensagem').textContent = data.mensagem || '';
  document.getElementById('pubIdSelo').textContent = data.id_selo || '—';
  document.getElementById('pubEmitidoEm').textContent = data.emitido_em ? new Date(data.emitido_em).toLocaleDateString('pt-BR') : '—';
  document.getElementById('pubRawJson').textContent = JSON.stringify(data, null, 2);
  document.getElementById('publicResultSection').style.display = 'block';
}

async function checkEdgeHealth() {
  const indicator = document.getElementById('edgeStatus');
  if (!indicator) return;
  try {
    const res = await fetch('/healthz');
    indicator.innerHTML = res.ok
      ? '<span class="pulse-dot"></span><span class="status-text">Gateway : Conectado</span>'
      : '<span class="status-text" style="color:var(--warning);">Gateway : Alerta</span>';
  } catch {
    indicator.innerHTML = '<span class="status-text" style="color:var(--danger);">Gateway : Inacessível</span>';
  }
}

// Listeners gerais
document.getElementById('btnLogin')?.addEventListener('click', login);
document.getElementById('btnRegister')?.addEventListener('click', cadastrarNovaOng);
document.getElementById('btnLogout')?.addEventListener('click', logout);

// Listeners Gestor
document.getElementById('btnGoDiagnostico')?.addEventListener('click', () => switchTab('tab-audit'));
document.getElementById('btnGoPlano')?.addEventListener('click', () => switchTab('tab-plan'));
document.getElementById('btnEditarPerfilOng')?.addEventListener('click', abrirModalPerfil);
document.getElementById('btnAuditEditarPerfil')?.addEventListener('click', abrirModalPerfil);
document.getElementById('btnFecharModalPerfil')?.addEventListener('click', fecharModalPerfil);
document.getElementById('btnCancelarModalPerfil')?.addEventListener('click', fecharModalPerfil);
document.getElementById('btnSalvarPasso0')?.addEventListener('click', async () => {
  const desc = document.getElementById('passo0Descricao').value.trim();
  const publicos = coletarCheckboxesGrupo('passo0Publico');
  const canais = coletarCheckboxesGrupo('passo0Canais');
  if (desc.length < 5) {
    showToast('Descreva brevemente as atividades da sua ONG para personalizar o diagnóstico.', 'error');
    return;
  }
  const btn = document.getElementById('btnSalvarPasso0');
  if (btn) btn.disabled = true;
  try {
    await salvarPerfilOngApi(desc, publicos, canais);
    showToast('Perfil salvo! Preparando diagnóstico sob medida...', 'success');
    await carregarQuestionarioWizard(true);
  } catch (err) {
    showToast('Erro ao salvar perfil: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
});
document.getElementById('btnSalvarModalPerfil')?.addEventListener('click', async () => {
  const desc = document.getElementById('modalPerfilDescricao').value.trim();
  const publicos = coletarCheckboxesGrupo('modalPublico');
  const canais = coletarCheckboxesGrupo('modalCanais');
  if (desc.length < 5) {
    showToast('Informe uma descrição válida das atividades da ONG.', 'error');
    return;
  }
  const btn = document.getElementById('btnSalvarModalPerfil');
  if (btn) btn.disabled = true;
  try {
    await salvarPerfilOngApi(desc, publicos, canais);
    fecharModalPerfil();
    showToast('Perfil da ONG atualizado! Atualizando diagnóstico...', 'success');
    await carregarQuestionarioWizard(true);
  } catch (err) {
    showToast('Erro ao atualizar perfil: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
});
document.getElementById('btnEditarNomeOng')?.addEventListener('click', editarNomeOng);
document.getElementById('btnSolicitarSeloGestor')?.addEventListener('click', solicitarSeloLimpo);
document.getElementById('btnSolicitarSeloPlano')?.addEventListener('click', solicitarSeloLimpo);
document.getElementById('btnEnviarDiagnostico')?.addEventListener('click', concluirDiagnosticoWizard);
document.getElementById('btnGestorChatSend')?.addEventListener('click', () => enviarMensagemGestorChat());
document.querySelectorAll('.gestor-chat-sug').forEach(btn => {
  btn.addEventListener('click', () => enviarMensagemGestorChat(btn.dataset.q));
});
document.getElementById('btnIaExportarPdf')?.addEventListener('click', () => window.print());
document.getElementById('btnIaSalvarEvidencia')?.addEventListener('click', async () => {
  const tarefaId = document.getElementById('aiTargetTaskSelect')?.value;
  if (!tarefaId || !ultimaRespostaIA) return;
  await window.concluirTarefaIndividual(tarefaId, ultimaRespostaIA);
});

// Listeners Admin
document.getElementById('btnAtualizarAdmin')?.addEventListener('click', carregarDados);
document.getElementById('btnEvidenciaBancos')?.addEventListener('click', inspecionarBancos);
document.getElementById('btnSagaSucesso')?.addEventListener('click', () => executarSagaAdmin(false));
document.getElementById('btnSagaFalha')?.addEventListener('click', () => executarSagaAdmin(true));
document.getElementById('btnAdminRevogarSelo')?.addEventListener('click', revogarSelo);
document.getElementById('btnConcluirTarefas')?.addEventListener('click', concluirTodasAdmin);
document.getElementById('btnAdminSim100')?.addEventListener('click', () => simularDiagAdmin(false));
document.getElementById('btnAdminSim80')?.addEventListener('click', () => simularDiagAdmin(true));
document.getElementById('aiPresetSelect')?.addEventListener('change', (e) => {
  document.getElementById('aiPerguntaInput').value = e.target.value;
});
document.getElementById('btnIaConsultar')?.addEventListener('click', () => consultarIAAdmin(false));
document.getElementById('btnIaComparar')?.addEventListener('click', compararRagIAAdmin);
document.getElementById('btnIaSimularFalha')?.addEventListener('click', () => consultarIAAdmin(true));
document.getElementById('btnIaResetCb')?.addEventListener('click', () => controlarCbIA('fechar'));
document.getElementById('btnIaMetricas')?.addEventListener('click', atualizarMetricasIA);
document.getElementById('btnConsultarPublico')?.addEventListener('click', consultarSeloPublicoAdmin);

// Initialize
const savedEmail = localStorage.getItem('ongsec_user_email');
if (jwtToken) {
  currentUserRole = localStorage.getItem('ongsec_user_role') || decodeJwtRole(jwtToken);
  aplicarVisibilidadePorPerfil(true, savedEmail);
  inicializarPainel();
} else {
  aplicarVisibilidadePorPerfil(false);
}
