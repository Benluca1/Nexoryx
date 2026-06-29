/* nex — AI harness frontend */

'use strict';

const _MOTTOS = [
  'trained in the dark. ready in the light.',
  'no cloud required. no trace left behind.',
  'local. private. learning.',
  'open weights. your data. your model.',
  'why pay for intelligence you can grow?',
];

// ── State ─────────────────────────────────────────────────────────────────────
let _activeBubble = null;
let _step = 0;

// ── Python → JS Bridge (wird von evaluate_js() aus Python aufgerufen) ─────────
window._nex = {
  appendToken(token) {
    if (!_activeBubble) return;
    const dots = _activeBubble.querySelector('.typing-dots');
    if (dots) dots.remove();
    _activeBubble.querySelector('.bubble-text').textContent += token;
    scrollDown();
  },

  onStreamEnd(meta) {
    if (_activeBubble && meta && meta.model) {
      const badge = document.createElement('span');
      badge.className = 'model-badge';
      badge.textContent = meta.model;
      _activeBubble.appendChild(badge);
    }
    _activeBubble = null;
    setSending(false);
    flashLearnIndicator();
  },

  onStreamError(msg) {
    if (_activeBubble) {
      const dots = _activeBubble.querySelector('.typing-dots');
      if (dots) dots.remove();
      _activeBubble.querySelector('.bubble-text').textContent = 'Fehler: ' + msg;
      _activeBubble = null;
    }
    setSending(false);
  },
};

// ── pywebview-Bridge abwarten ─────────────────────────────────────────────────
function waitBridge() {
  return new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) { resolve(); return; }
    window.addEventListener('pywebviewready', resolve, { once: true });
  });
}

const api = new Proxy({}, {
  get(_, method) {
    return (...args) => waitBridge().then(() => window.pywebview.api[method](...args));
  },
});

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  const motto = _MOTTOS[Math.floor(Math.random() * _MOTTOS.length)];
  setSplash(motto);
  await waitBridge();

  setSplash('connecting…');
  const daemon = await api.check_daemon();

  if (!daemon.running) {
    setSplash('⚠️ Could not start the service. Please restart nex.');
    document.querySelector('.dots').style.display = 'none';
    return;
  }

  const onboarding = await api.is_onboarding_needed();
  hideSplash();

  if (onboarding) {
    show('onboarding');
  } else {
    show('app');
    loadStatus();
  }
}

// ── Splash ────────────────────────────────────────────────────────────────────
function setSplash(msg) {
  document.getElementById('splash-msg').textContent = msg;
}

function hideSplash() {
  const s = document.getElementById('splash');
  s.style.opacity = '0';
  s.style.pointerEvents = 'none';
  setTimeout(() => s.classList.add('hidden'), 420);
}

function show(id) {
  document.getElementById(id).classList.remove('hidden');
}

// ── Onboarding ────────────────────────────────────────────────────────────────
const _steps = ['step-welcome', 'step-keys', 'step-first'];

function nextStep() {
  document.getElementById(_steps[_step]).classList.add('hidden');
  _step++;
  if (_step < _steps.length) {
    document.getElementById(_steps[_step]).classList.remove('hidden');
  }
}

async function saveKeysAndNext() {
  const data = {
    anthropic_key: document.getElementById('key-anthropic').value,
    openai_key:    document.getElementById('key-openai').value,
    gemini_key:    document.getElementById('key-gemini').value,
  };
  await api.save_config(data);
  nextStep();
}

async function sendFirstMsg() {
  const input = document.getElementById('first-msg');
  const text = input.value.trim();
  if (!text) return;

  await api.mark_onboarding_done();
  document.getElementById('onboarding').classList.add('hidden');
  show('app');
  loadStatus();

  setTimeout(() => sendMessage(text), 100);
}

// ── App ───────────────────────────────────────────────────────────────────────
function switchView(view, btn) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('view-chat').classList.toggle('hidden', view !== 'chat');
  document.getElementById('view-settings').classList.toggle('hidden', view !== 'settings');
  if (view === 'settings') loadSettingsView();
}

async function loadStatus() {
  try {
    const s = await api.get_status();
    if (s.error) { setOffline(); return; }

    document.getElementById('st-profile').textContent = s.profile || '—';
    const dot = document.getElementById('st-dot');
    dot.className = 'st-dot online';
  } catch {
    setOffline();
  }
  await loadModels();
}

async function loadModels() {
  try {
    const models = await api.get_models();
    const sel = document.getElementById('st-model');
    const prev = sel.value;
    sel.innerHTML = '<option value="">auto</option>';
    for (const m of (models || [])) {
      const opt = document.createElement('option');
      opt.value = m.tag;
      opt.textContent = m.label;
      if (m.active) opt.selected = true;
      sel.appendChild(opt);
    }
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
  } catch { /* Ollama nicht erreichbar — dropdown bleibt leer */ }
}

async function onModelChange(tag) {
  await api.set_model(tag);
}

function setOffline() {
  document.getElementById('st-dot').className = 'st-dot offline';
}

let _learnTimer = null;
function flashLearnIndicator() {
  const el = document.getElementById('st-learn');
  if (!el) return;
  clearTimeout(_learnTimer);
  el.classList.remove('hidden');
  _learnTimer = setTimeout(() => el.classList.add('hidden'), 2800);
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function sendMessage(text) {
  if (!text || _activeBubble) return;

  const hint = document.getElementById('empty-hint');
  if (hint) hint.remove();

  addBubble(text, 'user');
  _activeBubble = addBubble('', 'bot');
  setSending(true);

  api.start_ask(text);   // kehrt sofort zurück; Tokens kommen via _nex.appendToken
}

function addBubble(text, side) {
  const wrap = document.createElement('div');
  wrap.className = 'bubble bubble-' + side;

  const p = document.createElement('p');
  p.className = 'bubble-text';
  p.textContent = text;
  wrap.appendChild(p);

  if (side === 'bot' && !text) {
    const dots = document.createElement('div');
    dots.className = 'typing-dots';
    dots.innerHTML = '<span></span><span></span><span></span>';
    wrap.appendChild(dots);
  }

  document.getElementById('messages').appendChild(wrap);
  scrollDown();
  return wrap;
}

function setSending(active) {
  document.getElementById('send-btn').disabled = active;
  document.getElementById('chat-input').disabled = active;
  if (!active) document.getElementById('chat-input').focus();
}

function scrollDown() {
  const m = document.getElementById('messages');
  m.scrollTop = m.scrollHeight;
}

// ── Einstellungen ─────────────────────────────────────────────────────────────
async function loadSettingsView() {
  const [cfg, training] = await Promise.all([
    api.get_config(),
    api.get_training_status(),
  ]);

  document.getElementById('set-budget').value = cfg.daily_budget || 0;
  document.getElementById('set-persona').value = cfg.persona || '';

  // System-Info
  const info = document.getElementById('sys-info');
  const lines = [];
  if (cfg.profile)           lines.push(`Profile:        <span>${cfg.profile}</span>`);
  if (cfg.house_base)        lines.push(`Base model:     <span>${cfg.house_base}</span>`);
  if (training && !training.error) {
    lines.push(`Training data:  <span>${training.dataset_size} examples</span>`);
    if (training.house_trained) {
      lines.push(`House model:    <span>v${training.house_version} (trained)</span>`);
    }
  }
  const keysActive = Object.entries(cfg.keys || {})
    .filter(([,v]) => v).map(([k]) => k).join(', ') || '—';
  lines.push(`API keys:       <span>${keysActive}</span>`);
  info.innerHTML = lines.join('<br>') || 'No information available';
}

async function saveSettings() {
  const data = {
    daily_budget:  document.getElementById('set-budget').value,
    persona:       document.getElementById('set-persona').value,
    anthropic_key: document.getElementById('set-anthropic').value,
    openai_key:    document.getElementById('set-openai').value,
    gemini_key:    document.getElementById('set-gemini').value,
  };
  await api.save_config(data);

  const msg = document.getElementById('save-msg');
  msg.classList.remove('hidden');
  setTimeout(() => msg.classList.add('hidden'), 2500);

  loadStatus();
}

// ── Eingabe-Events ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('chat-input');
  const btn   = document.getElementById('send-btn');

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const text = input.value.trim();
      if (text) { input.value = ''; autoResize(input); sendMessage(text); }
    }
  });

  input.addEventListener('input', () => autoResize(input));

  btn.addEventListener('click', () => {
    const text = input.value.trim();
    if (text) { input.value = ''; autoResize(input); sendMessage(text); }
  });

  init();
});

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}
