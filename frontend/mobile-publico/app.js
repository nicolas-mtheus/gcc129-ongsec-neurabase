/**
 * ONGSec Portal Mobile Público — Consulta Anônima via BFF Público + CQRS
 */

const navButtons = document.querySelectorAll('.nav-btn');
const views = document.querySelectorAll('.view');
const searchInput = document.getElementById('searchInput');
const btnSearch = document.getElementById('btnSearch');
const ongsList = document.getElementById('ongsList');
const totalCount = document.getElementById('totalCount');
const directOngId = document.getElementById('directOngId');
const btnDirectVerify = document.getElementById('btnDirectVerify');
const sealDetailCard = document.getElementById('sealDetailCard');

function showView(viewId) {
  navButtons.forEach(b => b.classList.toggle('active', b.dataset.view === viewId));
  views.forEach(v => v.classList.toggle('active', v.id === viewId));
}

navButtons.forEach(btn => {
  btn.addEventListener('click', () => showView(btn.dataset.view));
});

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2800);
}

function escapeHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatCnpj(cnpj) {
  if (!cnpj || cnpj.length !== 14) return cnpj || 'Não informado';
  return cnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
}

// Matriz visual de verificação (21x21 estilo QR determinístico para o código do selo/URL)
function renderVerificationMatrixSvg(seedText) {
  const size = 21;
  let hash = 2166136261;
  for (let i = 0; i < seedText.length; i++) {
    hash ^= seedText.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const finder = (r, c) => {
    const inBox = (r0, c0) => {
      const dr = r - r0, dc = c - c0;
      if (dr < 0 || dr > 6 || dc < 0 || dc > 6) return null;
      return dr === 0 || dr === 6 || dc === 0 || dc === 6 || (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4);
    };
    return inBox(0, 0) ?? inBox(0, size - 7) ?? inBox(size - 7, 0);
  };

  let rects = '';
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      let on = finder(r, c);
      if (on === null) {
        hash ^= (r * 31 + c * 17);
        hash = Math.imul(hash, 16777619);
        on = ((hash >>> 0) % 2) === 0;
      }
      if (on) {
        rects += `<rect x="${c * 6}" y="${r * 6}" width="6" height="6" fill="#0f172a"/>`;
      }
    }
  }
  return `<svg viewBox="0 0 ${size * 6} ${size * 6}" width="132" height="132" aria-label="Código visual do certificado">${rects}</svg>`;
}

async function carregarListaOngs(query = '') {
  ongsList.innerHTML = '<div class="empty-state">Consultando projeção pública CQRS...</div>';
  try {
    const qs = query ? `?q=${encodeURIComponent(query)}` : '';
    const res = await fetch(`/api/publico/selos${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const itens = data.itens || [];
    totalCount.textContent = `${itens.length}`;
    if (!itens.length) {
      ongsList.innerHTML = '<div class="empty-state">Nenhuma ONG certificada encontrada para esta busca.</div>';
      return;
    }
    ongsList.innerHTML = itens.map(item => {
      const ativo = (item.status_conformidade || '').toUpperCase() === 'ATIVO';
      return `
        <article class="ong-card" data-ong="${escapeHtml(item.ong_id)}">
          <div class="ong-card-top">
            <div>
              <h4>${escapeHtml(item.nome_instituicao)}</h4>
              <div class="ong-card-meta">
                Selo: <code>${escapeHtml(item.id_selo)}</code> • CNPJ: ${escapeHtml(formatCnpj(item.cnpj))}
              </div>
            </div>
            <span class="status-badge ${ativo ? 'status-ativo' : 'status-revogado'}">
              ${escapeHtml(item.status_conformidade)}
            </span>
          </div>
        </article>
      `;
    }).join('');
    ongsList.querySelectorAll('.ong-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = card.dataset.ong;
        directOngId.value = id;
        verificarSelo(id);
        showView('view-verify');
      });
    });
  } catch (err) {
    ongsList.innerHTML = `<div class="empty-state">Erro ao consultar BFF Público: ${escapeHtml(err.message)}</div>`;
  }
}

async function verificarSelo(ongId) {
  const id = (ongId || '').trim();
  if (!id) return;
  sealDetailCard.innerHTML = '<div class="empty-state">Consultando selo...</div>';
  try {
    const res = await fetch(`/api/publico/selos/${encodeURIComponent(id)}`);
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || `HTTP ${res.status}`);
    }
    const d = await res.json();
    const ativo = (d.status_conformidade || '').toUpperCase() === 'ATIVO';
    const verifyUrl = `${window.location.origin}/publico/?ong=${encodeURIComponent(d.ong_id)}`;
    sealDetailCard.innerHTML = `
      <div class="seal-banner ${ativo ? 'ativo' : 'revogado'}">
        <div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem;">
          <h3>${escapeHtml(d.nome_instituicao)}</h3>
          <span class="status-badge ${ativo ? 'status-ativo' : 'status-revogado'}">${escapeHtml(d.status_conformidade)}</span>
        </div>
        <p style="margin-top:0.5rem; font-size:0.86rem; color:var(--text);">${escapeHtml(d.mensagem)}</p>
      </div>
      <div class="seal-meta-grid">
        <div class="seal-meta-item"><span>Certificado</span><strong>${escapeHtml(d.id_selo)}</strong></div>
        <div class="seal-meta-item"><span>Identificador ONG</span><strong>${escapeHtml(d.ong_id)}</strong></div>
        <div class="seal-meta-item"><span>CNPJ</span><strong>${escapeHtml(formatCnpj(d.cnpj))}</strong></div>
        <div class="seal-meta-item"><span>Emitido em</span><strong>${d.emitido_em ? new Date(d.emitido_em).toLocaleDateString('pt-BR') : '—'}</strong></div>
      </div>
      <div class="qr-box">
        ${renderVerificationMatrixSvg(`${d.id_selo}|${verifyUrl}`)}
        <small>${escapeHtml(verifyUrl)}</small>
      </div>
      <button type="button" id="btnCopyVerifyLink" class="btn-copy" style="width:100%;">🔗 Copiar Link de Verificação</button>
    `;
    document.getElementById('btnCopyVerifyLink')?.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(verifyUrl);
        showToast('Link de verificação copiado!');
      } catch {
        showToast(verifyUrl);
      }
    });
  } catch (err) {
    sealDetailCard.innerHTML = `<div class="empty-state">Não encontrado: ${escapeHtml(err.message)}</div>`;
  }
}

btnSearch.addEventListener('click', () => carregarListaOngs(searchInput.value));
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') carregarListaOngs(searchInput.value); });
btnDirectVerify.addEventListener('click', () => verificarSelo(directOngId.value));

// Inicialização e deep-link (?ong=ong-123)
const params = new URLSearchParams(window.location.search);
const deepOng = params.get('ong');
carregarListaOngs();
if (deepOng) {
  directOngId.value = deepOng;
  verificarSelo(deepOng);
  showView('view-verify');
}

