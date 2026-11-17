/**
 * ONGSec — Frontend Controller (Vanilla ES6+)
 * Plataforma de Governança e Certificação LGPD
 */

let jwtToken = localStorage.getItem('ongsec_jwt_token') || '';
let currentUser = null;

// DOM Elements
const authSection = document.getElementById('authSection');
const userProfile = document.getElementById('userProfile');
const btnLogin = document.getElementById('btnLogin');
const btnLogout = document.getElementById('btnLogout');
const btnFillDemo = document.getElementById('btnFillDemo');
const btnAtualizar = document.getElementById('btnAtualizar');
const btnRevogar = document.getElementById('btnRevogar');
const btnConsultarPublico = document.getElementById('btnConsultarPublico');
const toastContainer = document.getElementById('toast');

// Tabs Switcher
const tabButtons = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

tabButtons.forEach(btn => {
  btn.addEventListener('click', () => {
    const targetTabId = btn.getAttribute('data-tab');
    
    tabButtons.forEach(b => b.classList.remove('active'));
    tabPanes.forEach(p => p.classList.remove('active'));

    btn.classList.add('active');
    const targetPane = document.getElementById(targetTabId);
    if (targetPane) {
      targetPane.classList.add('active');
    }
  });
});

// Toast System
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let iconSvg = '';
  if (type === 'success') {
    iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
  } else if (type === 'error') {
    iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
  } else {
    iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#3b82f6" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
  }

  toast.innerHTML = `${iconSvg} <span>${message}</span>`;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(30px)';
    toast.style.transition = 'all 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Quick Demo Fill
if (btnFillDemo) {
  btnFillDemo.addEventListener('click', () => {
    document.getElementById('email').value = 'maria@associacaocuidar.org';
    document.getElementById('senha').value = 'senha-segura-123';
    showToast('Credenciais de teste preenchidas!', 'info');
  });
}

// Authentication
async function login(e) {
  if (e) e.preventDefault();
  const email = document.getElementById('email').value.trim();
  const senha = document.getElementById('senha').value;

  if (!email || !senha) {
    showToast('Informe o e-mail e a senha corporativa.', 'error');
    return;
  }

  const btnText = btnLogin.querySelector('.btn-text');
  if (btnText) btnText.textContent = 'Autenticando...';
  btnLogin.disabled = true;

  try {
    const res = await fetch('/api/gestao/sessoes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, senha })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Falha ao autenticar credenciais');
    }

    const data = await res.json();
    jwtToken = data.token;
    localStorage.setItem('ongsec_jwt_token', jwtToken);
    localStorage.setItem('ongsec_user_email', email);

    showToast('Autenticação realizada com sucesso!', 'success');
    updateAuthUI(true, email);
    await carregarDados();
  } catch (err) {
    showToast('Erro de login: ' + err.message, 'error');
  } finally {
    if (btnText) btnText.textContent = 'Autenticar no BFF Gestão';
    btnLogin.disabled = false;
  }
}

function logout() {
  jwtToken = '';
  localStorage.removeItem('ongsec_jwt_token');
  localStorage.removeItem('ongsec_user_email');
  updateAuthUI(false);
  showToast('Sessão encerrada com sucesso.', 'info');
}

function updateAuthUI(isLoggedIn, email = '') {
  if (isLoggedIn) {
    authSection.classList.add('hidden');
    userProfile.style.display = 'flex';
    document.getElementById('userName').textContent = email ? email.split('@')[0] : 'Gestor LGPD';
  } else {
    authSection.classList.remove('hidden');
    userProfile.style.display = 'none';
  }
}

// Carregar Dados da ONG e do Selo
async function carregarDados() {
  if (!jwtToken) {
    updateAuthUI(false);
    return;
  }

  try {
    const res = await fetch('/api/gestao/selos/ong-123/detalhes', {
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });

    if (res.status === 401) {
      showToast('Sessão expirada. Faça login novamente.', 'error');
      logout();
      return;
    }

    if (!res.ok) {
      throw new Error(`BFF retornou status ${res.status}`);
    }

    const data = await res.json();

    // Atualiza KPIs
    const statusEl = document.getElementById('statusSelo');
    const isAtivo = (data.status_conformidade || '').toUpperCase() === 'ATIVO';
    statusEl.textContent = data.status_conformidade || 'INATIVO';
    statusEl.className = isAtivo ? 'status-pill status-active' : 'status-pill status-revoked';

    document.getElementById('idSelo').textContent = data.id_selo || 'PENDENTE';
    
    const scoreVal = data.score_auditoria ?? 0;
    document.getElementById('scoreAuditoria').textContent = `${scoreVal}%`;
    const scoreBar = document.getElementById('scoreBar');
    if (scoreBar) scoreBar.style.width = `${Math.min(100, Math.max(0, scoreVal))}%`;

    document.getElementById('tarefasPendentes').textContent = data.tarefas_pendentes ?? 0;

    if (data.instituicao) {
      document.getElementById('responsavelLegal').textContent = data.instituicao.responsavel_legal || 'Não informado';
      document.getElementById('ongId').textContent = data.instituicao.ong_id || 'ong-123';
    }

    // Render SAGA Events
    renderSagaEvents(data.historico_saga_emissao || []);

    // Render HATEOAS Links
    renderHateoasLinks(data._links || {});

    showToast('Dados atualizados via BFF Gestão.', 'success');
  } catch (err) {
    console.error('Falha ao carregar dados:', err);
    showToast('Erro ao buscar dados: ' + err.message, 'error');
  }
}

// Render SAGA Table
function renderSagaEvents(events) {
  const tableBody = document.getElementById('sagaTableBody');
  const countBadge = document.getElementById('sagaEventsCount');
  
  if (countBadge) {
    countBadge.textContent = `${events.length} evento(s)`;
  }

  if (!tableBody) return;
  tableBody.innerHTML = '';

  if (events.length === 0) {
    tableBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-dim);">Nenhum evento registrado.</td></tr>';
    return;
  }

  events.forEach((ev, idx) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="code-id">#0${idx + 1}</span></td>
      <td><strong>${escapeHtml(ev.servico)}</strong></td>
      <td><code>${escapeHtml(ev.evento)}</code></td>
      <td>
        <span class="status-pill ${ev.sucesso ? 'status-active' : 'status-revoked'}" style="font-size: 0.72rem; padding: 0.15rem 0.5rem;">
          ${ev.sucesso ? 'CONCLUÍDO' : 'FALHA'}
        </span>
      </td>
      <td><span style="color: ${ev.sucesso ? 'var(--text-dim)' : 'var(--danger)'}; font-size: 0.75rem;">${ev.sucesso ? 'Não (Fluxo Nominal)' : 'Sim (Rollback acionado)'}</span></td>
    `;
    tableBody.appendChild(tr);
  });
}

// Render HATEOAS
function renderHateoasLinks(links) {
  const container = document.getElementById('hateoasList');
  if (!container) return;
  container.innerHTML = '';

  const entries = Object.entries(links);
  if (entries.length === 0) {
    container.innerHTML = '<span style="color: var(--text-dim); font-size: 0.8rem;">Nenhum link hipermidiático disponível.</span>';
    return;
  }

  entries.forEach(([rel, item]) => {
    const href = typeof item === 'string' ? item : item.href;
    const method = (item.method || 'GET').toUpperCase();

    const div = document.createElement('div');
    div.className = 'hateoas-item';
    div.innerHTML = `
      <div class="hateoas-rel">
        <span class="hateoas-rel-name">rel: "${escapeHtml(rel)}"</span>
        <span class="hateoas-href">${escapeHtml(href)}</span>
      </div>
      <span class="hateoas-method method-${method.toLowerCase()}">${escapeHtml(method)}</span>
    `;
    container.appendChild(div);
  });
}

// Revogar Selo
async function revogarSelo() {
  if (!jwtToken) {
    showToast('Você precisa estar autenticado para revogar.', 'error');
    return;
  }

  const confirmado = confirm('Deseja realmente acionar a revogação do selo LGPD para a organização ong-123?');
  if (!confirmado) return;

  try {
    const res = await fetch('/api/gestao/selos/ong-123/revogar', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${jwtToken}` }
    });

    if (res.ok) {
      showToast('Selo revogado com sucesso no badge-service!', 'success');
      await carregarDados();
    } else {
      showToast(`Falha ao revogar selo (HTTP ${res.status})`, 'error');
    }
  } catch (err) {
    showToast('Erro de comunicação: ' + err.message, 'error');
  }
}

// Consulta Pública Anônima
async function consultarSeloPublico() {
  const ongId = document.getElementById('inputPublicOngId').value.trim() || 'ong-123';
  const resultSection = document.getElementById('publicResultSection');
  const btn = document.getElementById('btnConsultarPublico');

  btn.disabled = true;

  try {
    const res = await fetch(`/api/publico/selos/${encodeURIComponent(ongId)}`);
    if (!res.ok) {
      throw new Error(`BFF Público retornou HTTP ${res.status}`);
    }

    const data = await res.json();

    document.getElementById('pubNomeInstituicao').textContent = data.nome_instituicao || ongId;
    document.getElementById('pubStatus').textContent = `STATUS: ${data.status_conformidade || 'N/A'}`;
    document.getElementById('pubMensagem').textContent = data.mensagem || 'Sem observações adicionais.';
    document.getElementById('pubIdSelo').textContent = data.id_selo || 'N/A';
    document.getElementById('pubEmitidoEm').textContent = data.emitido_em ? new Date(data.emitido_em).toLocaleDateString('pt-BR') : '10/10/2026';

    document.getElementById('pubRawJson').textContent = JSON.stringify(data, null, 2);
    resultSection.style.display = 'block';

    showToast(`Consulta pública realizada para ${ongId}!`, 'success');
  } catch (err) {
    showToast('Erro na consulta pública: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

// Edge Gateway Health Check
async function checkEdgeHealth() {
  const indicator = document.getElementById('edgeStatus');
  try {
    const res = await fetch('/healthz');
    if (res.ok) {
      indicator.innerHTML = '<span class="pulse-dot"></span><span class="status-text">Gateway : Conectado (Porta 8080)</span>';
    } else {
      indicator.innerHTML = '<span class="status-text" style="color: var(--warning);">Gateway : Alerta</span>';
    }
  } catch (err) {
    indicator.innerHTML = '<span class="status-text" style="color: var(--danger);">Gateway : Inacessível</span>';
  }
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

// Listeners
btnLogin.addEventListener('click', login);
btnLogout.addEventListener('click', logout);
btnAtualizar.addEventListener('click', carregarDados);
btnRevogar.addEventListener('click', revogarSelo);
btnConsultarPublico.addEventListener('click', consultarSeloPublico);

// Initialize
checkEdgeHealth();

const savedEmail = localStorage.getItem('ongsec_user_email');
if (jwtToken) {
  updateAuthUI(true, savedEmail);
  carregarDados();
} else {
  updateAuthUI(false);
}
