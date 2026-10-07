// ── Storage helpers ──────────────────────────────────────────

const store = {
  async get(key) {
    return new Promise(r => chrome.storage.local.get(key, d => r(d[key])));
  },
  async set(key, val) {
    return new Promise(r => chrome.storage.local.set({[key]: val}, r));
  }
};

// ── State ────────────────────────────────────────────────────

let gatewayUrl = 'http://localhost:8080';
let queue = [];
let currentContact = null;
let stats = null;

// ── API ──────────────────────────────────────────────────────

async function api(path, opts = {}) {
  try {
    const res = await fetch(`${gatewayUrl}/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined
    });
    if (!res.ok) return null;
    if (res.status === 204) return {};
    return res.json();
  } catch {
    return null;
  }
}

// ── View switching ───────────────────────────────────────────

function showView(id) {
  ['view-settings', 'view-queue', 'view-sending'].forEach(v => {
    document.getElementById(v).classList.toggle('hidden', v !== id);
  });
}

// ── Settings view ────────────────────────────────────────────

async function initSettings() {
  const saved = await store.get('gatewayUrl');
  if (saved) {
    gatewayUrl = saved;
    document.getElementById('input-gateway-url').value = saved;
  }
}

async function saveSettings() {
  const url = document.getElementById('input-gateway-url').value.trim()
    .replace(/\/$/, '');
  if (!url) return;
  
  gatewayUrl = url;
  await store.set('gatewayUrl', url);
  
  const ok = await testConnection();
  if (ok) {
    showView('view-queue');
    loadQueue();
  } else {
    document.getElementById('settings-error').textContent =
      'Cannot reach Arachnode. Is it running?';
    document.getElementById('settings-error').classList.remove('hidden');
  }
}

async function testConnection() {
  const data = await api('/health');
  const dot = document.getElementById('status-dot');
  if (data) {
    dot.className = 'dot-green';
    return true;
  } else {
    dot.className = 'dot-red';
    return false;
  }
}

// ── Queue view ───────────────────────────────────────────────

async function loadQueue() {
  showView('view-queue');

  // Load stats
  const s = await api('/referral/stats');
  if (s) {
    stats = s;
    document.getElementById('stat-sent').textContent =
      s.by_status?.sent_today ?? s.sent_today ?? '—';
    document.getElementById('stat-remaining').textContent =
      s.daily_remaining ?? '—';
    document.getElementById('stat-total-sent').textContent =
      s.by_status?.sent ?? '—';
  }

  // Load today's queue
  const data = await api('/referral/queue/today');
  if (!data || !data.contacts || data.contacts.length === 0) {
    queue = [];
    document.getElementById('no-queue-area').classList.remove('hidden');
    document.getElementById('contact-list').innerHTML = '';
    return;
  }
  
  document.getElementById('no-queue-area').classList.add('hidden');
  queue = data.contacts;
  renderContactList();
}

function renderContactList() {
  const list = document.getElementById('contact-list');
  list.innerHTML = queue.map((c, i) => {
    const statusIcon = c.status === 'sent' ? '✓' 
      : c.status === 'skipped' ? '—' 
      : '→';
    const badgeClass = `badge-${c.contact_type || 'unknown'}`;
    const typeLabel = (c.contact_type || 'unknown').toUpperCase();
    
    return `
      <div class="contact-card ${c.status === 'sent' ? 'sent' : ''} 
                               ${c.status === 'skipped' ? 'skipped' : ''}"
           data-index="${i}">
        <div class="status-icon">${statusIcon}</div>
        <div class="contact-card-info">
          <div class="contact-card-name">
            ${esc(c.first_name)} ${esc(c.last_name || '')}
          </div>
          <div class="contact-card-meta">
            ${esc(c.position || '—')} · ${esc(c.company || '—')}
          </div>
        </div>
        <span class="type-badge ${badgeClass}">${typeLabel}</span>
      </div>`;
  }).join('');

  list.querySelectorAll('.contact-card').forEach(card => {
    card.addEventListener('click', () => {
      const idx = parseInt(card.getAttribute('data-index'), 10);
      openContact(idx);
    });
  });
}

async function generateQueue() {
  const btn = document.getElementById('btn-generate-queue');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  
  const data = await api('/referral/queue/generate', {
    method: 'POST',
    body: {
      date: todayISO(),
      count: 20,
      prefer_types: ['hr', 'leadership']
    }
  });
  
  btn.disabled = false;
  btn.textContent = 'Generate Today\'s Queue';
  
  if (data) loadQueue();
}

// ── Sending view ─────────────────────────────────────────────

async function openContact(index) {
  const contact = queue[index];
  if (!contact) return;
  if (contact.status === 'sent' || contact.status === 'skipped') return;
  
  currentContact = contact;
  
  // Populate sending view
  document.getElementById('sending-name').textContent =
    `${contact.first_name} ${contact.last_name || ''}`.trim();
  document.getElementById('sending-company').textContent =
    `${contact.position || '—'} · ${contact.company || '—'}`;
  
  const badge = document.getElementById('sending-type-badge');
  badge.className = `type-badge badge-${contact.contact_type || 'unknown'}`;
  badge.textContent = (contact.contact_type || 'unknown').toUpperCase();
  
  const draft = document.getElementById('sending-draft');
  draft.value = contact.message_draft || '';
  updateCharCount(draft.value);
  
  showView('view-sending');
  
  // Tell the content script to open this profile and fill the message box
  await openLinkedInProfile(contact);
}

async function openLinkedInProfile(contact) {
  if (!contact.linkedin_url) return;
  
  // Open the LinkedIn profile in a new tab
  const tab = await chrome.tabs.create({
    url: contact.linkedin_url,
    active: true
  });
  
  // Wait for the tab to load then send the draft
  // The content script listens for this message
  await store.set('pending_fill', {
    draft: contact.message_draft || '',
    contact_id: contact.id,
    tab_id: tab.id
  });
}

async function markSent() {
  if (!currentContact) return;
  
  const btn = document.getElementById('btn-mark-sent');
  btn.disabled = true;
  btn.textContent = 'Saving...';
  
  await api(`/referral/contacts/${currentContact.id}`, {
    method: 'PATCH',
    body: { status: 'sent' }
  });
  
  // Update local state
  const idx = queue.findIndex(c => c.id === currentContact.id);
  if (idx !== -1) queue[idx].status = 'sent';
  currentContact = null;
  
  btn.disabled = false;
  btn.textContent = '✓ Sent — Next Contact';
  
  // Clear the pending fill
  await store.set('pending_fill', null);
  
  // Go back to queue and find next pending contact
  showView('view-queue');
  renderContactList();
  loadQueueStats();
  
  // Auto-open next pending contact
  const next = queue.find(c => 
    c.status !== 'sent' && c.status !== 'skipped'
  );
  if (next) {
    setTimeout(() => openContact(queue.indexOf(next)), 400);
  }
}

async function skipContact() {
  if (!currentContact) return;
  
  await api(`/referral/contacts/${currentContact.id}`, {
    method: 'PATCH',
    body: { status: 'skipped' }
  });
  
  const idx = queue.findIndex(c => c.id === currentContact.id);
  if (idx !== -1) queue[idx].status = 'skipped';
  currentContact = null;
  
  await store.set('pending_fill', null);
  showView('view-queue');
  renderContactList();
}

async function loadQueueStats() {
  const s = await api('/referral/stats');
  if (!s) return;
  document.getElementById('stat-sent').textContent =
    s.sent_today ?? '—';
  document.getElementById('stat-remaining').textContent =
    s.daily_remaining ?? '—';
  document.getElementById('stat-total-sent').textContent =
    s.by_status?.sent ?? '—';
}

// ── Helpers ──────────────────────────────────────────────────

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function todayISO() {
  return new Date().toISOString().split('T')[0];
}

function updateCharCount(text) {
  const count = (text || '').length;
  document.getElementById('sending-char-count').textContent =
    `${count} characters`;
}

// ── Init ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  await initSettings();
  
  // Wire buttons
  document.getElementById('btn-save-settings')
    .addEventListener('click', saveSettings);
  
  document.getElementById('btn-settings-toggle')
    .addEventListener('click', () => showView('view-settings'));
  
  document.getElementById('btn-refresh-queue')
    .addEventListener('click', loadQueue);
  
  document.getElementById('btn-generate-queue')
    .addEventListener('click', generateQueue);
  
  document.getElementById('btn-mark-sent')
    .addEventListener('click', markSent);
  
  document.getElementById('btn-open-profile')
    .addEventListener('click', () => {
      if (currentContact?.linkedin_url) {
        chrome.tabs.create({ url: currentContact.linkedin_url });
      }
    });
  
  document.getElementById('btn-skip-contact')
    .addEventListener('click', skipContact);
  
  document.getElementById('btn-back-to-queue')
    .addEventListener('click', () => {
      currentContact = null;
      store.set('pending_fill', null);
      showView('view-queue');
      renderContactList();
    });
  
  document.getElementById('sending-draft')
    .addEventListener('input', e => updateCharCount(e.target.value));
  
  // Try to connect with saved URL
  const saved = await store.get('gatewayUrl');
  if (saved) {
    gatewayUrl = saved;
    const ok = await testConnection();
    if (ok) {
      showView('view-queue');
      loadQueue();
    } else {
      showView('view-settings');
    }
  } else {
    showView('view-settings');
  }
});
