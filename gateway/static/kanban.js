/* kanban.js — Vanilla JS Kanban board for Arachnode dashboard
   Columns: Discovered → Contacted → Applied → Interviewing → Offer / Rejected
   - Drag-and-drop between columns (HTML5 drag API, no heavy libs)
   - PATCH /api/jobs/{id}/status on drop with optimistic update + rollback
   - Grid ↔ Kanban toggle persisted in localStorage
*/

const KANBAN_COLUMNS = [
  { id: 'discovered',   label: 'Discovered',   color: '#6c47ff' },
  { id: 'contacted',    label: 'Contacted',     color: '#3b82f6' },
  { id: 'applied',      label: 'Applied',       color: '#10b981' },
  { id: 'interviewing', label: 'Interviewing',  color: '#f59e0b' },
  { id: 'offer',        label: 'Offer',         color: '#22c55e' },
  { id: 'rejected',     label: 'Rejected',      color: '#ef4444' },
];

// Map existing statuses to kanban columns
const STATUS_MAP = {
  new:          'discovered',
  discovered:   'discovered',
  contacted:    'contacted',
  applied:      'applied',
  interviewing: 'interviewing',
  offer:        'offer',
  rejected:     'rejected',
  ignored:      'rejected',
};

let _dragSrcId   = null;   // job id being dragged
let _dragSrcCol  = null;   // original column id
let _kanbanJobs  = [];     // local copy for optimistic updates

// ── Render ──────────────────────────────────────────────────────────────────

function renderKanban(jobs) {
  _kanbanJobs = jobs.map(j => ({ ...j }));

  const board = document.getElementById('kanban-board');
  if (!board) return;

  // Group jobs by column
  const grouped = {};
  KANBAN_COLUMNS.forEach(c => { grouped[c.id] = []; });
  _kanbanJobs.forEach(j => {
    const col = STATUS_MAP[j.status] || 'discovered';
    grouped[col].push(j);
  });

  board.innerHTML = KANBAN_COLUMNS.map(col => `
    <div class="kb-col" data-col="${col.id}">
      <div class="kb-col-header">
        <span class="kb-col-dot" style="background:${col.color}"></span>
        <span class="kb-col-title">${col.label}</span>
        <span class="kb-col-count">${grouped[col.id].length}</span>
      </div>
      <div class="kb-cards" data-col="${col.id}"
           ondragover="kbDragOver(event)"
           ondragleave="kbDragLeave(event)"
           ondrop="kbDrop(event)">
        ${grouped[col.id].map(j => kbCardHTML(j)).join('')}
        <div class="kb-drop-placeholder" style="display:none"></div>
      </div>
    </div>
  `).join('');
}

function kbCardHTML(j) {
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  const tags = (j.stack || []).slice(0, 3).map(t =>
    `<span class="tag">${esc(t)}</span>`).join('');
  return `
    <div class="kb-card job-card"
         draggable="true"
         data-id="${esc(j.id)}"
         ondragstart="kbDragStart(event)"
         ondragend="kbDragEnd(event)"
         onclick="openDetailPanel('${esc(j.id)}')">
      <div class="card-company">${esc(j.company)}</div>
      <div class="card-role">${esc(j.role)}</div>
      <div class="card-tags">${tags}</div>
      <div class="card-footer">
        <span class="tag tag-gray">${esc(j.source || '—')}</span>
      </div>
    </div>`;
}

// ── Drag handlers ────────────────────────────────────────────────────────────

function kbDragStart(e) {
  const card = e.currentTarget;
  _dragSrcId  = card.dataset.id;
  _dragSrcCol = card.closest('.kb-cards').dataset.col;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', _dragSrcId);
  setTimeout(() => card.classList.add('kb-dragging'), 0);
}

function kbDragEnd(e) {
  e.currentTarget.classList.remove('kb-dragging');
  document.querySelectorAll('.kb-cards').forEach(c => {
    c.classList.remove('kb-drag-over');
    const ph = c.querySelector('.kb-drop-placeholder');
    if (ph) ph.style.display = 'none';
  });
}

function kbDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const zone = e.currentTarget;
  zone.classList.add('kb-drag-over');
  const ph = zone.querySelector('.kb-drop-placeholder');
  if (ph) ph.style.display = 'block';
}

function kbDragLeave(e) {
  const zone = e.currentTarget;
  if (!zone.contains(e.relatedTarget)) {
    zone.classList.remove('kb-drag-over');
    const ph = zone.querySelector('.kb-drop-placeholder');
    if (ph) ph.style.display = 'none';
  }
}

async function kbDrop(e) {
  e.preventDefault();
  const zone    = e.currentTarget;
  const newCol  = zone.dataset.col;
  zone.classList.remove('kb-drag-over');

  if (!_dragSrcId || newCol === _dragSrcCol) return;

  // Optimistic update — move card locally immediately
  const jobIdx = _kanbanJobs.findIndex(j => j.id === _dragSrcId);
  if (jobIdx === -1) return;
  const prevStatus = _kanbanJobs[jobIdx].status;
  _kanbanJobs[jobIdx].status = newCol;
  renderKanban(_kanbanJobs);

  // PATCH backend
  try {
    const res = await fetch(`/api/jobs/${_dragSrcId}/status`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ status: newCol }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // Sync back to main state.jobs array
    const mainJob = (window._state?.jobs || []).find(j => j.id === _dragSrcId);
    if (mainJob) mainJob.status = newCol;
    showKbToast(`Moved to ${KANBAN_COLUMNS.find(c => c.id === newCol)?.label}`, 'success');
  } catch (err) {
    // Rollback on failure
    _kanbanJobs[jobIdx].status = prevStatus;
    renderKanban(_kanbanJobs);
    showKbToast('Status update failed — reverted', 'error');
  }
}

// ── Toast (reuses existing toast if available, else own) ─────────────────────

function showKbToast(msg, type) {
  if (typeof toast === 'function') { toast(msg, type); return; }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toasts')?.appendChild(el);
  setTimeout(() => { el.classList.add('fade-out'); setTimeout(() => el.remove(), 350); }, 3000);
}

// ── View toggle ──────────────────────────────────────────────────────────────

function initViewToggle() {
  const saved = localStorage.getItem('arachnode_view') || 'grid';
  setView(saved, false);
}

function setView(view, save = true) {
  const grid   = document.getElementById('jobs-grid');
  const board  = document.getElementById('kanban-board');
  const btnG   = document.getElementById('btn-view-grid');
  const btnK   = document.getElementById('btn-view-kanban');

  if (view === 'kanban') {
    grid?.style  && (grid.style.display  = 'none');
    board?.style && (board.style.display = 'flex');
    btnG?.classList.remove('active-view');
    btnK?.classList.add('active-view');
    if (window._state?.jobs?.length) renderKanban(window._state.jobs);
  } else {
    grid?.style  && (grid.style.display  = '');
    board?.style && (board.style.display = 'none');
    btnG?.classList.add('active-view');
    btnK?.classList.remove('active-view');
    if (typeof renderJobs === 'function') renderJobs();
  }

  if (save) localStorage.setItem('arachnode_view', view);
}

// Expose globally so dashboard.html can call them
window.kbDragStart  = kbDragStart;
window.kbDragEnd    = kbDragEnd;
window.kbDragOver   = kbDragOver;
window.kbDragLeave  = kbDragLeave;
window.kbDrop       = kbDrop;
window.renderKanban = renderKanban;
window.initViewToggle = initViewToggle;
window.setView      = setView;
