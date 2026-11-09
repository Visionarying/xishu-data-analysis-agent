'use strict';

/* =========================================================
   基础工具
   ========================================================= */
const STORAGE = {
  session: 'xishu_session_id',
  activeFile: 'xishu_active_file',
  sheetPrefix: 'xishu_active_sheet_',
};

const storedSession = localStorage.getItem(STORAGE.session);

const state = {
  sessionId: storedSession || newSessionId(),
  files: [],
  analyses: [],
  favorites: [],
  settings: null,
  activeFile: null,
  activeSheetId: null,
  preview: null,
  suggestions: [],
  messages: [],
  lastResult: null,
  busy: false,
  uploading: false,
  previewOpen: false,
  qualityOpen: false,
  showAllColumns: false,
  charts: new Map(),
  loading: null,
  messageSeq: 0,
};

if (!storedSession) localStorage.setItem(STORAGE.session, state.sessionId);

const LOADING_STEPS = [
  '理解问题与意图',
  '匹配时间与指标字段',
  '执行本地只读查询',
  '生成图表与指标',
  '撰写可核对结论',
];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function newSessionId() {
  const random = (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)).replace(/-/g, '');
  return `web_${random.slice(0, 24)}`;
}

function setSessionId(id) {
  if (!id || state.sessionId === id) return;
  state.sessionId = id;
  localStorage.setItem(STORAGE.session, id);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function icon(name, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}

const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  upload: '<path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  uploadCloud: '<path d="M7 18a4.5 4.5 0 0 1-.5-8.97A6 6 0 0 1 18.2 9.5 3.8 3.8 0 0 1 18 18"/><path d="M12 20V11m0 0-3 3m3-3 3 3"/>',
  download: '<path d="M12 4v12m0 0-5-5m5 5 5-5M4 20h16"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.4 2.4 4.6-5"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9 9 0 0 0-7.5 4"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1 1.55V22a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.11-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.14.6.66 1.05 1.28 1.1H22a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  sparkles: '<path d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7Z"/><path d="M19 15v4m-2-2h4M5 3v3M3.5 4.5h3"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  arrowRight: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  warning: '<path d="M10.3 3.6 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  alertCircle: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10M15 10v10"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z"/>',
  report: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
  printer: '<path d="M6 9V3h12v6"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8" rx="1"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 15-5-5L5 20"/>',
  code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 12v7c0 1.66 3.58 3 8 3s8-1.34 8-3v-7"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  eye: '<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
};

function hydrateIcons(root = document) {
  $$('[data-icon]', root).forEach((node) => {
    if (!node.firstElementChild) node.innerHTML = icon(node.dataset.icon, 16);
  });
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function formatNumber(value, unit = '', compact = true) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const abs = Math.abs(number);
  if (compact && abs >= 1e8) return `${(number / 1e8).toFixed(2)} 亿${unit}`;
  if (compact && abs >= 1e4) return `${(number / 1e4).toFixed(2)} 万${unit}`;
  const digits = Math.abs(number) >= 100 ? 1 : 2;
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: digits })}${unit}`;
}

function formatPercent(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return `${(number * 100).toFixed(digits)}%`;
}

function formatChartValue(value, chart) {
  if (chart && chart.value_format === 'percent') return formatPercent(value, 1);
  return formatNumber(value, (chart && chart.unit) || '');
}

function formatDateTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

function timeAgo(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} 天前`;
  return formatDateTime(iso);
}

function formatCell(value, column) {
  if (value === null || value === undefined || value === '') return '<span class="null">—</span>';
  if (column.type === 'percent') return esc(formatPercent(value, 1));
  if (column.type === 'number') return esc(formatNumber(value, '', false));
  if (column.type === 'rank') return `#${esc(value)}`;
  if (column.type === 'badge') {
    const tone = String(value) === '异常' ? 'badge-red' : 'badge-gray';
    return `<span class="status-pill ${tone}">${esc(value)}</span>`;
  }
  const text = String(value);
  if (text.length > 46) return `<span title="${esc(text)}">${esc(text.slice(0, 46))}…</span>`;
  return esc(text);
}

function formatColumnValue(value, column) {
  if (value === null || value === undefined) return '';
  if (column.type === 'percent') return formatPercent(value);
  if (column.type === 'number') return formatNumber(value, '', false);
  return String(value);
}

function decodeDate(value) {
  if (typeof value !== 'string') return value;
  return value.replace('T00:00:00', '').replace('T', ' ').slice(0, 19);
}

/* =========================================================
   API
   ========================================================= */
class ApiError extends Error {
  constructor(message, status = 0, code = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

function errorMessage(data, status) {
  if (data && data.error && data.error.message) return data.error.message;
  if (data && Array.isArray(data.detail)) {
    const first = data.detail[0];
    if (first && first.msg) return String(first.msg).replace(/^Value error,\s*/, '');
  }
  if (data && typeof data.detail === 'string') return data.detail;
  return `请求失败（HTTP ${status}）`;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-Session-Id', state.sessionId);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    throw new ApiError('无法连接本地服务，请确认服务已启动。', 0, 'network');
  }
  setSessionId(response.headers.get('X-Session-Id'));
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!response.ok) {
    throw new ApiError(errorMessage(data, response.status), response.status, data && data.error ? data.error.code : '');
  }
  return data;
}

async function refreshAnalyses() {
  try {
    const data = await api('/api/analyses');
    state.analyses = data.analyses || [];
    renderSidebar();
  } catch (error) {
    console.warn(error);
  }
}

async function refreshFavorites() {
  try {
    const data = await api('/api/favorites');
    state.favorites = data.favorites || [];
    renderSidebar();
  } catch (error) {
    console.warn(error);
  }
}

function favoriteForAnalysis(analysisId) {
  return state.favorites.find((item) => item.analysis_id === analysisId) || null;
}

function updateVersionUI() {
  const node = $('#appVersion');
  const version = state.settings && state.settings.app_version;
  if (node && version) node.textContent = `v${version}`;
}

/* =========================================================
   启动与视图
   ========================================================= */
async function init() {
  hydrateIcons();
  bindEvents();
  updateModelUI();
  updateComposer();
  await boot();
}

async function boot() {
  try {
    const data = await api('/api/bootstrap');
    setSessionId(data.session_id);
    state.files = data.files || [];
    state.analyses = data.analyses || [];
    state.favorites = data.favorites || [];
    state.settings = data.settings;
    updateModelUI();
    updateVersionUI();
    renderSidebar();
    renderRecent();
    const lastFile = localStorage.getItem(STORAGE.activeFile);
    if (lastFile && state.files.some((file) => file.id === lastFile)) {
      await openFile(lastFile, { loadLatest: true });
    } else {
      showLanding();
    }
  } catch (error) {
    showLanding();
    toast(error.message || '初始化失败', 'error');
    const dot = $('#modelDot');
    if (dot) dot.className = 'dot dot-red';
    $('#modelText').textContent = '服务未连接';
  }
}

function showLanding() {
  const landing = $('#landingView');
  const workspace = $('#workspaceView');
  if (landing) landing.hidden = false;
  if (workspace) workspace.hidden = true;
  $('#breadcrumb').innerHTML = '<span class="crumb-muted">工作台</span>';
  renderRecent();
  document.title = '析数 · 数据分析 Agent';
}

function showWorkspace() {
  $('#landingView').hidden = true;
  $('#workspaceView').hidden = false;
  closeSidebar();
  updateBreadcrumb();
}

function updateBreadcrumb() {
  const file = state.activeFile;
  if (!file) {
    $('#breadcrumb').innerHTML = '<span class="crumb-muted">工作台</span>';
    return;
  }
  $('#breadcrumb').innerHTML = `
    <span class="crumb-muted">数据文件</span>
    <span class="crumb-sep">/</span>
    <span class="crumb-current" title="${esc(file.name)}">${esc(file.name)}</span>
  `;
  document.title = `${file.name} · 析数`;
}

function goLanding() {
  if (state.busy) {
    toast('请等待当前分析完成', 'info');
    return;
  }
  state.activeFile = null;
  state.activeSheetId = null;
  state.preview = null;
  state.messages = [];
  state.lastResult = null;
  state.suggestions = [];
  state.previewOpen = false;
  state.qualityOpen = false;
  state.showAllColumns = false;
  localStorage.removeItem(STORAGE.activeFile);
  showLanding();
  renderSidebar();
  const mainScroll = $('#mainScroll');
  if (mainScroll) mainScroll.scrollTop = 0;
  window.scrollTo({ top: 0 });
}

/* =========================================================
   侧边栏 / 最近文件
   ========================================================= */
function fileTypeLabel(name, extension) {
  const ext = (extension || (name && name.split('.').pop()) || '').replace('.', '').toUpperCase();
  return ext === 'XLS' ? 'XLS' : ext === 'CSV' ? 'CSV' : 'XLSX';
}

function renderSidebar() {
  const fileCount = $('#fileCount');
  if (fileCount) fileCount.textContent = String(state.files.length);

  const fileList = $('#fileList');
  if (fileList) {
    if (!state.files.length) {
      fileList.innerHTML = '<div class="side-empty">还没有上传文件</div>';
    } else {
      fileList.innerHTML = state.files.map((file) => {
        const active = state.activeFile && state.activeFile.id === file.id;
        const type = fileTypeLabel(file.name, file.extension);
        return `
          <button class="side-item ${active ? 'active' : ''}" type="button" data-file-id="${esc(file.id)}" title="${esc(file.name)}">
            <span class="item-icon ${type === 'CSV' ? 'csv' : ''}">${type}</span>
            <span class="item-body">
              <span class="item-title">${esc(file.name)}</span>
              <span class="item-sub">${file.sheet_count || 1} 个工作表 · ${formatNumber(file.row_count, '', false)} 行</span>
            </span>
            <span class="item-del" data-delete-file="${esc(file.id)}" role="button" title="删除文件">${icon('trash', 13)}</span>
          </button>
        `;
      }).join('');
    }
  }

  const historyList = $('#historyList');
  if (historyList) {
    const items = state.analyses.slice(0, 8);
    if (!items.length) {
      historyList.innerHTML = '<div class="side-empty">分析记录会保存在本机</div>';
    } else {
      historyList.innerHTML = items.map((item) => `
        <button class="side-item" type="button" data-analysis-id="${esc(item.id)}" title="${esc(item.question)}">
          <span class="item-icon history-icon">${icon('history', 14)}</span>
          <span class="item-body">
            <span class="item-title">${esc(item.question)}</span>
            <span class="item-sub">${esc(item.intent_label || '分析')} · ${timeAgo(item.created_at)}</span>
          </span>
        </button>
      `).join('');
    }
  }

  const favoriteList = $('#favoriteList');
  if (favoriteList) {
    if (!state.favorites.length) {
      favoriteList.innerHTML = '<div class="side-empty">点结果右上角星标即可收藏</div>';
    } else {
      favoriteList.innerHTML = state.favorites.slice(0, 8).map((item) => `
        <button class="side-item favorite-item" type="button" data-favorite-id="${esc(item.id)}" title="${esc(item.question)}">
          <span class="item-icon favorite-icon">${icon('star', 14)}</span>
          <span class="item-body">
            <span class="item-title">${esc(item.title)}</span>
            <span class="item-sub">${esc(item.file_name || '本地数据')} · ${timeAgo(item.updated_at || item.created_at)}</span>
          </span>
          <span class="item-del item-rerun" data-rerun-favorite="${esc(item.id)}" role="button" title="重跑并刷新">${icon('refresh', 13)}</span>
        </button>
      `).join('');
    }
    hydrateIcons(favoriteList);
  }
  hydrateIcons(fileList || document);
  hydrateIcons(historyList || document);
}

function renderRecent() {
  const block = $('#recentBlock');
  const grid = $('#recentFiles');
  if (!block || !grid) return;
  const files = state.files.slice(0, 3);
  block.hidden = files.length === 0;
  grid.innerHTML = files.map((file) => {
    const type = fileTypeLabel(file.name, file.extension);
    return `
      <button class="recent-card" type="button" data-recent-file="${esc(file.id)}">
        <span class="item-icon">${type}</span>
        <span class="item-body" style="min-width:0;text-align:left;">
          <span class="item-title">${esc(file.name)}</span>
          <span class="item-sub">${formatNumber(file.row_count, '', false)} 行 · ${file.sheet_count || 1} 个工作表 · ${timeAgo(file.created_at)}</span>
        </span>
      </button>
    `;
  }).join('');
}

/* =========================================================
   上传
   ========================================================= */
function validateFile(file) {
  const name = (file.name || '').toLowerCase();
  if (!/\.(xlsx|xls|csv)$/.test(name)) return '仅支持 .xlsx / .xls / .csv 文件。';
  if (file.size > 50 * 1024 * 1024) return '文件超过 50MB 上限，请压缩或抽样后再上传。';
  if (file.size === 0) return '文件内容为空。';
  return '';
}

function showUploadProgress(name) {
  $('#uploadIdle').hidden = true;
  $('#uploadProgress').hidden = false;
  $('#dropzone').classList.add('busy');
  $('#uploadName').textContent = name;
  $('#uploadPercent').textContent = '0%';
  $('#uploadBar').style.width = '0%';
  $('#uploadStatus').textContent = '正在安全上传到本地服务…';
}

function updateUploadProgress(percent, status) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  $('#uploadBar').style.width = `${value}%`;
  $('#uploadPercent').textContent = `${value}%`;
  if (status) $('#uploadStatus').textContent = status;
}

function resetUpload() {
  state.uploading = false;
  $('#uploadIdle').hidden = false;
  $('#uploadProgress').hidden = true;
  $('#dropzone').classList.remove('busy', 'dragging');
}

async function uploadFile(file) {
  if (state.uploading) return;
  const validation = validateFile(file);
  if (validation) {
    toast(validation, 'error');
    return;
  }
  if (state.busy) {
    toast('请等待当前分析完成后再上传', 'info');
    return;
  }
  state.uploading = true;
  if (!state.activeFile) showLanding();
  else {
    goLanding();
  }
  showUploadProgress(file.name);

  const form = new FormData();
  form.append('file', file, file.name);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/files');
  xhr.setRequestHeader('X-Session-Id', state.sessionId);
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) {
      const percent = (event.loaded / event.total) * 84;
      updateUploadProgress(percent, '正在上传文件…');
    }
  };
  xhr.upload.onload = () => {
    updateUploadProgress(96, '上传完成，正在解析工作表与字段类型…');
  };
  xhr.onerror = () => {
    resetUpload();
    toast('上传失败，请检查网络或服务状态。', 'error');
  };
  xhr.onabort = () => {
    resetUpload();
    toast('上传已取消', 'info');
  };
  xhr.onload = async () => {
    setSessionId(xhr.getResponseHeader('X-Session-Id'));
    let data = null;
    try { data = JSON.parse(xhr.responseText || '{}'); } catch { data = {}; }
    if (xhr.status !== 201) {
      resetUpload();
      toast(errorMessage(data, xhr.status), 'error');
      return;
    }
    const meta = data.file;
    updateUploadProgress(100, '解析完成，正在打开数据概览…');
    const summary = {
      id: meta.id,
      name: meta.name,
      extension: meta.extension,
      size_bytes: meta.size_bytes,
      row_count: meta.row_count,
      sheet_count: meta.sheet_count,
      status: meta.status,
      created_at: meta.created_at,
    };
    state.files = [summary, ...state.files.filter((item) => item.id !== summary.id)];
    renderSidebar();
    renderRecent();
    toast(`已解析 ${meta.sheet_count} 个工作表、${formatNumber(meta.row_count, '', false)} 行数据`, 'success');
    resetUpload();
    await openFile(meta.id, { loadLatest: false });
  };
  xhr.send(form);
}

/* =========================================================
   文件与数据概览
   ========================================================= */
async function openFile(fileId, options = {}) {
  if (state.busy) {
    toast('请等待当前分析完成', 'info');
    return;
  }
  try {
    const detail = await api(`/api/files/${fileId}`);
    const file = detail.file;
    if (!file.sheets || !file.sheets.length) {
      toast('该文件没有可分析的工作表', 'error');
      return;
    }
    state.activeFile = file;
    const storedSheet = localStorage.getItem(STORAGE.sheetPrefix + fileId);
    const requested = options.sheetId && file.sheets.some((sheet) => sheet.id === options.sheetId) ? options.sheetId : null;
    const stored = storedSheet && file.sheets.some((sheet) => sheet.id === storedSheet) ? storedSheet : null;
    state.activeSheetId = requested || stored || file.sheets[0].id;
    state.messages = [];
    state.lastResult = null;
    state.preview = null;
    state.previewOpen = false;
    state.qualityOpen = false;
    state.showAllColumns = false;
    state.suggestions = detail.suggestions || [];
    localStorage.setItem(STORAGE.activeFile, fileId);
    await loadPreview(state.activeSheetId);
    showWorkspace();
    renderAll();
    if (options.loadLatest !== false) {
      const latest = state.analyses.find((item) => item.file_id === fileId);
      if (latest) await loadAnalysis(latest.id, { skipOpen: true });
    }
  } catch (error) {
    toast(error.message || '打开文件失败', 'error');
  }
}

async function loadPreview(sheetId) {
  if (!state.activeFile) return;
  const target = sheetId || state.activeSheetId;
  try {
    const data = await api(`/api/files/${state.activeFile.id}/sheets/${target}/preview`);
    const index = state.activeFile.sheets.findIndex((sheet) => sheet.id === target);
    if (index >= 0) {
      state.activeFile.sheets[index] = { ...state.activeFile.sheets[index], ...data.sheet };
    }
    state.activeSheetId = target;
    state.preview = data.preview;
    state.lastResult = null;
    state.suggestions = data.suggestions || [];
    localStorage.setItem(STORAGE.sheetPrefix + state.activeFile.id, target);
    renderOverview();
    renderSuggestions();
  } catch (error) {
    toast(error.message || '加载工作表失败', 'error');
  }
}

async function switchSheet(sheetId) {
  if (!state.activeFile || state.busy || state.activeSheetId === sheetId) return;
  state.activeSheetId = sheetId;
  state.preview = null;
  state.lastResult = null;
  state.messages = [];
  renderOverview();
  renderMessages();
  await loadPreview(sheetId);
}

function activeSheet() {
  if (!state.activeFile) return null;
  return state.activeFile.sheets.find((sheet) => sheet.id === state.activeSheetId) || state.activeFile.sheets[0] || null;
}

function renderOverview() {
  const container = $('#dataOverview');
  const file = state.activeFile;
  if (!container || !file) {
    if (container) container.innerHTML = '';
    return;
  }
  const sheet = activeSheet();
  if (!sheet) {
    container.innerHTML = '';
    return;
  }
  const quality = sheet.quality || [];
  const warningCount = quality.filter((item) => item.level === 'warning').length;
  const columns = sheet.columns || [];
  const dates = columns.filter((column) => column.dtype === 'datetime');
  const numeric = columns.filter((column) => column.dtype === 'number');
  const dimensions = columns.filter((column) => column.dtype === 'category' || column.dtype === 'text');
  const missing = columns.reduce((sum, column) => sum + (column.missing || 0), 0);
  const primaryDate = dates[0];
  const dateRange = primaryDate && primaryDate.min !== null && primaryDate.min !== undefined && primaryDate.max !== null && primaryDate.max !== undefined
    ? `${decodeDate(primaryDate.min).slice(0, 10)} → ${decodeDate(primaryDate.max).slice(0, 10)}`
    : '未识别日期字段';
  const type = fileTypeLabel(file.name, file.extension);
  const visibleColumns = state.showAllColumns ? columns : columns.slice(0, 11);

  container.innerHTML = `
    <div class="data-overview">
      <div class="overview-top">
        <div class="file-badge ${type === 'CSV' ? 'csv' : ''}">${type}</div>
        <div class="overview-title">
          <h2 title="${esc(file.name)}">${esc(file.name)}</h2>
          <div class="overview-meta">
            <span>${formatNumber(file.row_count, '', false)} 行 · ${file.sheet_count} 个工作表 · ${formatSize(file.size_bytes)}</span>
            <span class="ok">${icon('checkCircle', 11)} 解析完成</span>
            <span>${timeAgo(file.created_at)}</span>
          </div>
        </div>
        <div class="overview-actions">
          ${quality.length ? `<button class="mini-btn ${warningCount ? 'quality-count' : ''}" type="button" data-overview="quality" aria-label="查看数据质量提示">${icon('alertCircle', 13)}<span>${warningCount ? `${warningCount} 项提示` : '数据质量'}</span></button>` : ''}
          <button class="mini-btn" type="button" data-overview="upload" title="上传新文件" aria-label="上传新文件">${icon('plus', 13)}<span>新文件</span></button>
        </div>
      </div>
      <div class="sheet-tabs" role="tablist">
        ${file.sheets.map((item) => `
          <button class="sheet-tab ${item.id === state.activeSheetId ? 'active' : ''}" type="button" role="tab" data-sheet-id="${esc(item.id)}">
            ${esc(item.name)} <small>${formatNumber(item.row_count, '', false)} 行</small>
          </button>
        `).join('')}
      </div>
      <div class="profile-strip">
        <div class="profile-cell"><span>时间范围</span><b title="${esc(dateRange)}">${esc(dateRange)}</b></div>
        <div class="profile-cell"><span>数值字段</span><b>${numeric.length} 个 · ${numeric.slice(0, 2).map((column) => esc(column.name)).join('、') || '—'}</b></div>
        <div class="profile-cell"><span>分类字段</span><b>${dimensions.length} 个</b></div>
        <div class="profile-cell"><span>缺失值</span><b>${missing.toLocaleString('zh-CN')} 个${warningCount ? ' · 有提示' : ''}</b></div>
      </div>
      <div class="columns-row">
        <span class="columns-label">字段</span>
        ${visibleColumns.map((column) => `
          <button class="col-chip t-${esc(column.dtype)} ${column.note ? 'has-note' : ''}" type="button" data-note-column="${esc(column.name)}" title="${esc(column.name)} · ${esc(column.dtype)}${column.missing ? ` · 缺失 ${column.missing}` : ''}${column.note ? ` · 备注：${column.note}` : ' · 点击补充业务备注'}">
            <i>${esc(typeShort(column.dtype))}</i>${esc(column.name)}${column.note ? '<span class="note-dot" aria-hidden="true"></span>' : ''}
          </button>
        `).join('')}
        ${columns.length > 11 ? `<button class="col-more" type="button" data-overview="columns">${state.showAllColumns ? '收起' : `展开全部 ${columns.length} 个`}</button>` : ''}
      </div>
      ${state.qualityOpen && quality.length ? `
        <div class="quality-panel">
          ${quality.map((item) => `
            <div class="quality-item ${item.level === 'info' ? 'info' : ''}">
              <span class="qi">${icon(item.level === 'info' ? 'info' : 'warning', 13)}</span>
              <span>${esc(item.message)}</span>
            </div>
          `).join('')}
        </div>
      ` : ''}
      <div class="overview-bottom">
        <button class="preview-toggle ${state.previewOpen ? 'open' : ''}" type="button" data-overview="preview">
          ${icon('chevron', 13)} ${state.previewOpen ? '收起数据预览' : '展开数据预览'}
        </button>
        <span class="overview-hint">表头与字段类型已自动识别</span>
      </div>
      ${state.previewOpen ? renderPreviewPanel() : ''}
    </div>
  `;
  hydrateIcons(container);
}

function typeShort(dtype) {
  return {
    datetime: '日期', number: '数值', category: '分类', text: '文本', id: 'ID',
  }[dtype] || dtype;
}

function renderPreviewPanel() {
  const preview = state.preview;
  if (!preview) {
    return '<div class="preview-wrap"><div class="preview-title">正在加载数据预览…</div></div>';
  }
  const columns = preview.columns || [];
  const rows = preview.rows || [];
  return `
    <div class="preview-wrap">
      <div class="preview-title">
        <span>前 ${rows.length} 行 · 共 ${formatNumber(preview.total || rows.length, '', false)} 行</span>
        <span>${columns.length} 个字段</span>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>#</th>${columns.map((column) => `<th>${esc(column.name)}</th>`).join('')}</tr></thead>
          <tbody>
            ${rows.map((row, index) => `
              <tr>
                <td class="row-index">${index + 1}</td>
                ${row.map((value, cellIndex) => renderPreviewCell(value, columns[cellIndex])).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderPreviewCell(value, column) {
  if (value === null || value === undefined || value === '') return '<td class="null">—</td>';
  const dtype = column ? column.dtype : 'text';
  if (dtype === 'datetime') {
    const text = String(value).replace('T00:00:00', '').replace('T', ' ').slice(0, 19);
    return `<td>${esc(text)}</td>`;
  }
  if (dtype === 'number') {
    const number = Number(value);
    if (!Number.isFinite(number)) return `<td>${esc(value)}</td>`;
    if (column.is_percent) return `<td class="num">${esc(formatPercent(number, 2))}</td>`;
    return `<td class="num">${esc(number.toLocaleString('zh-CN', { maximumFractionDigits: 2 }))}</td>`;
  }
  const text = String(value);
  return `<td title="${esc(text)}">${esc(text.length > 28 ? `${text.slice(0, 28)}…` : text)}</td>`;
}

/* =========================================================
   对话与结果
   ========================================================= */
function renderAll() {
  renderOverview();
  renderBreadcrumbSafe();
  renderMessages();
  renderSuggestions();
  updateComposer();
}

function renderBreadcrumbSafe() {
  try { updateBreadcrumb(); } catch (error) { console.warn(error); }
}

function renderSuggestions() {
  const bar = $('#suggestionBar');
  if (!bar) return;
  const suggestions = state.suggestions || [];
  bar.innerHTML = suggestions.map((question) => `
    <button class="suggestion-chip" type="button" data-fill-question="${esc(question)}">${esc(question)}</button>
  `).join('');
}

function renderMessages(options = {}) {
  const container = $('#chatMessages');
  if (!container) return;
  disposeCharts();
  if (!state.messages.length) {
    container.innerHTML = renderChatEmpty();
  } else {
    container.innerHTML = state.messages.map((message) => {
      if (message.role === 'user') return renderUserMessage(message);
      if (message.role === 'loading') return renderLoadingCard(message);
      if (message.role === 'error') return renderErrorCard(message);
      if (message.role === 'assistant' && message.result) return renderResultCard(message);
      return '';
    }).join('');
  }
  hydrateIcons(container);
  initCharts();
  const loadingMessage = state.messages.find((message) => message.role === 'loading');
  if (loadingMessage) startLoadingAnimation(loadingMessage.id);
  if (options.scroll) scrollToBottom(options.smooth);
}

function renderChatEmpty() {
  const sheet = activeSheet();
  const suggestions = (state.suggestions.length ? state.suggestions : [
    '近12个月销售额趋势如何？',
    '找出销售额异常波动的月份。',
    '对比各区域的利润并排名。',
  ]).slice(0, 4);
  return `
    <div class="chat-empty">
      <div class="empty-mark">${icon('sparkles', 23)}</div>
      <h3>从一句话开始分析</h3>
      <p>${sheet ? `已加载「${esc(sheet.name)}」${formatNumber(sheet.row_count, '', false)} 行数据，直接提问即可。` : '选择数据文件后开始提问。'}</p>
      <div class="empty-suggestions">
        ${suggestions.map((question) => `
          <button class="empty-suggestion" type="button" data-fill-question="${esc(question)}">
            <span>${esc(question)}</span>
            ${icon('arrowRight', 13)}
          </button>
        `).join('')}
      </div>
    </div>
  `;
}

function renderUserMessage(message) {
  return `<div class="user-message"><div class="user-bubble">${esc(message.text)}</div></div>`;
}

function renderLoadingCard(message) {
  return `
    <div class="loading-card" id="loading-${esc(message.id)}">
      <div class="loading-title">
        <span class="dot dot-green"></span>
        正在分析：${esc(message.question)}
        <span class="loading-dots"><i></i><i></i><i></i></span>
      </div>
      <div class="loading-steps">
        ${LOADING_STEPS.map((step, index) => `
          <div class="loading-step ${index === 0 ? 'active' : ''}" data-step="${index}">
            <i></i><span>${esc(step)}</span>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function renderErrorCard(message) {
  return `
    <div class="error-card">
      <div class="err-icon">${icon('alertCircle', 15)}</div>
      <div style="flex:1;min-width:0;">
        <h4>这次分析没有完成</h4>
        <p>${esc(message.text || '未知错误')}</p>
        <div class="error-actions">
          <button class="btn btn-secondary" type="button" data-action="retry" data-message-id="${esc(message.id)}">${icon('refresh', 13)} 重试</button>
          <button class="btn btn-ghost" type="button" data-action="dismiss" data-message-id="${esc(message.id)}">关闭</button>
        </div>
      </div>
    </div>
  `;
}

function intentClass(intent) {
  return ['trend', 'anomaly', 'compare', 'query'].includes(intent) ? intent : 'query';
}

function resultSubtitle(result) {
  const chart = result.chart || {};
  const categories = chart.categories || [];
  if (chart.type === 'line_anomaly') {
    return `${categories.length} 个周期 · ${(chart.anomalies || []).length} 个异常点`;
  }
  if (chart.type === 'bar') {
    return `展示前 ${categories.length} 组${chart.max_groups ? ` · 共 ${chart.max_groups} 组` : ''}`;
  }
  if (chart.type === 'line') return `${categories.length} 个数据点`;
  return '汇总结果';
}

function renderResultCard(message) {
  const result = message.result;
  const chart = result.chart || {};
  const table = result.table || {};
  const detail = result.detail || {};
  const method = result.method || {};
  const meta = result.meta || {};
  const warnings = meta.warnings || [];
  const metrics = result.metrics || [];
  const tableColumns = table.columns || [];
  const tableRows = table.rows || [];
  const chartId = `chart_${message.id}`;
  const hasChart = (chart.categories || []).length > 0;
  const sourceModel = meta.conclusion_source === 'model';
  const isFavorite = Boolean(favoriteForAnalysis(result.id));
  const filterText = (method.filters || []).map((item) => `${item.field} ${item.op} ${item.value}`).join('；');
  const displayMethod = [
    ['工作表', `${result.sheet ? result.sheet.name : ''} · ${formatNumber(method.rows || 0, '', false)} 行`],
    ['分析类型', result.intent_label || '分析'],
    ['指标口径', `${method.metric || result.metric || '记录数'} · ${method.aggregation || ''}`],
    ['时间口径', method.time_field ? `${method.time_field}${method.granularity ? `（按${method.granularity}）` : ''}` : (method.period || '全部数据')],
    ['对比维度', method.group_field || '—'],
    ['筛选条件', filterText || '无'],
  ];

  return `
    <article class="result-card" data-result-id="${esc(result.id)}" data-message-id="${esc(message.id)}">
      <div class="result-head">
        <span class="intent-badge ${intentClass(result.intent)}">${esc(result.intent_label || '分析')}</span>
        ${meta.follow_up ? '<span class="followup-tag">追问</span>' : ''}
        <span class="result-time">${formatDateTime(meta.created_at)}</span>
        <div class="result-tools">
          <button class="tool-btn favorite-btn ${isFavorite ? 'active' : ''}" type="button" data-action="favorite" data-message-id="${esc(message.id)}" title="${isFavorite ? '取消收藏' : '收藏这个分析'}" aria-label="${isFavorite ? '取消收藏' : '收藏这个分析'}">${icon('star', 14)}</button>
          <button class="tool-btn" type="button" data-action="report" data-message-id="${esc(message.id)}" title="下载 Markdown 报告" aria-label="下载 Markdown 报告">${icon('report', 14)}</button>
          <button class="tool-btn" type="button" data-action="report-html" data-message-id="${esc(message.id)}" title="打开打印版报告（可另存为 PDF）" aria-label="打开打印版报告">${icon('printer', 14)}</button>
          <button class="tool-btn" type="button" data-action="copy" data-message-id="${esc(message.id)}" title="复制结论" aria-label="复制结论">${icon('copy', 14)}</button>
          <button class="tool-btn" type="button" data-action="png" data-message-id="${esc(message.id)}" title="下载图表 PNG" aria-label="下载图表 PNG">${icon('image', 14)}</button>
          <button class="tool-btn" type="button" data-action="csv" data-message-id="${esc(message.id)}" title="导出明细 CSV" aria-label="导出明细 CSV">${icon('download', 14)}</button>
          <button class="tool-btn" type="button" data-action="regen" data-message-id="${esc(message.id)}" title="重新生成" aria-label="重新生成结论">${icon('refresh', 14)}</button>
        </div>
      </div>

      <h3 class="one-liner"><span class="quote-mark">“</span>${esc(result.one_liner || '分析完成')}</h3>

      <div class="metrics-grid">
        ${metrics.map((metric) => `
          <div class="metric-card ${esc(metric.tone || 'default')}">
            <div class="metric-label" title="${esc(metric.label)}">${esc(metric.label)}</div>
            <div class="metric-value" title="${esc(metric.display)}">${esc(metric.display)}</div>
            <div class="metric-hint" title="${esc(metric.hint || '')}">${esc(metric.hint || '')}</div>
          </div>
        `).join('')}
      </div>

      <div class="chart-panel">
        <div class="chart-head">
          <div>
            <h4>${esc(chart.title || '可视化结果')}</h4>
            <span>${esc(resultSubtitle(result))}${chart.unit ? ` · 单位 ${esc(chart.unit)}` : ''}</span>
          </div>
          <button class="mini-btn" type="button" data-action="png" data-message-id="${esc(message.id)}" ${hasChart ? '' : 'disabled'}>
            ${icon('download', 12)} 下载图表
          </button>
        </div>
        ${hasChart ? `<div class="chart-box" id="${chartId}" data-chart-id="${esc(message.id)}"></div>` : '<div class="chart-empty">本次查询没有生成图表</div>'}
      </div>

      <div class="insight-grid">
        <section class="insight-block">
          <h5>${icon('checkCircle', 12)} 数据事实</h5>
          <ul class="insight-list">
            ${(detail.facts || []).map((item) => `<li>${esc(item)}</li>`).join('') || '<li>暂无</li>'}
          </ul>
        </section>
        <section class="insight-block suggest">
          <h5>${icon('sparkles', 12)} 推测与建议</h5>
          <ul class="insight-list">
            ${(detail.inferences || []).map((item) => `<li>${esc(item)}</li>`).join('')}
          </ul>
          ${(detail.suggestions || []).length ? `
            <div class="insight-sub">下一步可以做什么</div>
            <ul class="insight-list">
              ${detail.suggestions.map((item) => `<li>${esc(item)}</li>`).join('')}
            </ul>
          ` : ''}
        </section>
      </div>

      ${warnings.length ? `
        <div class="warning-box">
          <b>提示：</b>${warnings.map((item) => esc(item)).join(' ')}
        </div>
      ` : ''}

      ${tableColumns.length ? `
        <details class="result-details" data-table-details>
          <summary>
            ${icon('table', 13)} 数据明细
            <span class="detail-count">${formatNumber(table.total_rows || tableRows.length, '', false)} 行</span>
            <span class="summary-spacer"></span>
            <span class="detail-count">展开查看</span>
          </summary>
          <div class="detail-body">
            <div class="detail-actions">
              <button class="link-btn" type="button" data-action="csv" data-message-id="${esc(message.id)}">${icon('download', 12)} 导出 CSV</button>
            </div>
            <div class="table-scroll">
              <table class="data-table">
                <thead><tr>${tableColumns.map((column) => `<th class="${column.type === 'number' || column.type === 'percent' ? 'num' : ''}">${esc(column.label)}</th>`).join('')}</tr></thead>
                <tbody>
                  ${tableRows.map((row) => `
                    <tr>${tableColumns.map((column) => {
                      const align = column.type === 'number' || column.type === 'percent' || column.type === 'rank' ? ' class="num"' : '';
                      return `<td${align}>${formatCell(row[column.key], column)}</td>`;
                    }).join('')}</tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
            ${table.truncated ? `<p class="modal-note">仅展示前 ${tableRows.length} 行，导出 CSV 可获取当前结果的全部 ${formatNumber(table.total_rows, '', false)} 行。</p>` : ''}
          </div>
        </details>
      ` : ''}

      <details class="result-details" data-method-details>
        <summary>
          ${icon('code', 13)} 分析口径与方法
          <span class="summary-spacer"></span>
          <span class="detail-count">可追溯</span>
        </summary>
        <div class="method-body">
          ${meta.plan_summary ? `<p class="modal-note" style="margin:0 0 11px;">${esc(meta.plan_summary)}</p>` : ''}
          <div class="method-grid">
            ${displayMethod.map(([key, value]) => `<div class="method-row"><span>${esc(key)}</span><b>${esc(value)}</b></div>`).join('')}
          </div>
          ${(meta.fields_with_notes || []).length ? `
            <div class="field-notes">
              <span class="field-notes-label">字段备注</span>
              ${meta.fields_with_notes.map((item) => `<span class="field-note"><b>${esc(item.name)}</b>${esc(item.note)}</span>`).join('')}
            </div>
          ` : ''}
          <ul class="method-notes">${(method.notes || []).map((note) => `<li>${esc(note)}</li>`).join('')}</ul>
          ${method.sql ? `
            <div class="sql-head">
              <span>只读查询（DuckDB）</span>
              <button class="link-btn" type="button" data-action="copy-sql" data-message-id="${esc(message.id)}">${icon('copy', 11)} 复制 SQL</button>
            </div>
            <pre class="sql-block">${esc(method.sql)}</pre>
          ` : ''}
        </div>
      </details>

      <div class="result-foot">
        <span class="source-${sourceModel ? 'model' : 'rules'}">
          <span class="dot ${sourceModel ? 'dot-green' : 'dot-amber'}"></span>
          ${sourceModel ? `结论由 ${esc(meta.model_used || '大模型')} 生成` : '结论由本地规则引擎生成'}
        </span>
        <span>${icon('clock', 10)} 耗时 ${formatNumber(meta.elapsed_ms || 0, '', false)} ms · 数字来自本地查询</span>
      </div>
    </article>
  `;
}

/* =========================================================
   图表
   ========================================================= */
function disposeCharts() {
  state.charts.forEach((chart) => {
    try { chart.dispose(); } catch (error) { /* noop */ }
  });
  state.charts.clear();
}

function initCharts() {
  $$('[data-chart-id]').forEach((element) => {
    const messageId = element.dataset.chartId;
    const message = state.messages.find((item) => item.id === messageId);
    if (!message || !message.result) return;
    try {
      const chart = echarts.init(element, null, { renderer: 'canvas' });
      chart.setOption(buildChartOption(message.result.chart || {}), true);
      state.charts.set(messageId, chart);
    } catch (error) {
      console.warn('chart init failed', error);
      element.innerHTML = '<div class="chart-empty">图表渲染失败</div>';
    }
  });
}

function buildChartOption(chart) {
  const categories = chart.categories || [];
  const series = chart.series || [];
  const values = (series[0] && series[0].data) || [];
  const unit = chart.unit || '';
  const isPercent = chart.value_format === 'percent';
  const valueLabel = isPercent ? (value) => formatPercent(value, 1) : (value) => formatNumber(value, unit);
  const axisLabel = isPercent ? (value) => `${(value * 100).toFixed(0)}%` : (value) => formatNumber(value, '', true);
  const color = '#4f46e5';
  const tooltip = {
    backgroundColor: 'rgba(16,24,40,.94)',
    borderWidth: 0,
    textStyle: { color: '#fff', fontSize: 11 },
    padding: [8, 10],
    formatter(params) {
      const item = Array.isArray(params) ? params[0] : params;
      return `${esc(item.name)}<br/>${item.marker || ''} ${esc(chart.metric || '数值')}：<b>${esc(valueLabel(item.value))}</b>`;
    },
  };

  if (chart.type === 'bar') {
    return {
      animationDuration: 450,
      grid: { left: 8, right: 76, top: 12, bottom: 8, containLabel: true },
      tooltip,
      xAxis: {
        type: 'value',
        axisLabel: { color: '#98a2b3', fontSize: 9, formatter: axisLabel },
        splitLine: { lineStyle: { color: '#f0f2f6', type: 'dashed' } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: categories,
        inverse: true,
        axisLabel: { color: '#475467', fontSize: 10, width: 96, overflow: 'truncate' },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: values,
        barMaxWidth: 20,
        itemStyle: {
          borderRadius: [0, 5, 5, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#8b83f4' },
            { offset: 1, color: color },
          ]),
        },
        label: {
          show: categories.length <= 10,
          position: 'right',
          color: '#667085',
          fontSize: 9,
          formatter: (params) => valueLabel(params.value),
        },
        emphasis: { itemStyle: { color: '#4338ca' } },
      }],
    };
  }

  const anomalyPoints = (chart.anomalies || []).map((item) => ({
    name: item.label,
    coord: [item.label, item.value],
    value: item.value,
    symbolSize: 42,
    itemStyle: { color: '#f04438' },
    label: { formatter: '异常', fontSize: 9, color: '#fff', fontWeight: 600 },
  }));

  return {
    animationDuration: 450,
    grid: { left: 8, right: 18, top: 22, bottom: 8, containLabel: true },
    tooltip,
    dataZoom: categories.length > 18 ? [{ type: 'inside', throttle: 60 }] : [],
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: false,
      axisLabel: {
        color: '#98a2b3',
        fontSize: 9,
        hideOverlap: true,
        interval: categories.length > 16 ? 'auto' : 0,
      },
      axisLine: { lineStyle: { color: '#eaecf0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#98a2b3', fontSize: 9, formatter: axisLabel },
      splitLine: { lineStyle: { color: '#f0f2f6', type: 'dashed' } },
    },
    series: [{
      name: chart.metric || '数值',
      type: 'line',
      data: values,
      smooth: 0.22,
      symbol: 'circle',
      symbolSize: categories.length > 30 ? 3 : 5,
      showSymbol: categories.length <= 30,
      lineStyle: { width: 2.4, color },
      itemStyle: { color, borderColor: '#fff', borderWidth: 1.5 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(79,70,229,.22)' },
          { offset: 1, color: 'rgba(79,70,229,.015)' },
        ]),
      },
      markPoint: anomalyPoints.length ? {
        symbol: 'pin',
        symbolOffset: [0, -6],
        data: anomalyPoints,
        tooltip: {
          formatter: (params) => `${esc(params.name)}<br/>${esc(chart.metric || '数值')}：<b>${esc(valueLabel(params.value))}</b>`,
        },
      } : undefined,
    }],
  };
}

/* =========================================================
   分析流程
   ========================================================= */
function nextMessageId() {
  state.messageSeq += 1;
  return `msg_${Date.now().toString(36)}_${state.messageSeq}`;
}

function scrollToBottom(smooth = false) {
  const scroller = $('#mainScroll');
  if (!scroller) return;
  requestAnimationFrame(() => {
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  });
}

function startLoadingAnimation(messageId) {
  if (state.loading && state.loading.messageId === messageId) return;
  stopLoadingAnimation();
  const steps = $$(`#loading-${CSS.escape(messageId)} .loading-step`);
  if (!steps.length) return;
  let index = 0;
  steps.forEach((step, stepIndex) => {
    step.classList.toggle('active', stepIndex === 0);
    step.classList.remove('done');
  });
  const timer = window.setInterval(() => {
    if (index > 0) {
      const previous = steps[index - 1];
      if (previous) { previous.classList.remove('active'); previous.classList.add('done'); }
    }
    index = Math.min(index + 1, steps.length - 1);
    const current = steps[index];
    if (current) current.classList.add('active');
  }, 1150);
  state.loading = { messageId, timer };
}

function stopLoadingAnimation() {
  if (state.loading && state.loading.timer) window.clearInterval(state.loading.timer);
  state.loading = null;
}

async function submitQuestion(rawQuestion, options = {}) {
  const question = String(rawQuestion || '').trim();
  if (!question || state.busy || !state.activeFile) return;
  if (question.length > 500) {
    toast('问题请控制在 500 字以内', 'error');
    return;
  }
  const fileId = options.fileId || state.activeFile.id;
  const sheetId = options.sheetId || state.activeSheetId;
  const previous = state.lastResult;
  const context = !options.replaceMessageId
    && previous
    && previous.meta
    && previous.meta.plan
    && previous.file
    && previous.file.id === fileId
    && previous.sheet
    && previous.sheet.id === sheetId
    ? previous.meta.plan
    : null;

  state.busy = true;
  updateComposer();
  const input = $('#questionInput');
  if (input) input.value = '';
  autoresizeInput();

  let targetId = options.replaceMessageId || null;
  if (targetId) {
    const existing = state.messages.find((message) => message.id === targetId);
    if (existing) {
      existing.role = 'loading';
      existing.question = question;
      existing.result = null;
    }
  } else {
    const userMessage = { id: nextMessageId(), role: 'user', text: question };
    const loadingMessage = { id: nextMessageId(), role: 'loading', question };
    state.messages.push(userMessage, loadingMessage);
    targetId = loadingMessage.id;
  }
  renderMessages({ scroll: true });

  try {
    const result = await api('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({ file_id: fileId, sheet_id: sheetId, question, context }),
    });
    const message = state.messages.find((item) => item.id === targetId);
    if (message) {
      message.role = 'assistant';
      message.result = result;
      message.question = result.question;
    }
    state.lastResult = result;
    state.activeSheetId = result.sheet ? result.sheet.id : state.activeSheetId;
    toast('分析完成', 'success');
    await refreshAnalyses();
  } catch (error) {
    const message = state.messages.find((item) => item.id === targetId);
    if (message) {
      message.role = 'error';
      message.text = error.message || '分析失败，请重试。';
      message.question = question;
      message.fileId = fileId;
      message.sheetId = sheetId;
    }
    toast(error.message || '分析失败', 'error');
  } finally {
    state.busy = false;
    stopLoadingAnimation();
    updateComposer();
    renderMessages({ scroll: true });
  }
}

async function regenerateMessage(messageId) {
  if (state.busy) return;
  const message = state.messages.find((item) => item.id === messageId);
  if (!message || !message.result) return;
  const result = message.result;
  await submitQuestion(result.question, {
    replaceMessageId: messageId,
    fileId: result.file.id,
    sheetId: result.sheet.id,
  });
}

function updateComposer() {
  const sendBtn = $('#sendBtn');
  const input = $('#questionInput');
  if (sendBtn) sendBtn.disabled = state.busy || !state.activeFile;
  if (input) {
    input.disabled = !state.activeFile;
    input.placeholder = state.activeFile ? '例如：近12个月销售额趋势如何？' : '请先选择数据文件';
  }
  const hint = $('#aiHint');
  if (hint && state.settings) {
    hint.textContent = state.settings.ai_configured ? `AI 已连接 · ${state.settings.model || '模型'}` : '规则模式 · 未配置模型';
    hint.classList.toggle('ready', Boolean(state.settings.ai_configured));
  }
}

async function loadAnalysis(analysisId, options = {}) {
  if (state.busy) {
    toast('请等待当前分析完成', 'info');
    return;
  }
  try {
    const result = await api(`/api/analyses/${analysisId}`);
    if (!state.activeFile || state.activeFile.id !== result.file.id) {
      await openFile(result.file.id, { loadLatest: false, sheetId: result.sheet.id });
    }
    if (!state.activeFile) return;
    state.activeSheetId = result.sheet.id;
    await loadPreview(result.sheet.id);
    state.messages = [
      { id: nextMessageId(), role: 'user', text: result.question },
      { id: nextMessageId(), role: 'assistant', result },
    ];
    state.lastResult = result;
    showWorkspace();
    renderOverview();
    renderBreadcrumbSafe();
    renderMessages({ scroll: true });
    renderSuggestions();
    updateComposer();
    localStorage.setItem(STORAGE.activeFile, result.file.id);
    localStorage.setItem(STORAGE.sheetPrefix + result.file.id, result.sheet.id);
  } catch (error) {
    toast(error.message || '加载历史分析失败', 'error');
  }
}

/* =========================================================
   结果操作
   ========================================================= */
function resultToText(result) {
  const detail = result.detail || {};
  const lines = [result.one_liner || ''];
  if (detail.facts && detail.facts.length) {
    lines.push('', '数据事实：');
    detail.facts.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
  }
  if (detail.inferences && detail.inferences.length) {
    lines.push('', '推测与解读：');
    detail.inferences.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
  }
  if (detail.suggestions && detail.suggestions.length) {
    lines.push('', '下一步建议：');
    detail.suggestions.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
  }
  if (result.method && result.method.sql) {
    lines.push('', '分析口径（SQL）：', result.method.sql);
  }
  lines.push('', '—— 由析数 · 数据分析 Agent 生成，数字来自本地只读查询。');
  return lines.join('\n');
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(textarea);
    return ok;
  }
}

function downloadDataUrl(url, filename) {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function safeFilename(name) {
  return String(name || 'chart').replace(/[\\/:*?"<>|]/g, '_').slice(0, 60);
}

async function downloadCsv(result) {
  if (!result || !result.id) return;
  try {
    const response = await fetch(`/api/analyses/${result.id}/export.csv`, {
      headers: { 'X-Session-Id': state.sessionId },
    });
    if (!response.ok) {
      const text = await response.text();
      let data = null;
      try { data = JSON.parse(text); } catch { data = null; }
      throw new ApiError(errorMessage(data, response.status), response.status);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    downloadDataUrl(url, `分析结果_${new Date().toISOString().slice(0, 10)}.csv`);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    toast('CSV 已导出', 'success');
  } catch (error) {
    toast(error.message || '导出失败', 'error');
  }
}

async function toggleFavorite(result) {
  if (!result || !result.id) return;
  const existing = favoriteForAnalysis(result.id);
  try {
    if (existing) {
      await api(`/api/favorites/${existing.id}`, { method: 'DELETE' });
      state.favorites = state.favorites.filter((item) => item.id !== existing.id);
      toast('已取消收藏', 'success');
    } else {
      const data = await api('/api/favorites', {
        method: 'POST',
        body: JSON.stringify({ analysis_id: result.id }),
      });
      state.favorites = [data.favorite, ...state.favorites];
      await refreshFavorites();
      toast('已收藏，可在左侧「我的收藏」查看', 'success');
    }
    renderSidebar();
    renderMessages();
  } catch (error) {
    toast(error.message || '收藏操作失败', 'error');
  }
}

async function fetchReport(analysisId, kind) {
  const response = await fetch(`/api/analyses/${analysisId}/export.${kind}`, {
    headers: { 'X-Session-Id': state.sessionId },
  });
  if (!response.ok) {
    const text = await response.text();
    let data = null;
    try { data = JSON.parse(text); } catch { data = null; }
    throw new ApiError(errorMessage(data, response.status), response.status);
  }
  return response;
}

async function downloadReport(result, kind = 'md') {
  if (!result || !result.id) return;
  try {
    const response = await fetchReport(result.id, kind);
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const fallback = `分析报告_${new Date().toISOString().slice(0, 10)}.${kind}`;
    const filename = match ? decodeURIComponent(match[1]) : fallback;
    const url = URL.createObjectURL(blob);
    downloadDataUrl(url, filename);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    toast('报告已下载', 'success');
  } catch (error) {
    toast(error.message || '报告导出失败', 'error');
  }
}

async function openPrintableReport(result) {
  if (!result || !result.id) return;
  const win = window.open('', '_blank');
  try {
    const response = await fetchReport(result.id, 'html');
    const text = await response.text();
    if (win) {
      win.document.open();
      win.document.write(text);
      win.document.close();
    } else {
      const blob = new Blob([text], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
  } catch (error) {
    if (win) win.close();
    toast(error.message || '打印版报告打开失败', 'error');
  }
}

/* =========================================================
   字段备注 / 收藏 / 报告
   ========================================================= */
function openColumnNoteModal(columnName) {
  const sheet = activeSheet();
  const file = state.activeFile;
  if (!sheet || !file) return;
  const column = (sheet.columns || []).find((item) => item.name === columnName);
  if (!column) return;
  openModal(`
    <div class="modal-head">
      <div>
        <h3>字段备注 · ${esc(columnName)}</h3>
        <p>写清业务含义或常用别名，提问时可以直接使用这些说法。</p>
      </div>
      <button class="modal-close" type="button" data-modal-close aria-label="关闭">${icon('close', 15)}</button>
    </div>
    <div class="modal-body">
      <div class="note-field">
        <label for="columnNoteInput">业务备注</label>
        <textarea class="note-input" id="columnNoteInput" maxlength="200" placeholder="例如：毛利口径，不含运费；也常被称为「毛利」">${esc(column.note || '')}</textarea>
        <p class="modal-note">备注会参与问题理解：提到备注里的词也能匹配到这个字段。留空保存即删除备注，最多 200 字。</p>
      </div>
      <div class="modal-actions">
        <button class="btn btn-secondary" type="button" data-modal-close>取消</button>
        <button class="btn btn-primary" type="button" id="saveColumnNote">${icon('check', 13)} 保存备注</button>
      </div>
    </div>
  `);
  const input = $('#columnNoteInput');
  if (input) {
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
  const saveButton = $('#saveColumnNote');
  if (saveButton) {
    saveButton.addEventListener('click', async () => {
      saveButton.disabled = true;
      saveButton.textContent = '保存中…';
      try {
        const note = input ? input.value.trim() : '';
        const data = await api(
          `/api/files/${file.id}/sheets/${sheet.id}/columns/${encodeURIComponent(columnName)}`,
          { method: 'PUT', body: JSON.stringify({ note }) },
        );
        const targetSheet = activeSheet();
        const target = targetSheet && (targetSheet.columns || []).find((item) => item.name === columnName);
        if (target) {
          if (data.note) target.note = data.note;
          else delete target.note;
        }
        closeModal();
        renderOverview();
        toast(data.note ? '字段备注已保存' : '字段备注已删除', 'success');
      } catch (error) {
        toast(error.message || '备注保存失败', 'error');
        saveButton.disabled = false;
        saveButton.textContent = '保存备注';
      }
    });
  }
}

function favoriteById(favoriteId) {
  return state.favorites.find((item) => item.id === favoriteId) || null;
}

async function rerunFavorite(favoriteId) {
  try {
    toast('正在重新分析…', 'info');
    const result = await api(`/api/favorites/${favoriteId}/rerun`, { method: 'POST' });
    await refreshFavorites();
    await loadAnalysis(result.id);
    toast('收藏已重新分析', 'success');
  } catch (error) {
    toast(error.message || '重跑失败', 'error');
  }
}

function openFavorite(favoriteId) {
  const favorite = favoriteById(favoriteId);
  if (!favorite) {
    toast('收藏不存在，可能已被删除', 'error');
    return;
  }
  if (favorite.analysis_id) loadAnalysis(favorite.analysis_id);
  else rerunFavorite(favorite.id);
}

function openRenameFavorite(favorite) {
  openModal(`
    <div class="modal-head">
      <div>
        <h3>重命名收藏</h3>
        <p>名称只影响侧边栏和收藏面板中的显示，不会改变分析问题。</p>
      </div>
      <button class="modal-close" type="button" data-modal-close aria-label="关闭">${icon('close', 15)}</button>
    </div>
    <div class="modal-body">
      <div class="note-field">
        <label for="favoriteTitleInput">收藏名称</label>
        <input class="note-input text-input" id="favoriteTitleInput" maxlength="80" value="${esc(favorite.title)}">
        <p class="modal-note">最多 80 字。</p>
      </div>
      <div class="modal-actions">
        <button class="btn btn-secondary" type="button" data-modal-close>取消</button>
        <button class="btn btn-primary" type="button" id="saveFavoriteTitle">保存</button>
      </div>
    </div>
  `);
  const input = $('#favoriteTitleInput');
  if (input) {
    input.focus();
    input.select();
  }
  const saveButton = $('#saveFavoriteTitle');
  if (saveButton) {
    saveButton.addEventListener('click', async () => {
      const title = input ? input.value.trim() : '';
      if (!title) {
        toast('收藏名称不能为空', 'error');
        return;
      }
      saveButton.disabled = true;
      try {
        await api(`/api/favorites/${favorite.id}`, { method: 'PATCH', body: JSON.stringify({ title }) });
        await refreshFavorites();
        openFavoritesPanel();
        toast('已重命名', 'success');
      } catch (error) {
        toast(error.message || '重命名失败', 'error');
        saveButton.disabled = false;
      }
    });
  }
}

function openFavoritesPanel() {
  const items = state.favorites;
  openModal(`
    <div class="modal-head">
      <div>
        <h3>我的收藏</h3>
        <p>保存下来的分析快照，可随时查看、重命名或重跑最新数据。</p>
      </div>
      <button class="modal-close" type="button" data-modal-close aria-label="关闭">${icon('close', 15)}</button>
    </div>
    <div class="modal-body">
      ${items.length ? `
        <div class="favorites-grid" data-favorites-grid>
          ${items.map((item) => `
            <article class="favorite-card">
              <div class="favorite-card-head">
                <b title="${esc(item.title)}">${esc(item.title)}</b>
                <span>${timeAgo(item.updated_at || item.created_at)}</span>
              </div>
              <p class="favorite-question" title="${esc(item.question)}">${esc(item.question)}</p>
              <p class="favorite-liner">${esc(item.one_liner || '暂无结论摘要')}</p>
              <div class="favorite-meta">${esc(item.file_name || '本地数据')} · ${esc(item.sheet_name || '')}</div>
              <div class="favorite-actions">
                <button class="btn btn-secondary btn-sm" type="button" data-fav-open="${esc(item.id)}">查看</button>
                <button class="btn btn-secondary btn-sm" type="button" data-fav-rerun="${esc(item.id)}">${icon('refresh', 12)} 重跑</button>
                <button class="btn btn-ghost btn-sm" type="button" data-fav-rename="${esc(item.id)}">重命名</button>
                <button class="btn btn-ghost btn-sm danger-text" type="button" data-fav-delete="${esc(item.id)}">删除</button>
              </div>
            </article>
          `).join('')}
        </div>
      ` : `
        <div class="favorites-empty">
          ${icon('star', 26)}
          <h4>还没有收藏</h4>
          <p>在任意分析结果右上角点击星标，就会出现在这里。</p>
        </div>
      `}
    </div>
  `, { wide: true });

  const grid = $('[data-favorites-grid]');
  if (!grid) return;
  grid.addEventListener('click', async (event) => {
    const openButton = event.target.closest('[data-fav-open]');
    if (openButton) {
      closeModal();
      openFavorite(openButton.dataset.favOpen);
      return;
    }
    const rerunButton = event.target.closest('[data-fav-rerun]');
    if (rerunButton) {
      closeModal();
      rerunFavorite(rerunButton.dataset.favRerun);
      return;
    }
    const renameButton = event.target.closest('[data-fav-rename]');
    if (renameButton) {
      const favorite = favoriteById(renameButton.dataset.favRename);
      if (favorite) openRenameFavorite(favorite);
      return;
    }
    const deleteButton = event.target.closest('[data-fav-delete]');
    if (deleteButton) {
      const favorite = favoriteById(deleteButton.dataset.favDelete);
      if (!favorite) return;
      confirmDialog({
        title: '删除这条收藏？',
        message: `将删除收藏「${favorite.title}」。原始数据与历史分析不受影响。`,
        confirmText: '删除收藏',
        danger: true,
        onConfirm: async () => {
          await api(`/api/favorites/${favorite.id}`, { method: 'DELETE' });
          await refreshFavorites();
          toast('收藏已删除', 'success');
        },
      });
    }
  });
}

function handleAction(action, messageId) {
  const message = state.messages.find((item) => item.id === messageId);
  const result = message && message.result;
  if (!action) return;
  if (action === 'copy' && result) {
    copyText(resultToText(result)).then((ok) => toast(ok ? '结论已复制' : '复制失败，请手动选择', ok ? 'success' : 'error'));
    return;
  }
  if (action === 'png' && messageId) {
    const chart = state.charts.get(messageId);
    if (!chart) { toast('图表尚未渲染完成', 'info'); return; }
    const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
    downloadDataUrl(url, `${safeFilename(result && result.chart ? result.chart.title : '图表')}.png`);
    toast('图表已下载', 'success');
    return;
  }
  if (action === 'csv' && result) {
    downloadCsv(result);
    return;
  }
  if (action === 'regen' && messageId) {
    regenerateMessage(messageId);
    return;
  }
  if (action === 'favorite' && result) {
    toggleFavorite(result);
    return;
  }
  if (action === 'report' && result) {
    downloadReport(result, 'md');
    return;
  }
  if (action === 'report-html' && result) {
    openPrintableReport(result);
    return;
  }
  if (action === 'copy-sql' && result && result.method && result.method.sql) {
    copyText(result.method.sql).then((ok) => toast(ok ? 'SQL 已复制' : '复制失败', ok ? 'success' : 'error'));
    return;
  }
  if (action === 'retry') {
    const target = state.messages.find((item) => item.id === messageId);
    if (!target) return;
    const question = target.question;
    const fileId = target.fileId || (state.activeFile && state.activeFile.id);
    const sheetId = target.sheetId || state.activeSheetId;
    const index = state.messages.findIndex((item) => item.id === messageId);
    if (index >= 0) state.messages.splice(index, 1);
    if (fileId) submitQuestion(question, { fileId, sheetId });
    return;
  }
  if (action === 'dismiss') {
    state.messages = state.messages.filter((item) => item.id !== messageId);
    renderMessages();
  }
}

/* =========================================================
   设置 / 清除数据
   ========================================================= */
function openSettings() {
  const settings = state.settings || {};
  const configured = Boolean(settings.ai_configured);
  const envSnippet = [
    'OPENAI_API_KEY=sk-your-key',
    'OPENAI_BASE_URL=https://api.openai.com/v1',
    'OPENAI_MODEL=gpt-4o-mini',
  ].join('\n');
  openModal(`
    <div class="modal-head">
      <div>
        <h3>模型与数据设置</h3>
        <p>API Key 仅在服务端环境变量中读取，不会下发到浏览器。</p>
      </div>
      <button class="modal-close" type="button" data-modal-close aria-label="关闭">${icon('close', 15)}</button>
    </div>
    <div class="modal-body">
      <div class="modal-section">
        <h4>大模型连接</h4>
        <div class="status-banner ${configured ? 'ok' : ''}">
          <span class="dot ${configured ? 'dot-green' : 'dot-amber'}"></span>
          <span>${configured
            ? `已连接 OpenAI 兼容接口：<b>${esc(settings.model || '')}</b>（${esc(settings.endpoint_host || '')}）。规划与结论生成会调用模型；查询与数字始终在本地完成。`
            : '当前未配置大模型，系统使用本地规则引擎完成问题规划和结论撰写。数据概览、图表与所有数字不受影响。'}</span>
        </div>
        <div class="setting-row"><span class="setting-key">当前模型</span><span class="setting-val">${esc(settings.model || '规则引擎')}</span></div>
        <div class="setting-row"><span class="setting-key">接口地址</span><span class="setting-val">${esc(settings.endpoint_host || '未配置')}</span></div>
        <p class="modal-note">在项目根目录创建 <code>.env</code>（可参考 <code>.env.example</code>），填写以下变量后重启服务：</p>
        <pre class="code-snippet">${envSnippet.split('\n').map((line) => {
          const [key, ...rest] = line.split('=');
          return `<span class="c-key">${esc(key)}</span>=<span class="c-val">${esc(rest.join('='))}</span>`;
        }).join('\n')}</pre>
        <div class="modal-actions" style="justify-content:flex-start;margin-top:10px;">
          <button class="btn btn-secondary" type="button" data-copy-env>${icon('copy', 13)} 复制配置模板</button>
        </div>
      </div>

      <div class="modal-section">
        <h4>本地存储与边界</h4>
        <div class="setting-row"><span class="setting-key">数据目录</span><span class="setting-val">${esc(settings.storage_dir || 'data/')}</span></div>
        <div class="setting-row"><span class="setting-key">上传限制</span><span class="setting-val">${esc(settings.max_upload_mb || 50)} MB / 文件 · 建议 ≤ 10 万行</span></div>
        <div class="setting-row"><span class="setting-key">执行方式</span><span class="setting-val">DuckDB 只读查询 · 仅访问当前工作表</span></div>
        <p class="modal-note">${esc(settings.privacy || '文件与分析历史仅保存在本机。')}</p>
      </div>

      <div class="modal-section danger-zone">
        <h4>清空本地数据</h4>
        <p>删除当前会话上传的所有文件、解析结果与分析历史，操作不可恢复。</p>
        <button class="btn btn-danger" type="button" data-clear-data>${icon('trash', 13)} 清空本地数据</button>
      </div>
    </div>
  `, { wide: true });
  const copyButton = $('[data-copy-env]');
  if (copyButton) {
    copyButton.addEventListener('click', async () => {
      const ok = await copyText(envSnippet);
      toast(ok ? '配置模板已复制' : '复制失败', ok ? 'success' : 'error');
    });
  }
  const clearButton = $('[data-clear-data]');
  if (clearButton) clearButton.addEventListener('click', () => {
    closeModal();
    confirmDialog({
      title: '确认清空本地数据？',
      message: '将删除当前会话的全部文件、Parquet 解析结果与分析历史。该操作不可恢复。',
      confirmText: '确认清空',
      danger: true,
      onConfirm: clearAllData,
    });
  });
}

async function clearAllData() {
  try {
    await api('/api/data', { method: 'DELETE' });
    state.files = [];
    state.analyses = [];
    state.favorites = [];
    state.activeFile = null;
    state.activeSheetId = null;
    state.preview = null;
    state.messages = [];
    state.lastResult = null;
    state.suggestions = [];
    localStorage.removeItem(STORAGE.activeFile);
    Object.keys(localStorage).filter((key) => key.startsWith(STORAGE.sheetPrefix)).forEach((key) => localStorage.removeItem(key));
    renderSidebar();
    renderRecent();
    showLanding();
    toast('本地数据已清空', 'success');
  } catch (error) {
    toast(error.message || '清空失败', 'error');
  }
}

/* =========================================================
   删除文件
   ========================================================= */
function requestDeleteFile(fileId) {
  const file = state.files.find((item) => item.id === fileId);
  if (!file) return;
  confirmDialog({
    title: '删除这个数据文件？',
    message: `「${file.name}」的原始文件、解析结果以及相关分析历史都会被删除，操作不可恢复。`,
    confirmText: '删除文件',
    danger: true,
    onConfirm: async () => {
      try {
        await api(`/api/files/${fileId}`, { method: 'DELETE' });
        state.files = state.files.filter((item) => item.id !== fileId);
        state.analyses = state.analyses.filter((item) => item.file_id !== fileId);
        state.favorites = state.favorites.filter((item) => item.file_id !== fileId);
        localStorage.removeItem(STORAGE.sheetPrefix + fileId);
        if (state.activeFile && state.activeFile.id === fileId) {
          state.activeFile = null;
          state.messages = [];
          state.lastResult = null;
          localStorage.removeItem(STORAGE.activeFile);
          showLanding();
        }
        renderSidebar();
        renderRecent();
        toast('文件已删除', 'success');
      } catch (error) {
        toast(error.message || '删除失败', 'error');
      }
    },
  });
}

/* =========================================================
   弹窗 / Toast
   ========================================================= */
function openModal(html, options = {}) {
  const root = $('#modalRoot');
  root.innerHTML = `
    <div class="modal-overlay" data-modal-overlay>
      <div class="modal-card ${options.wide ? 'wide' : ''}" role="dialog" aria-modal="true">
        ${html}
      </div>
    </div>
  `;
  document.body.classList.add('modal-open');
  const overlay = $('[data-modal-overlay]');
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) closeModal();
  });
  $$('[data-modal-close]', root).forEach((button) => button.addEventListener('click', closeModal));
  const first = root.querySelector('button, input, textarea');
  if (first) first.focus({ preventScroll: true });
}

function closeModal() {
  $('#modalRoot').innerHTML = '';
  document.body.classList.remove('modal-open');
}

function confirmDialog({ title, message, confirmText = '确认', danger = false, onConfirm }) {
  openModal(`
    <div class="modal-head">
      <div>
        <h3>${esc(title)}</h3>
        <p>请确认操作</p>
      </div>
      <button class="modal-close" type="button" data-modal-close aria-label="关闭">${icon('close', 15)}</button>
    </div>
    <div class="modal-body">
      <p class="modal-note" style="font-size:12px;margin-top:0;">${esc(message)}</p>
      <div class="modal-actions" style="margin-top:18px;">
        <button class="btn btn-secondary" type="button" data-modal-close>取消</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" type="button" data-confirm>${esc(confirmText)}</button>
      </div>
    </div>
  `);
  const confirmButton = $('[data-confirm]');
  if (confirmButton) {
    confirmButton.addEventListener('click', async () => {
      confirmButton.disabled = true;
      confirmButton.textContent = '处理中…';
      try {
        await onConfirm();
        closeModal();
      } catch (error) {
        toast(error.message || '操作失败', 'error');
        confirmButton.disabled = false;
        confirmButton.textContent = confirmText;
      }
    });
  }
}

function toast(message, type = 'info') {
  const stack = $('#toastStack');
  if (!stack) return;
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.innerHTML = `${icon(type === 'success' ? 'checkCircle' : type === 'error' ? 'alertCircle' : 'info', 15)}<span>${esc(message)}</span>`;
  stack.appendChild(node);
  setTimeout(() => {
    node.style.opacity = '0';
    node.style.transform = 'translateY(6px)';
    node.style.transition = 'opacity .2s ease, transform .2s ease';
    setTimeout(() => node.remove(), 220);
  }, type === 'error' ? 5200 : 3200);
}

/* =========================================================
   模型状态 / 输入
   ========================================================= */
function updateModelUI() {
  const settings = state.settings || {};
  const pill = $('#modelPill');
  const text = $('#modelText');
  const dot = $('#modelDot');
  if (!pill || !text || !dot) return;
  if (settings.ai_configured) {
    pill.classList.add('configured');
    dot.className = 'dot dot-green';
    text.textContent = `AI 已连接 · ${settings.model || '模型'}`;
  } else {
    pill.classList.remove('configured');
    dot.className = 'dot dot-amber';
    text.textContent = '规则模式 · 未配置模型';
  }
  updateComposer();
}

function autoresizeInput() {
  const input = $('#questionInput');
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
}

function fillQuestion(question) {
  const input = $('#questionInput');
  if (!input || state.busy) return;
  input.value = question;
  input.focus();
  autoresizeInput();
}

/* =========================================================
   事件绑定
   ========================================================= */
function bindEvents() {
  $('#newAnalysisBtn').addEventListener('click', goLanding);
  $('#heroUploadBtn').addEventListener('click', () => $('#fileInput').click());
  $('#fileInput').addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadFile(file);
    event.target.value = '';
  });

  const dropzone = $('#dropzone');
  dropzone.addEventListener('click', () => {
    if (!state.uploading) $('#fileInput').click();
  });
  dropzone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!state.uploading) $('#fileInput').click();
    }
  });
  ['dragenter', 'dragover'].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.add('dragging');
    });
  });
  ['dragleave', 'drop'].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.remove('dragging');
    });
  });
  dropzone.addEventListener('drop', (event) => {
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
  window.addEventListener('dragover', (event) => event.preventDefault());
  window.addEventListener('drop', (event) => event.preventDefault());

  $('#settingsBtn').addEventListener('click', openSettings);
  $('#settingsBtnTop').addEventListener('click', openSettings);
  $('#modelPill').addEventListener('click', openSettings);
  $('#privacyBtn').addEventListener('click', openSettings);

  const menuBtn = $('#menuBtn');
  const sidebar = $('#sidebar');
  const backdrop = $('#sidebarBackdrop');
  menuBtn.addEventListener('click', () => {
    sidebar.classList.add('open');
    backdrop.hidden = false;
  });
  backdrop.addEventListener('click', closeSidebar);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeSidebar();
      if ($('#modalRoot').innerHTML) closeModal();
    }
  });

  $('#fileList').addEventListener('click', (event) => {
    const deleteButton = event.target.closest('[data-delete-file]');
    if (deleteButton) {
      event.preventDefault();
      event.stopPropagation();
      requestDeleteFile(deleteButton.dataset.deleteFile);
      return;
    }
    const item = event.target.closest('[data-file-id]');
    if (item) {
      closeSidebar();
      openFile(item.dataset.fileId, { loadLatest: true });
    }
  });

  $('#historyList').addEventListener('click', (event) => {
    const item = event.target.closest('[data-analysis-id]');
    if (item) {
      closeSidebar();
      loadAnalysis(item.dataset.analysisId);
    }
  });

  $('#favoriteList').addEventListener('click', (event) => {
    const rerunButton = event.target.closest('[data-rerun-favorite]');
    if (rerunButton) {
      event.preventDefault();
      event.stopPropagation();
      closeSidebar();
      rerunFavorite(rerunButton.dataset.rerunFavorite);
      return;
    }
    const item = event.target.closest('[data-favorite-id]');
    if (item) {
      closeSidebar();
      openFavorite(item.dataset.favoriteId);
    }
  });

  const favoritesPanelBtn = $('#favoritesPanelBtn');
  if (favoritesPanelBtn) favoritesPanelBtn.addEventListener('click', openFavoritesPanel);

  $('#recentFiles').addEventListener('click', (event) => {
    const item = event.target.closest('[data-recent-file]');
    if (item) openFile(item.dataset.recentFile, { loadLatest: true });
  });

  $('#dataOverview').addEventListener('click', (event) => {
    const noteNode = event.target.closest('[data-note-column]');
    if (noteNode) {
      openColumnNoteModal(noteNode.dataset.noteColumn);
      return;
    }
    const actionNode = event.target.closest('[data-overview]');
    if (actionNode) {
      const action = actionNode.dataset.overview;
      if (action === 'preview') {
        state.previewOpen = !state.previewOpen;
        renderOverview();
      } else if (action === 'quality') {
        state.qualityOpen = !state.qualityOpen;
        renderOverview();
      } else if (action === 'columns') {
        state.showAllColumns = !state.showAllColumns;
        renderOverview();
      } else if (action === 'upload') {
        $('#fileInput').click();
      }
      return;
    }
    const sheetNode = event.target.closest('[data-sheet-id]');
    if (sheetNode) switchSheet(sheetNode.dataset.sheetId);
  });

  $('#suggestionBar').addEventListener('click', (event) => {
    const button = event.target.closest('[data-fill-question]');
    if (button) fillQuestion(button.dataset.fillQuestion);
  });

  $('#chatMessages').addEventListener('click', (event) => {
    const fillButton = event.target.closest('[data-fill-question]');
    if (fillButton) {
      fillQuestion(fillButton.dataset.fillQuestion);
      return;
    }
    const actionNode = event.target.closest('[data-action]');
    if (actionNode) handleAction(actionNode.dataset.action, actionNode.dataset.messageId);
  });

  const input = $('#questionInput');
  input.addEventListener('input', autoresizeInput);
  input.addEventListener('compositionstart', () => { input.dataset.composing = '1'; });
  input.addEventListener('compositionend', () => { delete input.dataset.composing; });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && input.dataset.composing !== '1') {
      event.preventDefault();
      submitQuestion(input.value);
    }
  });
  $('#sendBtn').addEventListener('click', () => submitQuestion(input.value));

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      state.charts.forEach((chart) => {
        try { chart.resize(); } catch (error) { /* noop */ }
      });
    }, 120);
  });
}

function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#sidebarBackdrop').hidden = true;
}

/* boot */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
