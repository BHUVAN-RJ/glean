/**
 * content.js — CSCI 576 AI TA Chrome Extension (v2)
 *
 * Lifecycle:
 *   IDLE      → video playing or initial state
 *   LISTENING → video paused, single mic session, live transcript shown
 *   THINKING  → request in-flight
 *   RESPONSE  → overlay + TTS playing
 *   FOLLOWUP  → TTS done, listening again for follow-up (video still paused)
 *
 * Mic strategy:
 *   - Pre-acquire mic permission ONCE via getUserMedia at boot
 *   - Each listen cycle creates ONE SpeechRecognition instance
 *   - Never auto-restart in onend (that causes permission re-prompts)
 *   - After TTS response, start a new listen cycle for follow-up
 */

const API_BASE = 'http://localhost:8000';
const SILENCE_MS      = 12000;  // no speech at all → timeout
const SEND_PAUSE_MS   = 2000;   // pause after final words → auto-send
const TYPEWRITER_MS   = 25;
const LINE_GAP_MS     = 150;

/* ── state ─────────────────────────────────────────────────────────────────── */
let video, videoContainer;
let phase = 'idle';           // idle | listening | thinking | response | followup
let recognition   = null;
let pendingCtrl   = null;
let silenceTimer  = null;
let sendTimer     = null;
let pauseDebounce = null;
let micPermissionGranted = false;
let finalText   = '';
let interimText = '';

/* ── boot ──────────────────────────────────────────────────────────────────── */
async function boot() {
  video          = document.getElementById('lectureVideo');
  videoContainer = document.getElementById('videoContainer');
  if (!video || !videoContainer) { setTimeout(boot, 500); return; }

  // Pre-request mic permission once — no further prompts after this
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(t => t.stop());   // release immediately
    micPermissionGranted = true;
    console.log('[AITA] Mic permission granted');
  } catch (e) {
    console.warn('[AITA] Mic permission denied — will use text fallback');
    micPermissionGranted = false;
  }

  video.addEventListener('pause', onPause);
  video.addEventListener('play',  onPlay);
  // NOTE: no 'seeking' listener — seeking while paused should NOT reset

  console.log('[AITA] Extension v2 ready');
}

/* ── video events ──────────────────────────────────────────────────────────── */
function onPause() {
  clearTimeout(pauseDebounce);
  pauseDebounce = setTimeout(() => {
    if (!video.paused) return;
    if (phase === 'idle') {
      beginListening();
    }
    // If phase is 'response', do nothing (user is reading annotations)
  }, 400);
}

function onPlay() {
  clearTimeout(pauseDebounce);
  fullReset();
}

/* ── full reset ────────────────────────────────────────────────────────────── */
function fullReset() {
  phase = 'idle';
  killMic();
  killTTS();
  killRequest();
  clearAllUI();
  setPage('', 'Pause the video and speak your question.');
}

/* ── begin listening (single cycle) ────────────────────────────────────────── */
function beginListening() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR || !micPermissionGranted) {
    phase = 'listening';
    showBar('Type your question below');
    showTextInput();
    return;
  }

  phase      = 'listening';
  finalText  = '';
  interimText = '';

  showBar('🎙  Listening — speak your question…');
  setPage('listening', 'Listening…');

  recognition = new SR();
  recognition.lang            = 'en-US';
  recognition.continuous      = true;
  recognition.interimResults  = true;
  recognition.maxAlternatives = 1;

  /* live transcript */
  recognition.onresult = (ev) => {
    clearTimeout(silenceTimer);
    clearTimeout(sendTimer);

    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const chunk = ev.results[i][0].transcript;
      if (ev.results[i].isFinal) finalText += chunk + ' ';
      else                        interim   += chunk;
    }
    interimText = interim;

    const display = (finalText + interim).trim();
    showBar('🎙  "' + display + '"');

    /* auto-send after speech pause */
    if (finalText.trim()) {
      sendTimer = setTimeout(() => {
        const q = finalText.trim();
        killMic();
        doQuery(q);
      }, SEND_PAUSE_MS);
    }

    /* watchdog: if nothing new for 12s, send what we have or timeout */
    silenceTimer = setTimeout(() => {
      const q = (finalText + interimText).trim();
      killMic();
      if (q) doQuery(q);
      else   noSpeechFallback();
    }, SILENCE_MS);
  };

  recognition.onerror = (ev) => {
    clearTimeout(silenceTimer);
    clearTimeout(sendTimer);
    if (ev.error === 'aborted' || ev.error === 'no-speech') return;
    console.warn('[AITA] Speech error:', ev.error);
    killMic();
    showBar('⚠  Mic error — type your question below');
    showTextInput();
  };

  /* When recognition ends naturally, do NOT restart.
     If we have text, send it.  Otherwise show fallback. */
  recognition.onend = () => {
    if (phase !== 'listening') return;
    clearTimeout(silenceTimer);
    clearTimeout(sendTimer);
    const q = finalText.trim();
    if (q) {
      doQuery(q);
    } else {
      noSpeechFallback();
    }
  };

  /* initial silence watchdog */
  silenceTimer = setTimeout(() => {
    killMic();
    noSpeechFallback();
  }, SILENCE_MS);

  try {
    recognition.start();
  } catch (e) {
    console.error('[AITA] recognition.start() failed:', e);
    noSpeechFallback();
  }
}

function noSpeechFallback() {
  showBar('No speech detected — type your question below');
  showTextInput();
}

/* ── mic helpers ───────────────────────────────────────────────────────────── */
function killMic() {
  clearTimeout(silenceTimer);
  clearTimeout(sendTimer);
  if (recognition) {
    const r = recognition;
    recognition = null;        // prevent onend from doing anything
    try { r.abort(); } catch (_) {}
  }
}

/* ── text fallback ─────────────────────────────────────────────────────────── */
function showTextInput() {
  if (document.getElementById('aitaInput')) return;
  const inp = document.createElement('input');
  inp.id          = 'aitaInput';
  inp.type        = 'text';
  inp.placeholder = 'Type your question and press Enter…';
  videoContainer.appendChild(inp);
  inp.focus();
  inp.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter')  { const q = inp.value.trim(); if (q) { inp.remove(); doQuery(q); } }
    if (e.key === 'Escape') { inp.remove(); fullReset(); }
  });
}

/* ── API query ─────────────────────────────────────────────────────────────── */
async function doQuery(question) {
  killRequest();
  phase = 'thinking';

  const ctrl = new AbortController();
  pendingCtrl = ctrl;

  showBar('💭  "' + question + '"  — thinking…');
  setPage('thinking', 'AI TA is thinking…');

  let frame = null;
  try { frame = grabFrame(); } catch (_) {}

  try {
    const res = await fetch(API_BASE + '/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        student_id: getStudentId(),
        timestamp:  video.currentTime,
        frame_base64: frame,
      }),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'HTTP ' + res.status);
    }
    const data = await res.json();
    pendingCtrl = null;
    showResponse(data);
  } catch (e) {
    if (e.name === 'AbortError') return;
    showBar('❌  ' + e.message);
    setPage('error', e.message);
  }
}

function killRequest() {
  if (pendingCtrl) { pendingCtrl.abort(); pendingCtrl = null; }
}

function grabFrame() {
  const c = document.createElement('canvas');
  c.width = 640; c.height = 360;
  c.getContext('2d').drawImage(video, 0, 0, 640, 360);
  return c.toDataURL('image/jpeg', 0.7).split(',')[1];
}

/* ── response overlay ──────────────────────────────────────────────────────── */
function showResponse(data) {
  phase = 'response';
  removeBar();
  setPage('active', 'AI TA responding');

  const overlay = makeOverlay();
  const ann = overlay.querySelector('#aitaAnn');
  ann.innerHTML = '';

  const lines = data.annotations?.length ? data.annotations : [data.answer];

  let delay = 0;
  lines.forEach(text => {
    const row = document.createElement('div');
    row.className = 'aita-line';
    row.innerHTML = '<span class="aita-bullet">▸</span><span class="aita-text"></span>';
    ann.appendChild(row);
    const sp = row.querySelector('.aita-text');
    setTimeout(() => { row.classList.add('shown'); tw(sp, text, 0); }, delay);
    delay += text.length * TYPEWRITER_MS + LINE_GAP_MS;
  });

  if (data.highlights) paintHighlight(data.highlights);

  // TTS — when done, transition to follow-up listening
  setTimeout(() => speak(data.answer), 500);
}

function tw(el, txt, i) {
  if (i >= txt.length) return;
  el.textContent += txt[i];
  setTimeout(() => tw(el, txt, i + 1), TYPEWRITER_MS);
}

/* ── TTS ───────────────────────────────────────────────────────────────────── */
function speak(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  u.onend = () => {
    // After speaking, start listening for a follow-up (video still paused)
    if (phase === 'response' && video.paused) {
      phase = 'followup';
      setPage('listening', 'Ask a follow-up question or press play');
      beginListening();
    }
  };
  window.speechSynthesis.speak(u);
}

function killTTS() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

/* ── highlight ─────────────────────────────────────────────────────────────── */
function paintHighlight(box) {
  let c = document.getElementById('aitaHL');
  if (!c) {
    c = document.createElement('canvas');
    c.id = 'aitaHL';
    c.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:9997';
    videoContainer.appendChild(c);
  }
  c.width  = videoContainer.clientWidth;
  c.height = videoContainer.clientHeight;
  const ctx = c.getContext('2d');
  const w = c.width, h = c.height;
  ctx.fillStyle = 'rgba(0,0,0,0.4)';
  ctx.fillRect(0, 0, w, h);
  ctx.clearRect(box.x1*w, box.y1*h, (box.x2-box.x1)*w, (box.y2-box.y1)*h);
  ctx.strokeStyle = '#7c83f5';
  ctx.lineWidth = 3;
  ctx.shadowColor = '#7c83f5';
  ctx.shadowBlur = 12;
  ctx.strokeRect(box.x1*w, box.y1*h, (box.x2-box.x1)*w, (box.y2-box.y1)*h);
}

/* ── small listening bar ───────────────────────────────────────────────────── */
function showBar(text) {
  let bar = document.getElementById('aitaBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'aitaBar';
    videoContainer.appendChild(bar);
  }
  bar.textContent = text;
}
function removeBar() {
  const b = document.getElementById('aitaBar');
  if (b) b.remove();
}

/* ── response overlay ──────────────────────────────────────────────────────── */
function makeOverlay() {
  let o = document.getElementById('aitaOverlay');
  if (o) return o;
  o = document.createElement('div');
  o.id = 'aitaOverlay';
  o.innerHTML = '<button id="aitaX" title="Dismiss">✕</button><div id="aitaAnn"></div>';
  videoContainer.appendChild(o);
  document.getElementById('aitaX').addEventListener('click', (e) => {
    e.stopPropagation();
    fullReset();
  });
  return o;
}

/* ── cleanup ───────────────────────────────────────────────────────────────── */
function clearAllUI() {
  ['aitaBar','aitaOverlay','aitaHL','aitaInput'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });
}

/* ── page helpers ──────────────────────────────────────────────────────────── */
function setPage(state, text) {
  if (typeof window.__setStatus === 'function') window.__setStatus(state, text);
}
function getStudentId() {
  return window.__studentId
      || document.getElementById('studentIdInput')?.value.trim()
      || 'demo_student_1';
}

/* ── start ─────────────────────────────────────────────────────────────────── */
document.readyState === 'loading'
  ? document.addEventListener('DOMContentLoaded', boot)
  : boot();
