'use strict';
const $ = (s) => document.querySelector(s);
const W = 960, H = 540;          // 캔버스 논리 크기
const TS = 32;                   // 타일 크기
const VISION = 7;
const cv = $('#cv');
const ctx = cv.getContext('2d');

const PLAYER_COLORS = ['#f5c542', '#5b8cff', '#5fbf4f', '#e0524a'];
const FONT = (px) => `${px}px Galmuri11, "Malgun Gothic", sans-serif`;
const SKILL_CODES = ['KeyQ', 'KeyW', 'KeyE', 'KeyR'];
const KEY_LABEL = ['Q', 'W', 'E', 'R'];
const DOLL = { helmet: [1, 2], amulet: [1, 3], weapon: [2, 1], armor: [2, 2], gloves: [2, 3], ring1: [3, 1], boots: [3, 2], ring2: [3, 3] };
const ICON_OF = { weapon: 'weapon', helmet: 'helmet', armor: 'armor', gloves: 'gloves', boots: 'boots', amulet: 'amulet', ring: 'ring', ring1: 'ring', ring2: 'ring' };
const FIELD_COLOR = { blizzard: '127,227,255', holylight: '255,226,122', bladestorm: '241,239,233' };

let META = null;
let ws = null;
let roomCode = null;
let me = null;
let S = null;          // 공개 상태
let ME = null;         // 내 개인 정보 (가방/장비/스킬)
let fatal = false;
let noticeTimer = null;
let timeOffset = 0;

let MAP = null, mapCache = null, explored = null, visible = null;
let miniCache = null, miniDirty = true;
const rpos = {};
const flashAt = {};
const fx = [], shots = [], rings = [], parts = [], lines = [];
let cam = { x: 0, y: 0 };
let mouse = null;      // {px, py, wx, wy}
let holding = false, holdTimer = null, lastSent = null;
let hudBoxes = [];
let lastFrame = performance.now();
const openWin = { inv: false, skill: false };

// ---------------- 공통 ----------------
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2200);
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* 무시 */ } };
const serverNow = () => performance.now() / 1000 + timeOffset;

function send(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }
function myPub() { return S && S.players.find((p) => p.id === me); }
function playerById(id) { return S.players.find((p) => p.id === id); }
function monsterById(id) { return S.monsters.find((m) => m.id === id); }
function entityPos(id) {
  const r = rpos[id];
  if (r) return r;
  const e = playerById(id) || monsterById(id);
  return e ? { x: e.x, y: e.y } : null;
}
function classSkills(cls) { return META.classes[cls].skills; }
const iconUrls = {};
function iconHTML(kind, size) {
  const url = iconUrls[kind] || (iconUrls[kind] = buildSprite(kind).toDataURL());
  return `<img class="px" src="${url}" width="${size}" height="${size}" alt="" draggable="false">`;
}
function icon(kind, size = 48) {
  const c = document.createElement('canvas');
  c.width = 16; c.height = 16; c.className = 'icon';
  c.style.width = c.style.height = size + 'px';
  c.getContext('2d').drawImage(buildSprite(kind), 0, 0);
  return c;
}
const rarityColor = (r) => META.rarities[r].color;
const isPct = (k) => META.pct_stats.includes(k);
function fmtVal(k, v) { return isPct(k) ? `${Math.round(v * 1000) / 10}%` : `${v}`; }
function fmtStat(k, v) { return `${META.stat_names[k] || k} ${v >= 0 ? '+' : ''}${fmtVal(k, v)}`; }
function itemStats(it) {
  const out = {}, plus = it.plus || 0;
  for (const [k, v] of Object.entries(it.stats)) {
    out[k] = isPct(k) ? Math.round(v * (1 + 0.05 * plus) * 1000) / 1000 : Math.round(v * (1 + 0.1 * plus));
  }
  return out;
}
function itemName(it) { return `${it.plus ? `+${it.plus} ` : ''}${it.name}`; }

// ---------------- 접속 ----------------
async function init() {
  META = await (await fetch('/api/meta')).json();
  $('#name').value = lsGet('name') || '';
  const q = new URLSearchParams(location.search).get('room');
  if (q) $('#code').value = q.toUpperCase();
  $('#btn-create').onclick = createRoom;
  $('#btn-join').onclick = () => joinRoom($('#code').value.trim().toUpperCase());
  $('#code').onkeydown = (e) => { if (e.key === 'Enter') $('#btn-join').click(); };
  $('#btn-copy').onclick = copyLink;
  $('#btn-ready').onclick = () => send({ t: 'ready' });
  $('#btn-start').onclick = () => send({ t: 'start' });
  $('#btn-sort').onclick = () => send({ t: 'sort' });
  $('#chat-in').onkeydown = (e) => {
    e.stopPropagation();
    if (e.key === 'Enter' && e.target.value.trim()) {
      send({ t: 'chat', text: e.target.value });
      e.target.value = '';
    }
    if (e.key === 'Escape') e.target.blur();
  };
  document.querySelectorAll('[data-close]').forEach((b) => (b.onclick = () => closeWin(b.dataset.close)));
  setupInventoryDnD();
  requestAnimationFrame(loop);
  if (q && lsGet('tok_' + q.toUpperCase())) joinRoom(q.toUpperCase());
}

function saveName() {
  const n = $('#name').value.trim() || '모험가';
  lsSet('name', n);
  return n;
}

async function createRoom() {
  $('#home-err').textContent = '';
  try {
    const r = await fetch('/api/rooms', { method: 'POST' });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || '방을 만들 수 없습니다.');
    joinRoom(j.code);
  } catch (e) {
    $('#home-err').textContent = e.message;
  }
}

function joinRoom(code) {
  if (!/^[A-Z0-9]{4}$/.test(code)) {
    $('#home-err').textContent = '방 코드 4자리를 입력하세요.';
    return;
  }
  roomCode = code;
  fatal = false;
  history.replaceState(null, '', '?room=' + code);
  connect();
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/${roomCode}`);
  const sock = ws;
  sock.onopen = () => sock.send(JSON.stringify({ t: 'hello', name: saveName(), token: lsGet('tok_' + roomCode) }));
  sock.onmessage = (e) => onMessage(JSON.parse(e.data));
  sock.onclose = () => {
    if (ws !== sock || fatal) return;
    toast('연결이 끊겼습니다. 재접속 중...');
    setTimeout(() => { if (ws === sock) connect(); }, 2000);
  };
}

function onMessage(m) {
  if (m.t === 'welcome') {
    me = m.you;
    lsSet('tok_' + roomCode, m.token);
    $('#chat-log').innerHTML = '';
    m.chat.forEach(addChat);
  } else if (m.t === 'state') apply(m.state);
  else if (m.t === 'tk') applyTick(m);
  else if (m.t === 'me') applyMe(m.me);
  else if (m.t === 'chat') addChat(m.line);
  else if (m.t === 'error') toast(m.msg);
  else if (m.t === 'fatal') {
    fatal = true;
    S = null;
    showScreen('home');
    $('#home-err').textContent = m.msg;
    history.replaceState(null, '', location.pathname);
  }
}

function addChat(line) {
  const box = $('#chat-log');
  const div = document.createElement('div');
  div.innerHTML = `<b>${esc(line.name)}</b> ${esc(line.text)}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function copyLink() {
  const url = `${location.origin}/?room=${roomCode}`;
  navigator.clipboard.writeText(url).then(() => toast('초대 링크를 복사했습니다.'), () => toast(url));
}

// ---------------- 상태 반영 ----------------
function applyPlayerRow(p, row) {
  [, p.x, p.y, p.hp, p.max_hp, p.shield, p.down, p.flags] = row;
  p.downed = p.down >= 0;
}
function applyMonsterRow(m, row) { [, m.x, m.y, m.hp, m.max_hp, m.flags] = row; }

async function apply(state) {
  const prev = S;
  S = state;
  timeOffset = S.now - performance.now() / 1000;
  for (const p of S.players) applyPlayerRow(p, p.row);
  for (const m of S.monsters) applyMonsterRow(m, m.row);
  if (S.phase !== 'lobby' && S.map_id && (!MAP || MAP.map_id !== S.map_id)) await loadMap();
  if (!prev || prev.notice !== S.notice) showNotice(S.notice);
  showScreen(S.phase === 'lobby' ? 'lobby' : 'game');
  if (S.phase === 'lobby') renderLobby();
  else renderGame();
  renderWindows();
  playEvents(S.ev || []);
  updateVision();
}

function applyTick(m) {
  if (!S || S.phase === 'lobby') return;
  timeOffset = m.now - performance.now() / 1000;
  for (const row of m.p) { const p = playerById(row[0]); if (p) applyPlayerRow(p, row); }
  for (const row of m.m) { const mo = monsterById(row[0]); if (mo) applyMonsterRow(mo, row); }
  S.zones = m.z;
  S.fields = m.f;
  playEvents(m.ev);
  updateVision();
  updatePartyBars();
}

function applyMe(data) {
  const prevNpc = ME && ME.npc;
  ME = data;
  if (ME.npc && ME.npc !== prevNpc) {
    if (ME.npc === 'shop') { openWin.inv = true; }
  }
  renderWindows();
  renderPanel();
}

function playEvents(evs) {
  const now = performance.now();
  for (const e of evs) {
    switch (e.k) {
      case 'shot': {
        const a = entityPos(e.src), b = entityPos(e.tgt);
        if (!a || !b) break;
        const src = playerById(e.src);
        let style = 'slash', color = '#ffffff';
        if (src) {
          const ranged = { mage: '#ff8a3d', priest: '#ffe27a' }[src.cls];
          if (e.skill === 'freeze') { style = 'bolt'; color = '#7fe3ff'; }
          else if (e.skill === 'poison') { style = 'bolt'; color = '#9be15d'; }
          else if (e.skill === 'heal') { style = 'bolt'; color = '#7dffa0'; }
          else if (e.skill === 'backstab') { style = 'slash'; color = '#ff4d4d'; }
          else if (ranged) { style = 'bolt'; color = ranged; }
        } else if (e.skill === 'heal') { style = 'bolt'; color = '#7dffa0'; }
        else {
          const mo = monsterById(e.src);
          const pc = mo && ENEMY_PROJ[mo.kind];
          if (pc) { style = 'bolt'; color = pc; } else { style = 'claw'; color = '#ff6b5e'; }
        }
        shots.push({ ax: a.x, ay: a.y, bx: b.x, by: b.y, style, color, t0: now, dur: style === 'bolt' ? 200 : 170 });
        break;
      }
      case 'dmg': {
        const b = entityPos(e.tgt);
        if (!b) break;
        flashAt[e.tgt] = now;
        const col = e.kind === 'poison' ? '#9be15d' : e.kind === 'burn' ? '#ff9f43' : e.crit ? '#ffb020'
          : playerById(e.tgt) ? '#ff5a4f' : '#ffffff';
        floatText(b.x, b.y - 0.6, (e.crit ? '치명! ' : '') + e.v, col, e.crit ? 18 : 14);
        break;
      }
      case 'heal': { const b = entityPos(e.tgt); if (b) floatText(b.x, b.y - 0.6, '+' + e.v, '#5fef6f', 14); break; }
      case 'aoe': rings.push({ x: e.x, y: e.y, r: e.r, c: e.c, t0: now }); break;
      case 'chain': lines.push({ x0: e.x0, y0: e.y0, x: e.x, y: e.y, c: '#9fd8ff', t0: now, dur: 250, zig: true }); break;
      case 'line': lines.push({ x0: e.x0, y0: e.y0, x: e.x, y: e.y, c: '#ff3b2f', t0: now, dur: e.t * 1000, warn: true }); break;
      case 'dash': {
        lines.push({ x0: e.x0, y0: e.y0, x: e.x, y: e.y, c: e.s === 'charge' ? '#ffd27a' : '#c9b8ff', t0: now, dur: 300 });
        if (rpos[e.src]) { rpos[e.src].x = e.x; rpos[e.src].y = e.y; }
        break;
      }
      case 'cast': {
        const a = entityPos(e.src);
        if (a) floatText(a.x, a.y - 1.1, e.name, playerById(e.src) ? '#f5c542' : '#ff9a8a', 12);
        if (e.src === me && ME && e.until !== undefined) ME.cds[e.id] = e.until;
        break;
      }
      case 'die': {
        const b = entityPos(e.tgt);
        if (!b) break;
        if (monsterById(e.tgt)) {
          for (let i = 0; i < 14; i++) {
            const a = Math.random() * Math.PI * 2, sp = 0.5 + Math.random() * 1.5;
            parts.push({ x: b.x, y: b.y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 1, t0: now, c: i % 2 ? '#ffffff' : '#9a90b0' });
          }
          S.monsters = S.monsters.filter((m) => m.id !== e.tgt);
        } else floatText(b.x, b.y - 1, '쓰러짐!', '#ff5a4f', 16);
        break;
      }
      case 'revive': { const b = entityPos(e.tgt); if (b) floatText(b.x, b.y - 1, '부활!', '#f5c542', 16); break; }
      case 'lvl': {
        const b = entityPos(e.tgt);
        if (b) { floatText(b.x, b.y - 1.3, 'LEVEL UP!', '#f5c542', 18); rings.push({ x: b.x, y: b.y, r: 1.5, c: '#f5c542', t0: now }); }
        break;
      }
    }
  }
}
const ENEMY_PROJ = { archer: '#d6b36a', cultist: '#c56bff', necro: '#7fffd4', lich: '#7fffd4' };

function floatText(x, y, text, color, size) {
  fx.push({ x: x * TS + (Math.random() - 0.5) * 10, y: y * TS, text, color, size, t0: performance.now() });
}

function showNotice(text) {
  const el = $('#notice');
  el.textContent = text || '';
  clearTimeout(noticeTimer);
  if (text) noticeTimer = setTimeout(() => (el.textContent = ''), 5000);
}

function showScreen(name) {
  for (const id of ['home', 'lobby', 'game']) $('#' + id).hidden = id !== name;
}

// ---------------- 맵 & 시야 ----------------
async function loadMap() {
  const r = await fetch(`/api/rooms/${roomCode}/map`);
  if (!r.ok) return;
  MAP = await r.json();
  explored = new Uint8Array(MAP.w * MAP.h);
  visible = new Uint8Array(MAP.w * MAP.h);
  if (MAP.town) explored.fill(1);
  buildMapCache();
  for (const k of Object.keys(rpos)) delete rpos[k];
  miniDirty = true;
  visKey = '';
}

const isFloor = (x, y) => MAP && x >= 0 && y >= 0 && x < MAP.w && y < MAP.h && MAP.tiles[y][x] === '.';

function hash(x, y) {
  let h = (x * 374761393 + y * 668265263) ^ 0x5bd1e995;
  h = (h ^ (h >>> 13)) * 1274126177;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function buildMapCache() {
  mapCache = document.createElement('canvas');
  mapCache.width = MAP.w * TS;
  mapCache.height = MAP.h * TS;
  const c = mapCache.getContext('2d');
  const town = MAP.town;
  c.fillStyle = '#0c0a10';
  c.fillRect(0, 0, mapCache.width, mapCache.height);
  for (let y = 0; y < MAP.h; y++) {
    for (let x = 0; x < MAP.w; x++) {
      const px = x * TS, py = y * TS;
      const r = hash(x, y);
      if (isFloor(x, y)) {
        if (town) {
          c.fillStyle = r < 0.5 ? '#3a4a2e' : '#3e4f31';
          c.fillRect(px, py, TS, TS);
          if (r > 0.7) { c.fillStyle = '#4f6a3a'; c.fillRect(px + ((r * 97) | 0) % 24, py + ((r * 53) | 0) % 24, 3, 5); }
          continue;
        }
        c.fillStyle = r < 0.5 ? '#29222f' : '#2c2533';
        c.fillRect(px, py, TS, TS);
        c.fillStyle = '#231d29';
        c.fillRect(px, py, TS, 1);
        c.fillRect(px, py, 1, TS);
        if (r > 0.8) { c.fillStyle = '#352d3e'; c.fillRect(px + 6 + ((r * 97) | 0) % 16, py + 8 + ((r * 53) | 0) % 14, 3, 2); }
        if (r < 0.06) { c.fillStyle = '#1d1823'; c.fillRect(px + 8, py + 14, 10, 2); c.fillRect(px + 16, py + 16, 2, 6); }
      } else if (isFloor(x, y + 1)) {
        c.fillStyle = town ? '#6b5a44' : '#463c55';
        c.fillRect(px, py, TS, TS);
        c.fillStyle = town ? '#857058' : '#5a4e6b';
        c.fillRect(px, py, TS, 5);
        c.fillStyle = town ? '#54462f' : '#352d42';
        for (let by = 9; by < TS; by += 8) {
          c.fillRect(px, py + by, TS, 1);
          const off = ((by / 8) | 0) % 2 ? 8 : 0;
          for (let bx = off; bx < TS; bx += 16) c.fillRect(px + bx, py + by - 7, 1, 7);
        }
        c.fillStyle = 'rgba(0,0,0,0.35)';
        c.fillRect(px, py + TS - 3, TS, 3);
      } else {
        const near = [[1, 0], [-1, 0], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]].some(([dx, dy]) => isFloor(x + dx, y + dy));
        c.fillStyle = near ? (town ? '#2a2318' : '#1b1622') : '#0c0a10';
        c.fillRect(px, py, TS, TS);
        if (near) {
          c.fillStyle = town ? '#857058' : '#5a4e6b';
          if (isFloor(x - 1, y)) c.fillRect(px, py, 3, TS);
          if (isFloor(x + 1, y)) c.fillRect(px + TS - 3, py, 3, TS);
          if (isFloor(x, y - 1)) c.fillRect(px, py, TS, 3);
        }
      }
    }
  }
}

function los(x0, y0, x1, y1) {
  let dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  while (true) {
    if (x0 === x1 && y0 === y1) return true;
    if (!isFloor(x0, y0)) return false;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
}

let visKey = '';
function updateVision() {
  if (!MAP || !S || !S.players) return;
  const tiles = S.players.map((p) => [Math.floor(p.x), Math.floor(p.y)]);
  const key = tiles.join('|');
  if (key === visKey) return;
  visKey = key;
  visible.fill(MAP.town ? 1 : 0);
  if (MAP.town) return;
  for (const [px, py] of tiles) {
    for (let y = py - VISION; y <= py + VISION; y++) {
      for (let x = px - VISION; x <= px + VISION; x++) {
        if (x < 0 || y < 0 || x >= MAP.w || y >= MAP.h) continue;
        if ((x - px) ** 2 + (y - py) ** 2 > VISION * VISION + 2) continue;
        if (los(px, py, x, y)) {
          const i = y * MAP.w + x;
          visible[i] = 1;
          if (!explored[i]) { explored[i] = 1; miniDirty = true; }
        }
      }
    }
  }
}
const isVisible = (x, y) => { x = Math.floor(x); y = Math.floor(y); return visible && x >= 0 && y >= 0 && x < MAP.w && y < MAP.h && visible[y * MAP.w + x]; };
const isExplored = (x, y) => { x = Math.floor(x); y = Math.floor(y); return explored && x >= 0 && y >= 0 && x < MAP.w && y < MAP.h && explored[y * MAP.w + x]; };

// ---------------- 로비 ----------------
function renderLobby() {
  $('#lobby-code').textContent = S.code;
  const box = $('#lobby-players');
  box.innerHTML = '';
  for (let i = 0; i < 4; i++) {
    const p = S.players[i];
    const div = document.createElement('div');
    if (!p) { div.className = 'lp empty'; div.textContent = '빈 자리'; }
    else {
      div.className = 'lp';
      div.appendChild(icon(p.cls));
      const who = document.createElement('div');
      who.className = 'who';
      who.innerHTML = `<span>${esc(p.name)}${p.id === me ? ' (나)' : ''}</span>
        <span class="tag">${META.classes[p.cls].name}${p.id === S.host ? ' · 방장' : ''}</span>
        <span class="tag ${p.ready ? 'ready' : ''}">${p.ready ? '준비 완료' : '대기 중'}</span>`;
      div.appendChild(who);
    }
    box.appendChild(div);
  }
  const mp = myPub();
  const list = $('#class-list');
  list.innerHTML = '';
  for (const [id, c] of Object.entries(META.classes)) {
    const div = document.createElement('div');
    div.className = 'cls' + (mp && mp.cls === id ? ' sel' : '');
    const head = document.createElement('div');
    head.className = 'cls-head';
    head.appendChild(icon(id));
    head.insertAdjacentHTML('beforeend', `<div><b>${c.name}</b><div class="stats">${esc(c.desc)}</div></div>`);
    div.appendChild(head);
    div.insertAdjacentHTML('beforeend', `
      <div class="stats">체력 ${c.hp} · 공격 ${c.atk} · 방어 ${c.df} · 사거리 ${c.basic.range}</div>
      <ul><li><b>자동 공격</b> ${c.basic.name}</li>
      ${c.skills.map((s, i) => `<li><b>[${KEY_LABEL[i]}] ${s.name}</b> ${s.req ? `(Lv.${s.req}) ` : ''}${esc(fmtDesc(s, 1))}</li>`).join('')}
      <li><b>패시브</b> ${c.passives.map((s) => s.name).join(', ')}</li></ul>`);
    div.onclick = () => send({ t: 'class', cls: id });
    list.appendChild(div);
  }
  $('#btn-ready').textContent = mp && mp.ready ? '준비 취소' : '준비';
  $('#btn-ready').classList.toggle('on', !!(mp && mp.ready));
  $('#btn-start').hidden = S.host !== me;
  const allReady = S.players.every((p) => p.ready || p.id === S.host);
  $('#btn-start').textContent = allReady ? '시작' : '시작 (준비 안 된 사람 있음)';
}

function skillVal(s, key, lvl) { return (s[key] || 0) + ((s.lv || {})[key] || 0) * (lvl - 1); }
function fmtDesc(s, lvl) {
  return s.desc.replace(/\{(\w+)\}/g, (_, k) => {
    const v = skillVal(s, k, Math.max(1, lvl));
    return k === 'ratio' ? `${Math.round(v * 100)}%` : `${Math.round(v * 100) / 100}`;
  });
}

// ---------------- 게임 패널 / 창 ----------------
function renderGame() {
  $('#top-info').textContent = S.town ? `마을 · 최고 ${S.best_floor}층` : `${S.floor}층 · 최고 ${S.best_floor}층`;
  $('#top-code').textContent = S.code;
  const log = $('#log');
  log.innerHTML = S.log.map((l) => `<div class="${l.startsWith('──') ? 'floor' : ''}">${esc(l)}</div>`).join('');
  log.scrollTop = log.scrollHeight;
  renderPanel();
}

function renderPanel() {
  const el = $('#panel');
  if (!S || S.phase === 'lobby') return;
  el.classList.add('slim');
  if (S.phase === 'gameover') {
    let h = `<h3>모험 종료 — ${S.floor}층 도달 (최고 ${S.best_floor}층)</h3>`;
    if (S.host === me) {
      h += `<div class="row"><button class="btn primary" data-start>같은 파티로 다시 도전</button>
        <button class="btn" data-lobby>로비로 (직업 변경)</button></div>`;
    } else h += '<p class="muted">방장이 다시 시작하길 기다리는 중...</p>';
    el.innerHTML = h;
    return;
  }
  let h = '<div class="party-row">';
  S.players.forEach((p, i) => {
    const r = Math.max(0, p.hp / p.max_hp);
    h += `<div class="pm"><span style="color:${PLAYER_COLORS[i]}">${esc(p.name)}</span>
      <span class="muted">Lv.${p.level} ${META.classes[p.cls].name}${p.connected ? '' : ' (끊김)'}</span>
      <div class="hpbar" data-hp="${p.id}"><div style="width:${r * 100}%"></div><span>${p.downed ? '쓰러짐' : `${p.hp}/${p.max_hp}`}</span></div></div>`;
  });
  const [near, total] = S.gather;
  const what = S.stairs.portal ? '포탈' : '계단';
  h += `<div class="muted">${S.stairs.locked ? '계단: 보스를 쓰러뜨리면 열립니다.' : `${what}: ${near}/${total}명 모임`}</div>`;
  h += `<span class="spacer"></span><button class="btn small" data-open="inv">가방 (I)</button>
    <button class="btn small" data-open="skill">스킬 (K)${ME && ME.sp ? ` <span class="sp">+${ME.sp}</span>` : ''}</button></div>`;
  h += `<div class="hotkeys"><b>마우스 누르기</b> 이동 · <b>몬스터 클릭</b> 공격 · <b>Q W E R</b> 스킬(커서 조준) · <b>F</b> 물약 · <b>Enter</b> 채팅 · <b>Esc</b> 위장</div>`;
  if (ME && ME.prompt) {
    h = `<div class="prompt"><b>피의 제단</b> — 최대 체력 15를 바치고 공격력 3을 얻겠습니까?
      <button class="btn small primary" data-prompt="1">바친다</button>
      <button class="btn small" data-prompt="0">그만둔다</button></div>` + h;
  }
  el.innerHTML = h;
}

function updatePartyBars() {
  for (const p of S.players) {
    const bar = document.querySelector(`.hpbar[data-hp="${p.id}"]`);
    if (!bar) continue;
    bar.firstElementChild.style.width = `${Math.max(0, p.hp / p.max_hp) * 100}%`;
    bar.lastElementChild.textContent = p.downed ? `쓰러짐 ${Math.ceil(p.down)}초` : `${p.hp}/${p.max_hp}`;
  }
}

$('#panel').addEventListener('click', (e) => {
  const t = e.target.closest('[data-start],[data-lobby],[data-prompt],[data-open]');
  if (!t) return;
  const d = t.dataset;
  if (d.prompt !== undefined) send({ t: 'prompt', yes: d.prompt === '1' });
  else if (d.open) toggleWin(d.open);
  else if (t.hasAttribute('data-start')) send({ t: 'start' });
  else if (t.hasAttribute('data-lobby')) send({ t: 'lobby' });
});

function toggleWin(name) {
  openWin[name] = !openWin[name];
  renderWindows();
}
function closeWin(name) {
  if (name === 'npc') { send({ t: 'close_npc' }); return; }
  openWin[name] = false;
  renderWindows();
}

function renderWindows() {
  const inGame = S && S.phase === 'explore' && ME;
  $('#win-inv').hidden = !(inGame && openWin.inv);
  $('#win-skill').hidden = !(inGame && openWin.skill);
  $('#win-npc').hidden = !(inGame && ME.npc);
  if (!inGame) return;
  if (openWin.inv) renderInventory();
  if (openWin.skill) renderSkills();
  if (ME.npc) renderNpc();
  else hideTip();
}

// ----- 가방 -----
function renderInventory() {
  const doll = $('#doll');
  doll.style.gridTemplateRows = 'repeat(3, 50px)';
  let h = '';
  for (const [slot, [r, c]] of Object.entries(DOLL)) {
    const it = ME.eq[slot];
    h += `<div class="eqslot ${it ? '' : 'empty'}" style="grid-row:${r};grid-column:${c};${it ? `border-color:${rarityColor(it.rarity)}` : ''}"
      data-eq="${slot}" draggable="${it ? 'true' : 'false'}">${iconHTML(ICON_OF[slot], 36)}
      ${it && it.plus ? `<span class="plus">+${it.plus}</span>` : ''}<span class="lbl">${META.slot_names[slot]}</span></div>`;
  }
  doll.innerHTML = h;
  const st = ME;
  const rows = [['공격력', st.atk], ['방어력', st.df], ['최대 체력', st.max_hp], ['치명타', `${Math.round(st.crit * 100)}%`],
    ['치명 피해', `+${Math.round(st.crit_dmg * 100)}%`], ['공격 속도', `+${Math.round(st.as * 100)}%`],
    ['이동 속도', `+${Math.round(st.ms * 100)}%`], ['재사용 감소', `${Math.round(st.cdr * 100)}%`],
    ['흡혈', `${Math.round(st.lifesteal * 100)}%`], ['피해 감소', `${Math.round(st.dr * 100)}%`]];
  $('#inv-stats').innerHTML = rows.map(([k, v]) => `<span>${k} <b>${v}</b></span>`).join('');
  $('#inv-gold').textContent = `${ME.gold} G`;
  $('#inv-count').textContent = `${ME.inv.length}/40 · 물약 ${ME.potions}/${META.potion_max}`;
  let b = '';
  for (let i = 0; i < 40; i++) {
    const it = ME.inv[i];
    if (!it) { b += '<div class="cell empty" data-bag-empty></div>'; continue; }
    const bad = cantWear(it);
    b += `<div class="cell ${bad ? 'bad' : ''}" data-inv="${it.id}" draggable="true" style="border-color:${rarityColor(it.rarity)}">
      ${iconHTML(ICON_OF[it.slot], 32)}${it.plus ? `<span class="plus">+${it.plus}</span>` : ''}</div>`;
  }
  $('#bag').innerHTML = b;
}

function cantWear(it) {
  const mp = myPub();
  if (it.cls && mp && it.cls !== mp.cls) return `${META.classes[it.cls].name} 전용`;
  if (it.req > ME.level) return `레벨 ${it.req} 필요`;
  return null;
}

function findItem(id) {
  if (!ME) return null;
  return ME.inv.find((i) => i.id === id) || Object.values(ME.eq).find((i) => i && i.id === id)
    || (ME.shop || []).find((i) => i.id === id);
}

function equippedFor(it) {
  if (it.slot === 'ring') return ME.eq.ring1 || ME.eq.ring2;
  return ME.eq[it.slot];
}

function itemTipHTML(it, opts = {}) {
  const st = itemStats(it);
  let h = `<div class="nm" style="color:${rarityColor(it.rarity)}">${esc(itemName(it))}</div>
    <div class="ts">${META.rarities[it.rarity].name} ${META.slot_names[it.slot]} · 아이템 레벨 ${it.ilvl}</div>`;
  const bad = cantWear(it);
  if (it.cls) h += `<div class="${it.cls !== myPub().cls ? 'bad' : 'ts'}">${META.classes[it.cls].name} 전용</div>`;
  h += `<div class="${it.req > ME.level ? 'bad' : 'ts'}">요구 레벨 ${it.req}</div><hr>`;
  h += Object.entries(st).map(([k, v]) => `<div>${fmtStat(k, v)}</div>`).join('');
  if (it.effect) h += `<hr><div class="fx">★ ${esc(it.effect)}</div>`;
  if (it.set) {
    const set = META.sets[it.set];
    const n = (ME.sets && ME.sets[it.set]) || 0;
    h += `<hr><div class="set">${set.name} 세트 (${n}/${set.pieces.length})</div>`;
    for (const [need, d] of Object.entries(set.desc)) h += `<div class="set ${n >= +need ? '' : 'off'}">(${need}) ${d}</div>`;
  }
  if (opts.compare) {
    const cur = equippedFor(it);
    if (cur && cur.id !== it.id) {
      const cs = itemStats(cur);
      const keys = new Set([...Object.keys(st), ...Object.keys(cs)]);
      const diffs = [];
      for (const k of keys) {
        const d = Math.round(((st[k] || 0) - (cs[k] || 0)) * 1000) / 1000;
        if (d) diffs.push(`<div style="color:${d > 0 ? '#5fbf4f' : '#e0524a'}">${fmtStat(k, d)}</div>`);
      }
      h += `<hr><div class="ts">착용 중 [${esc(itemName(cur))}] 대비</div>${diffs.join('') || '<div class="ts">차이 없음</div>'}`;
    }
  }
  if (opts.price) h += `<hr><div class="gold">${opts.price}</div>`;
  if (bad && opts.compare) h += `<div class="bad">착용 불가: ${bad}</div>`;
  return h;
}

function showTip(html, e) {
  const t = $('#tip');
  t.innerHTML = html;
  t.hidden = false;
  const x = Math.min(window.innerWidth - t.offsetWidth - 8, e.clientX + 16);
  const y = Math.min(window.innerHeight - t.offsetHeight - 8, e.clientY + 12);
  t.style.left = x + 'px';
  t.style.top = y + 'px';
}
function hideTip() { $('#tip').hidden = true; }

function setupInventoryDnD() {
  const win = $('#win-inv');
  let drag = null;
  win.addEventListener('mousemove', (e) => {
    const c = e.target.closest('[data-inv],[data-eq]');
    if (!c || !ME) return hideTip();
    const it = c.dataset.inv ? findItem(c.dataset.inv) : ME.eq[c.dataset.eq];
    if (!it) return hideTip();
    const sell = c.dataset.inv && ME.npc === 'shop' ? `우클릭 판매: ${ME.values[it.id]} G` : null;
    showTip(itemTipHTML(it, { compare: !!c.dataset.inv, price: sell }), e);
  });
  win.addEventListener('mouseleave', hideTip);
  win.addEventListener('contextmenu', (e) => {
    const c = e.target.closest('[data-inv],[data-eq]');
    if (!c) return;
    e.preventDefault();
    hideTip();
    if (c.dataset.eq) send({ t: 'unequip', slot: c.dataset.eq });
    else if (ME.npc === 'shop') send({ t: 'sell', id: c.dataset.inv });
    else send({ t: 'equip', id: c.dataset.inv });
  });
  win.addEventListener('dragstart', (e) => {
    const c = e.target.closest('[data-inv],[data-eq]');
    if (!c) return;
    drag = c.dataset.inv ? { from: 'bag', id: c.dataset.inv } : { from: 'eq', slot: c.dataset.eq };
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', 'x');
    hideTip();
  });
  win.addEventListener('dragover', (e) => {
    if (!drag) return;
    const target = e.target.closest('[data-eq],#bag,#trash');
    if (!target) return;
    e.preventDefault();
    win.querySelectorAll('.drop-ok').forEach((x) => x.classList.remove('drop-ok'));
    (target.dataset.eq ? target : target.id === 'trash' ? target : target).classList.add('drop-ok');
  });
  win.addEventListener('drop', (e) => {
    e.preventDefault();
    win.querySelectorAll('.drop-ok').forEach((x) => x.classList.remove('drop-ok'));
    if (!drag) return;
    const slot = e.target.closest('[data-eq]');
    if (slot && drag.from === 'bag') send({ t: 'equip', id: drag.id, slot: slot.dataset.eq });
    else if (e.target.closest('#trash') && drag.from === 'bag') send({ t: 'drop', id: drag.id });
    else if (e.target.closest('#bag') && drag.from === 'eq') send({ t: 'unequip', slot: drag.slot });
    drag = null;
  });
  win.addEventListener('dragend', () => { drag = null; win.querySelectorAll('.drop-ok').forEach((x) => x.classList.remove('drop-ok')); });
}

// ----- 스킬 -----
function renderSkills() {
  const mp = myPub();
  const c = META.classes[mp.cls];
  $('#sp-left').textContent = ME.sp ? `남은 포인트 ${ME.sp}` : '';
  let h = '<h4 style="margin-top:0">액티브 (키보드)</h4>';
  c.skills.forEach((s, i) => { h += skillRow(s, ME.skills[s.id] || 0, KEY_LABEL[i]); });
  h += '<h4>패시브</h4>';
  c.passives.forEach((s) => { h += skillRow(s, ME.skills[s.id] || 0, '◆'); });
  h += '<p class="muted">레벨업마다 스킬 포인트 1. 같은 스킬을 올리려면 캐릭터 레벨이 2씩 더 필요합니다.</p>';
  $('#skill-body').innerHTML = h;
}

function skillRow(s, lvl, key) {
  const max = META.skill_max;
  const need = (s.req || 1) + 2 * lvl;
  const can = ME.sp > 0 && lvl < max && ME.level >= need;
  const pips = '●'.repeat(lvl) + '○'.repeat(max - lvl);
  let desc = esc(s.target ? fmtDesc(s, lvl || 1) : s.desc);
  if (s.target && lvl > 0 && lvl < max) desc += ` <span class="muted">→ 다음: ${esc(fmtDesc(s, lvl + 1))}</span>`;
  const cd = s.cd ? ` · 재사용 ${Math.round(skillVal(s, 'cd', Math.max(1, lvl)) * 10) / 10}초` : '';
  return `<div class="sk ${lvl ? '' : 'locked'}"><div class="key">${key}</div><div class="info">
    <b>${s.name}</b> <span class="pips">${pips}</span>${s.req ? ` <span class="muted">(Lv.${s.req}~)</span>` : ''}
    <div>${desc}<span class="muted">${cd}</span></div>
    ${lvl < max && !can && ME.sp > 0 ? `<div class="muted">캐릭터 레벨 ${need} 필요</div>` : ''}</div>
    <button class="btn small" data-learn="${s.id}" ${can ? '' : 'disabled'}>+</button></div>`;
}
$('#skill-body').addEventListener('click', (e) => {
  const b = e.target.closest('[data-learn]');
  if (b) send({ t: 'learn', id: b.dataset.learn });
});

// ----- 상점 / 대장장이 -----
function renderNpc() {
  const body = $('#npc-body');
  if (ME.npc === 'shop') {
    $('#npc-title').textContent = `상인 — ${ME.gold} G`;
    let h = `<div class="good">${iconHTML('potion', 28)}<span class="nm">체력 물약 (${ME.potions}/${META.potion_max})</span>
      <span class="price">${ME.potion_price} G</span><button class="btn small" data-buyp>구매</button></div><div class="goods">`;
    (ME.shop || []).forEach((it, i) => {
      h += `<div class="good" data-shop="${it.id}">${iconHTML(ICON_OF[it.slot], 28)}
        <span class="nm" style="color:${rarityColor(it.rarity)}">${esc(it.name)}${it.cls ? ` <span class="muted">(${META.classes[it.cls].name})</span>` : ''}</span>
        <span class="price">${it.price} G</span><button class="btn small" data-buy="${i}" ${ME.gold < it.price ? 'disabled' : ''}>구매</button></div>`;
    });
    h += '</div><p class="muted">가방에서 아이템을 우클릭하면 판매합니다.</p>';
    body.innerHTML = h;
  } else if (ME.npc === 'smith') {
    $('#npc-title').textContent = `대장장이 — ${ME.gold} G`;
    const list = Object.entries(ME.eq).filter(([, it]) => it).map(([s, it]) => it).concat(ME.inv);
    let h = '<div class="goods">';
    for (const it of list) {
      const [cost, chance] = ME.enhance[it.id] || [0, 0];
      const maxed = (it.plus || 0) >= META.enhance_max;
      h += `<div class="good" data-shop="${it.id}">${iconHTML(ICON_OF[it.slot], 28)}
        <span class="nm" style="color:${rarityColor(it.rarity)}">${esc(itemName(it))}</span>
        <span class="muted">${maxed ? '최대' : `성공 ${Math.round(chance * 100)}%`}</span>
        <span class="price">${maxed ? '' : cost + ' G'}</span>
        <button class="btn small" data-enh="${it.id}" ${maxed || ME.gold < cost ? 'disabled' : ''}>강화</button></div>`;
    }
    h += '</div><p class="muted">강화 1단계마다 능력치 +10% (퍼센트 옵션은 +5%). 실패해도 장비는 사라지지 않습니다.</p>';
    body.innerHTML = h;
  }
}
$('#npc-body').addEventListener('click', (e) => {
  const t = e.target.closest('[data-buy],[data-buyp],[data-enh]');
  if (!t) return;
  if (t.dataset.buy !== undefined) send({ t: 'buy', idx: +t.dataset.buy });
  else if (t.hasAttribute('data-buyp')) send({ t: 'buy_potion' });
  else if (t.dataset.enh) send({ t: 'enhance', id: t.dataset.enh });
});
$('#npc-body').addEventListener('mousemove', (e) => {
  const g = e.target.closest('[data-shop]');
  const it = g && findItem(g.dataset.shop);
  if (it) showTip(itemTipHTML(it, { compare: true }), e); else hideTip();
});
$('#npc-body').addEventListener('mouseleave', hideTip);

// ---------------- 입력 ----------------
function canvasPoint(e) {
  const r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) * (W / r.width), py = (e.clientY - r.top) * (H / r.height);
  return { px, py, wx: (px + cam.x) / TS, wy: (py + cam.y) / TS };
}
function monsterAt(wx, wy) {
  if (!S) return null;
  let best = null, bd = 1e9;
  for (const m of S.monsters) {
    if (!isVisible(m.x, m.y)) continue;
    const r = rpos[m.id] || m;
    const rad = 0.6 * (m.scale || 1) * (m.tier === 'boss' ? 1.6 : m.tier === 'elite' ? 1.2 : 1);
    const d = Math.hypot(r.x - wx, r.y - 0.3 * (m.scale || 1) - wy);
    if (d < rad && d < bd) { best = m; bd = d; }
  }
  return best;
}
function playerAt(wx, wy) { return S && S.players.find((p) => Math.hypot(p.x - wx, p.y - 0.3 - wy) < 0.6); }
function npcAt(wx, wy) {
  return S && S.objects.find((o) => (o.kind === 'shop' || o.kind === 'smith') && Math.hypot(o.x + 0.5 - wx, o.y + 0.3 - wy) < 0.8);
}
const inGame = () => S && S.phase === 'explore' && MAP;

cv.addEventListener('mousemove', (e) => {
  if (!inGame()) return;
  mouse = canvasPoint(e);
  const hud = hudAt(mouse.px, mouse.py);
  cv.style.cursor = hud || npcAt(mouse.wx, mouse.wy) ? 'pointer' : monsterAt(mouse.wx, mouse.wy) ? 'crosshair' : 'default';
});
cv.addEventListener('mouseleave', () => { mouse = null; });
cv.addEventListener('mousedown', (e) => {
  if (e.button !== 0 || !inGame()) return;
  mouse = canvasPoint(e);
  const hud = hudAt(mouse.px, mouse.py);
  if (hud) return castSkill(hud.id, true);
  const m = monsterAt(mouse.wx, mouse.wy);
  if (m) return send({ t: 'attack', id: m.id });
  const n = npcAt(mouse.wx, mouse.wy);
  if (n) return send({ t: 'talk', id: n.id });
  holding = true;
  sendMove(true);
  clearInterval(holdTimer);
  holdTimer = setInterval(() => sendMove(false), 120);
});
window.addEventListener('mouseup', () => { holding = false; clearInterval(holdTimer); });
cv.addEventListener('contextmenu', (e) => e.preventDefault());

function sendMove(force) {
  if (!holding || !mouse || !inGame()) return;
  const wx = Math.round(mouse.wx * 20) / 20, wy = Math.round(mouse.wy * 20) / 20;
  if (!force && lastSent && Math.hypot(lastSent[0] - wx, lastSent[1] - wy) < 0.15) return;
  if (!isFloor(Math.floor(wx), Math.floor(wy))) return;
  lastSent = [wx, wy];
  send({ t: 'move', x: wx, y: wy });
}

function castSkill(id, fromHud) {
  if (!ME || !inGame()) return;
  const mp = myPub();
  if (!mp || mp.downed) return;
  if (id !== 'potion' && !(ME.skills[id] > 0)) return toast('아직 배우지 않은 스킬입니다. (K: 스킬 창)');
  if ((ME.cds[id] || 0) - serverNow() > 0.05) return;
  const wx = fromHud || !mouse ? mp.x : mouse.wx;
  const wy = fromHud || !mouse ? mp.y : mouse.wy;
  const m = !fromHud && mouse && monsterAt(mouse.wx, mouse.wy);
  const p = !fromHud && mouse && playerAt(mouse.wx, mouse.wy);
  send({ t: 'skill', id, x: wx, y: wy, target: m ? m.id : p ? p.id : null });
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') return toggleBoss();
  if (e.target.tagName === 'INPUT' || !S || S.phase !== 'explore') return;
  const mp = myPub();
  if (!mp) return;
  let idx = SKILL_CODES.indexOf(e.code);
  if (idx < 0 && /^Digit[1-4]$/.test(e.code)) idx = +e.code.slice(5) - 1;
  if (idx >= 0) {
    const s = classSkills(mp.cls)[idx];
    if (s) { e.preventDefault(); castSkill(s.id); }
  } else if (e.code === 'KeyF') { e.preventDefault(); castSkill('potion'); }
  else if (e.code === 'KeyI') { e.preventDefault(); toggleWin('inv'); }
  else if (e.code === 'KeyK') { e.preventDefault(); toggleWin('skill'); }
  else if (e.code === 'Enter') { e.preventDefault(); $('#chat-in').focus(); }
});

const realTitle = document.title;
function toggleBoss() {
  const b = $('#boss');
  b.hidden = !b.hidden;
  document.title = b.hidden ? realTitle : '주간업무_회의록.docx';
  $('#boss-date').textContent = new Date().toLocaleDateString('ko-KR') + ' 10:00';
}

// ---------------- 렌더 ----------------
function loop(t) {
  const dt = Math.min(100, t - lastFrame);
  lastFrame = t;
  if (S && S.phase !== 'lobby' && !$('#game').hidden && mapCache) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = false;
    drawWorld(t, dt);
  }
  requestAnimationFrame(loop);
}

function lerpPos(id, x, y, dt) {
  const r = rpos[id];
  if (!r || Math.hypot(r.x - x, r.y - y) > 3) return (rpos[id] = { x, y });
  const k = Math.min(1, dt / 90);
  r.x += (x - r.x) * k;
  r.y += (y - r.y) * k;
  return r;
}

function drawWorld(t, dt) {
  const mp = myPub();
  if (!mp) return;
  const mr = lerpPos(me, mp.x, mp.y, dt);
  const goalX = Math.max(0, Math.min(MAP.w * TS - W, mr.x * TS - W / 2));
  const goalY = Math.max(0, Math.min(MAP.h * TS - H, mr.y * TS - H / 2));
  cam.x += (goalX - cam.x) * 0.25;
  cam.y += (goalY - cam.y) * 0.25;
  if (MAP.w * TS < W) cam.x = (MAP.w * TS - W) / 2;
  if (MAP.h * TS < H) cam.y = (MAP.h * TS - H) / 2;
  const cx = Math.round(cam.x), cy = Math.round(cam.y);
  const sx = (x) => x * TS - cx, sy = (y) => y * TS - cy;
  if (mouse) { mouse.wx = (mouse.px + cam.x) / TS; mouse.wy = (mouse.py + cam.y) / TS; }

  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  ctx.drawImage(mapCache, 0, 0, mapCache.width, mapCache.height, -cx, -cy, mapCache.width, mapCache.height);

  if (isExplored(S.stairs.x, S.stairs.y)) {
    if (S.stairs.portal) drawPortal(sx(S.stairs.x), sy(S.stairs.y), t);
    else drawStairs(sx(S.stairs.x), sy(S.stairs.y), S.stairs.locked, t);
  }
  for (const o of S.objects) {
    if (!isExplored(o.x, o.y)) continue;
    const npc = o.kind === 'shop' || o.kind === 'smith';
    ctx.globalAlpha = o.used ? 0.35 : 1;
    const bob = o.used ? 0 : Math.sin(t / 400 + o.x) * 1.5;
    const sprite = o.kind === 'shop' ? 'merchant' : o.kind;
    const size = npc ? TS * 1.5 : TS;
    ctx.drawImage(buildSprite(sprite), sx(o.x) + TS / 2 - size / 2, sy(o.y) + TS - size - 2 + bob, size, size);
    ctx.globalAlpha = 1;
    if (npc) {
      ctx.textAlign = 'center';
      ctx.font = FONT(12);
      ctx.fillStyle = '#000b';
      ctx.fillText(o.kind === 'shop' ? '상인' : '대장장이', sx(o.x) + TS / 2 + 1, sy(o.y) - 15);
      ctx.fillStyle = '#ffd34d';
      ctx.fillText(o.kind === 'shop' ? '상인' : '대장장이', sx(o.x) + TS / 2, sy(o.y) - 16);
    }
  }
  for (const g of S.items) {
    if (!isVisible(g.x, g.y)) continue;
    const gx = sx(g.x), gy = sy(g.y);
    const col = g.potion ? '#ff5a4f' : rarityColor(g.rarity);
    const glow = ctx.createRadialGradient(gx, gy, 2, gx, gy, 16);
    glow.addColorStop(0, col + 'aa');
    glow.addColorStop(1, col + '00');
    ctx.fillStyle = glow;
    ctx.fillRect(gx - 16, gy - 16, 32, 32);
    ctx.drawImage(buildSprite(g.potion ? 'potion' : ICON_OF[g.slot]), gx - 12, gy - 14 + Math.sin(t / 300 + g.x) * 2, 24, 24);
    if (!g.potion && g.rarity >= 3) {
      ctx.strokeStyle = col;
      ctx.globalAlpha = 0.5 + Math.sin(t / 150) * 0.3;
      ctx.beginPath(); ctx.moveTo(gx, gy); ctx.lineTo(gx, gy - 60); ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }

  drawFields(t, sx, sy);
  for (const [zx, zy, zr, prog] of S.zones || []) {
    const px = sx(zx), py = sy(zy), rad = zr * TS;
    ctx.fillStyle = 'rgba(255,40,30,0.16)';
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(255,40,30,0.32)';
    ctx.beginPath(); ctx.arc(px, py, rad * Math.min(1, prog), 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = `rgba(255,80,60,${0.6 + Math.sin(t / 60) * 0.3})`;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.stroke();
  }

  const ents = [];
  for (const m of S.monsters) {
    const r = lerpPos(m.id, m.x, m.y, dt);
    if (isVisible(m.x, m.y)) ents.push({ y: r.y, draw: () => drawMonster(m, r, sx, sy, t) });
  }
  S.players.forEach((p, i) => {
    const r = p.id === me ? mr : lerpPos(p.id, p.x, p.y, dt);
    ents.push({ y: r.y, draw: () => drawWalker(p, i, r, sx, sy, t) });
  });
  ents.sort((a, b) => a.y - b.y).forEach((e) => e.draw());

  drawLines(t, sx, sy);
  drawShots(t, sx, sy);
  drawRings(t, sx, sy);
  drawParticles(t, dt, sx, sy);

  if (!MAP.town) {
    const x0 = Math.floor(cx / TS), y0 = Math.floor(cy / TS);
    const x1 = Math.ceil((cx + W) / TS), y1 = Math.ceil((cy + H) / TS);
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        if (!isExplored(x, y)) { ctx.fillStyle = '#000'; ctx.fillRect(sx(x), sy(y), TS, TS); }
        else if (!isVisible(x, y)) { ctx.fillStyle = 'rgba(0,0,0,0.55)'; ctx.fillRect(sx(x), sy(y), TS, TS); }
      }
    }
    const vg = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.95);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,0.5)');
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, W, H);
  }

  for (const m of S.monsters) {
    const r = rpos[m.id];
    if (r && isVisible(m.x, m.y)) drawMonsterBar(m, sx(r.x), sy(r.y));
  }
  S.players.forEach((p, i) => {
    const r = p.id === me ? mr : rpos[p.id];
    if (r) drawNameTag(p, i, sx(r.x), sy(r.y) - 30, t);
  });
  drawFx(cx, cy);
  if (!MAP.town) drawMinimap();
  drawHoverInfo(sx, sy);
  drawHud(mp, t);

  if (mp.downed && S.phase !== 'gameover') {
    ctx.fillStyle = 'rgba(60,0,0,0.35)';
    ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center';
    ctx.font = FONT(24);
    ctx.fillStyle = '#ffdddd';
    ctx.fillText(`쓰러졌습니다 — ${Math.ceil(mp.down)}초 후 부활`, W / 2, H / 2 - 40);
  }
  if (S.phase === 'gameover') {
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(0, 0, W, H);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#e0524a';
    ctx.font = FONT(52);
    ctx.fillText('GAME OVER', W / 2, H / 2 - 10);
    ctx.fillStyle = '#ece6f5';
    ctx.font = FONT(18);
    ctx.fillText(`${S.floor}층에서 전멸`, W / 2, H / 2 + 30);
  }
}

function drawStairs(x, y, locked, t) {
  ctx.fillStyle = '#0a080d';
  ctx.fillRect(x + 2, y + 2, TS - 4, TS - 4);
  for (let i = 0; i < 4; i++) {
    ctx.fillStyle = ['#6b6080', '#544a66', '#3e364c', '#2a2434'][i];
    ctx.fillRect(x + 4 + i * 2, y + 5 + i * 6, TS - 8 - i * 4, 4);
  }
  if (locked) {
    ctx.strokeStyle = '#e0524a';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x + 6, y + 6); ctx.lineTo(x + TS - 6, y + TS - 6);
    ctx.moveTo(x + TS - 6, y + 6); ctx.lineTo(x + 6, y + TS - 6);
    ctx.stroke();
  } else {
    ctx.strokeStyle = `rgba(245,197,66,${0.5 + Math.sin(t / 250) * 0.4})`;
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 1, y + 1, TS - 2, TS - 2);
  }
}

function drawPortal(x, y, t) {
  const cxp = x + TS / 2, cyp = y + TS / 2;
  for (let i = 3; i >= 0; i--) {
    ctx.fillStyle = `rgba(${120 + i * 30},${80 + i * 20},255,${0.25 + i * 0.1})`;
    ctx.beginPath();
    ctx.ellipse(cxp, cyp, 14 + i * 4 + Math.sin(t / 200 + i) * 2, 22 + i * 5, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.textAlign = 'center';
  ctx.font = FONT(12);
  ctx.fillStyle = '#c9b8ff';
  ctx.fillText('포탈', cxp, y - 26);
}

function spriteFeet(sizePx) { return sizePx * 0.5; }

function drawWalker(p, i, r, sx, sy, t) {
  const px = sx(r.x), py = sy(r.y);
  const size = TS;
  if (p.downed) {
    ctx.save();
    ctx.globalAlpha = 0.45;
    ctx.translate(px, py);
    ctx.rotate(-Math.PI / 2);
    ctx.drawImage(buildSprite(p.cls), -size / 2, -size / 2, size, size);
    ctx.restore();
    return;
  }
  const moving = Math.hypot(r.x - p.x, r.y - p.y) > 0.03;
  const bob = moving ? Math.abs(Math.sin(t / 70)) * -3 : Math.sin(t / 400 + i);
  ctx.fillStyle = 'rgba(0,0,0,0.4)';
  ctx.beginPath(); ctx.ellipse(px, py + 8, 10, 4, 0, 0, Math.PI * 2); ctx.fill();
  const flags = p.flags || '';
  if (flags.includes('T') || flags.includes('X')) {
    ctx.strokeStyle = flags.includes('T') ? 'rgba(255,90,79,0.8)' : 'rgba(201,184,255,0.8)';
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px, py - 4, 18 + Math.sin(t / 120) * 2, 0, Math.PI * 2); ctx.stroke();
  }
  if (p.shield > 0) {
    ctx.fillStyle = 'rgba(127,176,255,0.18)';
    ctx.beginPath(); ctx.arc(px, py - 4, 17, 0, Math.PI * 2); ctx.fill();
  }
  const flash = flashAt[p.id] && t - flashAt[p.id] < 110;
  ctx.globalAlpha = p.connected ? 1 : 0.5;
  ctx.drawImage(buildSprite(p.cls, flash), px - size / 2, py - size + 10 + bob, size, size);
  ctx.globalAlpha = 1;
}

function drawNameTag(p, i, x, y, t) {
  ctx.textAlign = 'center';
  ctx.font = FONT(11);
  ctx.fillStyle = '#000b';
  ctx.fillText(p.name, x + 1, y - 7);
  ctx.fillStyle = PLAYER_COLORS[i];
  ctx.fillText(p.name, x, y - 8);
  const r = Math.max(0, p.hp / p.max_hp);
  ctx.fillStyle = '#000';
  ctx.fillRect(x - 16, y - 4, 32, 5);
  ctx.fillStyle = r > 0.5 ? '#5fbf4f' : r > 0.25 ? '#f5c542' : '#e0524a';
  ctx.fillRect(x - 16, y - 4, 32 * r, 5);
  if (p.shield > 0) { ctx.fillStyle = '#7fb0ff'; ctx.fillRect(x - 16, y - 4, Math.min(32, 32 * (p.shield / p.max_hp)), 2); }
  if (p.id === me) {
    ctx.fillStyle = '#f5c542';
    const ty = y - 30 + Math.sin(t / 200) * 2;
    ctx.beginPath(); ctx.moveTo(x - 4, ty); ctx.lineTo(x + 4, ty); ctx.lineTo(x, ty + 5); ctx.fill();
  }
}

function monsterSize(m) {
  return TS * (m.scale || 1) * (m.tier === 'boss' && (m.scale || 1) === 1 ? 2 : m.tier === 'elite' ? 1.4 : 1);
}

function drawMonster(m, r, sx, sy, t) {
  const size = monsterSize(m);
  const px = sx(r.x), py = sy(r.y);
  const flags = m.flags || '';
  const stunned = flags.includes('S');
  const winding = flags.includes('C') || flags.includes('F');
  const bob = stunned ? 0 : Math.sin(t / 300 + m.x * 3) * 1.5;
  const shake = winding ? Math.sin(t / 25) * 2 : 0;
  ctx.fillStyle = 'rgba(0,0,0,0.4)';
  ctx.beginPath(); ctx.ellipse(px, py + 8, size * 0.32, 4, 0, 0, Math.PI * 2); ctx.fill();
  if (m.tier !== 'normal' || flags.includes('E')) {
    const g = ctx.createRadialGradient(px, py - size / 2 + 10, 4, px, py - size / 2 + 10, size * 0.8);
    g.addColorStop(0, flags.includes('E') ? 'rgba(255,30,30,0.55)' : m.tier === 'boss' ? 'rgba(255,60,40,0.4)' : 'rgba(200,90,255,0.35)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(px - size, py - size * 1.4, size * 2, size * 2);
  }
  const flash = (flashAt[m.id] && t - flashAt[m.id] < 110) || (flags.includes('F') && Math.sin(t / 50) > 0);
  ctx.save();
  ctx.translate(px + size / 2 + shake, 0);
  ctx.scale(-1, 1);
  if (flags.includes('W')) ctx.filter = 'hue-rotate(160deg) saturate(1.5)';
  else if (flags.includes('P')) ctx.filter = 'sepia(1) hue-rotate(50deg) saturate(3)';
  else if (flags.includes('B')) ctx.filter = 'sepia(1) saturate(4)';
  ctx.drawImage(buildSprite(m.sprite || m.kind, flash), 0, py - size + 10 + bob, size, size);
  ctx.restore();
  if (stunned) {
    ctx.fillStyle = '#fff27a';
    for (let i = 0; i < 3; i++) {
      const a = t / 200 + i * 2.1;
      ctx.fillRect(px + Math.cos(a) * 10 - 2, py - size + 4 + Math.sin(a) * 3, 4, 4);
    }
  }
  if (winding) {
    ctx.font = FONT(16);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#ff3b2f';
    ctx.fillText('!', px, py - size - 4);
  }
  if (mouse && monsterAt(mouse.wx, mouse.wy) === m) {
    ctx.strokeStyle = 'rgba(255,90,79,0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(px - size / 2 - 2, py - size + 8, size + 4, size + 4);
  }
}

function drawMonsterBar(m, x, y) {
  const flags = m.flags || '';
  if (m.hp >= m.max_hp && !flags.includes('A') && m.tier === 'normal') return;
  const size = monsterSize(m);
  const w = m.tier === 'boss' ? 70 : m.tier === 'elite' ? 46 : 30;
  const bx = x - w / 2, by = y - size + 2;
  ctx.fillStyle = '#000';
  ctx.fillRect(bx - 1, by - 1, w + 2, 6);
  ctx.fillStyle = '#5a1010';
  ctx.fillRect(bx, by, w, 4);
  ctx.fillStyle = m.tier === 'boss' ? '#ff3b2f' : '#e0524a';
  ctx.fillRect(bx, by, w * Math.max(0, m.hp / m.max_hp), 4);
  if (m.tier !== 'normal') {
    ctx.font = FONT(11);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#000b';
    ctx.fillText(m.name, x + 1, by - 3);
    ctx.fillStyle = m.tier === 'boss' ? '#ff6b5e' : '#d39bff';
    ctx.fillText(m.name + (flags.includes('E') ? ' (광폭)' : ''), x, by - 4);
  }
}

function drawFields(t, sx, sy) {
  for (const [fxp, fyp, fr, kind] of S.fields || []) {
    const px = sx(fxp), py = sy(fyp), rad = (fr + 0.4) * TS;
    const c = FIELD_COLOR[kind] || '255,255,255';
    ctx.fillStyle = `rgba(${c},0.15)`;
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = `rgba(${c},0.6)`;
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.stroke();
    for (let i = 0; i < 10; i++) {
      const a = t / (kind === 'bladestorm' ? 80 : 600) + i * 0.63;
      const rr = rad * (kind === 'bladestorm' ? 0.75 : ((i * 37 + t / 20) % 100) / 100);
      ctx.fillStyle = `rgba(${c},0.9)`;
      if (kind === 'bladestorm') {
        ctx.save(); ctx.translate(px + Math.cos(a) * rr, py + Math.sin(a) * rr); ctx.rotate(a);
        ctx.fillRect(-7, -1, 14, 2); ctx.restore();
      } else ctx.fillRect(px + Math.cos(a) * rr - 2, py + Math.sin(a) * rr - 2, 3, 3);
    }
  }
}

function drawLines(t, sx, sy) {
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    const k = (t - l.t0) / l.dur;
    if (k >= 1) { lines.splice(i, 1); continue; }
    ctx.strokeStyle = l.c;
    ctx.globalAlpha = l.warn ? 0.4 + 0.4 * Math.sin(t / 50) : 1 - k;
    ctx.lineWidth = l.warn ? 6 : 3;
    ctx.beginPath();
    ctx.moveTo(sx(l.x0), sy(l.y0));
    if (l.zig) {
      const n = 6;
      for (let j = 1; j < n; j++) {
        const f = j / n;
        ctx.lineTo(sx(l.x0 + (l.x - l.x0) * f) + (Math.random() - 0.5) * 10, sy(l.y0 + (l.y - l.y0) * f) + (Math.random() - 0.5) * 10);
      }
    }
    ctx.lineTo(sx(l.x), sy(l.y));
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function drawShots(t, sx, sy) {
  for (let i = shots.length - 1; i >= 0; i--) {
    const s = shots[i];
    const k = (t - s.t0) / s.dur;
    if (k >= 1) { shots.splice(i, 1); continue; }
    const ax = sx(s.ax), ay = sy(s.ay) - 10, bx = sx(s.bx), by = sy(s.by) - 10;
    if (s.style === 'bolt') {
      const x = ax + (bx - ax) * k, y = ay + (by - ay) * k;
      ctx.fillStyle = s.color;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 0.4;
      ctx.beginPath(); ctx.arc(x - (bx - ax) * 0.06, y - (by - ay) * 0.06, 4, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    } else {
      const ang = Math.atan2(by - ay, bx - ax);
      ctx.strokeStyle = s.color;
      ctx.globalAlpha = 1 - k;
      ctx.lineWidth = s.style === 'claw' ? 2 : 3;
      const n = s.style === 'claw' ? 3 : 1;
      for (let j = 0; j < n; j++) {
        ctx.beginPath();
        ctx.arc(bx - Math.cos(ang) * 8, by - Math.sin(ang) * 8 + (j - (n - 1) / 2) * 5, 14, ang - 1.2 + k * 0.6, ang + 0.2 + k * 0.6);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }
}

function drawRings(t, sx, sy) {
  for (let i = rings.length - 1; i >= 0; i--) {
    const r = rings[i];
    const k = (t - r.t0) / 450;
    if (k >= 1) { rings.splice(i, 1); continue; }
    const px = sx(r.x), py = sy(r.y), rad = r.r * TS * (0.4 + 0.6 * k);
    ctx.globalAlpha = (1 - k) * 0.35;
    ctx.fillStyle = r.c;
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1 - k;
    ctx.strokeStyle = r.c;
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function drawParticles(t, dt, sx, sy) {
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i];
    const age = (t - p.t0) / 500;
    if (age >= 1) { parts.splice(i, 1); continue; }
    p.x += p.vx * dt / 1000 * 2;
    p.y += p.vy * dt / 1000 * 2;
    p.vy += dt / 1000 * 4;
    ctx.globalAlpha = 1 - age;
    ctx.fillStyle = p.c;
    ctx.fillRect(sx(p.x) - 2, sy(p.y) - 2, 4, 4);
  }
  ctx.globalAlpha = 1;
}

function drawFx(cx, cy) {
  const now = performance.now();
  ctx.textAlign = 'center';
  for (let i = fx.length - 1; i >= 0; i--) {
    const f = fx[i];
    const age = (now - f.t0) / 800;
    if (age >= 1) { fx.splice(i, 1); continue; }
    ctx.globalAlpha = 1 - age * age;
    ctx.font = FONT(f.size);
    const x = f.x - cx, y = f.y - cy - age * 26;
    ctx.fillStyle = '#000';
    ctx.fillText(f.text, x + 1, y + 1);
    ctx.fillStyle = f.color;
    ctx.fillText(f.text, x, y);
  }
  ctx.globalAlpha = 1;
}

function drawMinimap() {
  const s = 3, mw = MAP.w * s, mh = MAP.h * s;
  if (!miniCache || miniDirty) {
    miniCache = miniCache || document.createElement('canvas');
    miniCache.width = mw; miniCache.height = mh;
    const c = miniCache.getContext('2d');
    c.clearRect(0, 0, mw, mh);
    for (let y = 0; y < MAP.h; y++) {
      for (let x = 0; x < MAP.w; x++) {
        if (!explored[y * MAP.w + x]) continue;
        c.fillStyle = isFloor(x, y) ? '#6d6380' : '#2a2433';
        c.fillRect(x * s, y * s, s, s);
      }
    }
    miniDirty = false;
  }
  const ox = W - mw - 10, oy = 10;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(ox - 4, oy - 4, mw + 8, mh + 8);
  ctx.drawImage(miniCache, ox, oy);
  if (isExplored(S.stairs.x, S.stairs.y)) {
    ctx.fillStyle = S.stairs.locked ? '#e0524a' : '#f5c542';
    ctx.fillRect(ox + S.stairs.x * s - 1, oy + S.stairs.y * s - 1, 5, 5);
  }
  for (const m of S.monsters) {
    if (!isVisible(m.x, m.y)) continue;
    ctx.fillStyle = m.tier === 'boss' ? '#ff3b2f' : '#c0392b';
    ctx.fillRect(ox + m.x * s - 1, oy + m.y * s - 1, 3, 3);
  }
  S.players.forEach((p, i) => {
    ctx.fillStyle = PLAYER_COLORS[i];
    ctx.fillRect(ox + p.x * s - 2, oy + p.y * s - 2, 5, 5);
  });
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1;
  ctx.strokeRect(ox + (cam.x / TS) * s, oy + (cam.y / TS) * s, (W / TS) * s, (H / TS) * s);
}

function drawHoverInfo(sx, sy) {
  if (!mouse || hudAt(mouse.px, mouse.py)) return;
  const { wx, wy } = mouse;
  let text = null, color = '#ece6f5';
  const m = monsterAt(wx, wy);
  const g = S.items.find((q) => Math.hypot(q.x - wx, q.y - wy) < 0.5 && isVisible(q.x, q.y));
  const o = S.objects.find((q) => Math.floor(wx) === q.x && Math.floor(wy) === q.y && isExplored(q.x, q.y));
  if (m) { text = `${m.name} ${m.hp}/${m.max_hp}`; color = '#ff8a7a'; }
  else if (g) { text = g.potion ? '체력 물약' : g.name; color = g.potion ? '#ff8a7a' : rarityColor(g.rarity); }
  else if (o) text = o.used ? '(사용함)' : META.objects[o.kind];
  else if (Math.floor(wx) === S.stairs.x && Math.floor(wy) === S.stairs.y && isExplored(wx, wy)) {
    text = S.stairs.portal ? META.objects.portal : S.stairs.locked ? '계단 (보스가 지키는 중)' : '계단 — 파티 전원이 모이면 내려간다';
  }
  if (!text) return;
  ctx.font = FONT(12);
  const w = ctx.measureText(text).width + 14;
  const x = Math.min(W - w - 4, mouse.px + 16), y = mouse.py - 4;
  ctx.fillStyle = '#000d';
  ctx.fillRect(x, y, w, 20);
  ctx.fillStyle = color;
  ctx.textAlign = 'left';
  ctx.fillText(text, x + 7, y + 14);
}

// 하단 HUD: 체력/경험치 + 스킬바
function hudAt(px, py) { return hudBoxes.find((b) => px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h); }

function drawHud(mp, t) {
  hudBoxes = [];
  if (!ME) return;
  const skills = classSkills(mp.cls).map((s, i) => ({ ...s, key: KEY_LABEL[i], lvl: ME.skills[s.id] || 0 }));
  skills.push({ id: 'potion', name: '물약', key: 'F', cd: 2, count: ME.potions, lvl: 1 });
  const bw = 52, gap = 5;
  const total = skills.length * bw + (skills.length - 1) * gap;
  let x = W / 2 - total / 2;
  const y = H - bw - 8;
  const now = serverNow();
  // 체력/경험치 바
  const barW = total + 160, bx = W / 2 - barW / 2;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(bx - 6, y - 30, barW + 12, bw + 38);
  const hpR = Math.max(0, mp.hp / mp.max_hp);
  ctx.fillStyle = '#3a1010'; ctx.fillRect(bx, y - 24, barW, 12);
  ctx.fillStyle = '#c0392b'; ctx.fillRect(bx, y - 24, barW * hpR, 12);
  if (mp.shield) { ctx.fillStyle = 'rgba(127,176,255,0.8)'; ctx.fillRect(bx, y - 24, Math.min(barW, barW * mp.shield / mp.max_hp), 4); }
  ctx.font = FONT(10); ctx.textAlign = 'center'; ctx.fillStyle = '#fff';
  ctx.fillText(`${mp.hp} / ${mp.max_hp}`, W / 2, y - 14);
  ctx.fillStyle = '#1d1430'; ctx.fillRect(bx, y - 10, barW, 4);
  ctx.fillStyle = '#8f74ff'; ctx.fillRect(bx, y - 10, barW * (ME.xp / ME.xp_next), 4);
  ctx.textAlign = 'left'; ctx.font = FONT(12);
  ctx.fillStyle = '#f5c542'; ctx.fillText(`Lv.${ME.level}`, bx, y + 14);
  ctx.fillStyle = '#ffd34d'; ctx.fillText(`${ME.gold} G`, bx, y + 32);
  if (ME.sp) { ctx.fillStyle = '#7dffa0'; ctx.fillText(`스킬 +${ME.sp} (K)`, bx, y + 48); }
  x += 0;
  for (const s of skills) {
    const left = Math.max(0, (ME.cds[s.id] || 0) - now);
    const locked = s.lvl <= 0;
    const empty = s.count === 0;
    ctx.fillStyle = '#221d2e';
    ctx.fillRect(x, y, bw, bw);
    ctx.strokeStyle = locked || left > 0 || empty ? '#3d3456' : '#8f74ff';
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 1, y + 1, bw - 2, bw - 2);
    ctx.textAlign = 'center';
    ctx.font = FONT(11);
    ctx.fillStyle = locked ? '#6d6380' : '#ece6f5';
    ctx.fillText(s.name, x + bw / 2, y + bw - 8);
    ctx.font = FONT(15);
    ctx.fillStyle = locked ? '#6d6380' : '#f5c542';
    ctx.fillText(s.key, x + bw / 2, y + 22);
    if (s.count !== undefined) { ctx.font = FONT(10); ctx.fillStyle = '#ece6f5'; ctx.textAlign = 'right'; ctx.fillText(`×${s.count}`, x + bw - 4, y + 12); }
    else if (!locked) { ctx.font = FONT(9); ctx.fillStyle = '#9a90b0'; ctx.textAlign = 'right'; ctx.fillText(`${s.lvl}`, x + bw - 4, y + 11); }
    if (locked) {
      ctx.fillStyle = 'rgba(0,0,0,0.55)'; ctx.fillRect(x, y, bw, bw);
      ctx.font = FONT(9); ctx.fillStyle = '#9a90b0'; ctx.textAlign = 'center';
      ctx.fillText(s.req ? `Lv.${s.req}` : '미습득', x + bw / 2, y + 36);
    } else if (left > 0) {
      const cd = s.cd || 1;
      const k = Math.min(1, left / cd);
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(x, y + bw * (1 - k), bw, bw * k);
      ctx.textAlign = 'center'; ctx.font = FONT(15); ctx.fillStyle = '#ffffff';
      ctx.fillText(left >= 1 ? Math.ceil(left) : left.toFixed(1), x + bw / 2, y + bw / 2 + 6);
    } else if (empty) {
      ctx.fillStyle = 'rgba(0,0,0,0.6)'; ctx.fillRect(x, y, bw, bw);
    }
    hudBoxes.push({ x, y, w: bw, h: bw, id: s.id });
    x += bw + gap;
  }
}

init();
