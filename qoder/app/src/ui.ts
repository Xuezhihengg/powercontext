import { api, type SearchResult, type ReviewEntry } from './api';
import { embedTexts, embedSingle, ensureModelReady, getModelMeta } from './embedding';
import { setStatus, showToast, loadState, saveState, type AppState } from './state';

const state: AppState = {
  currentCourse: null,
  collections: [],
  reviewProgress: new Map(),
  lastSearchTime: null,
  modelReady: false,
  importProgress: null,
};

const addedReviewSet = new Set<string>();

function el(tag: string, attrs?: Record<string, string>, ...children: (string | Node)[]): HTMLElement {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') node.className = v;
      else if (k === 'textContent') node.textContent = v;
      else if (k.startsWith('data-')) node.setAttribute(k, v);
      else node.setAttribute(k, v);
    }
  }
  for (const child of children) {
    if (typeof child === 'string') node.appendChild(document.createTextNode(child));
    else node.appendChild(child);
  }
  return node;
}

function clearChildren(node: HTMLElement) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function switchTab(tabName: string) {
  document.querySelectorAll('.nav-btn').forEach((b) => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tabName);
  });
  document.querySelectorAll('.tab-content').forEach((t) => {
    t.classList.toggle('active', t.id === `tab-${tabName}`);
  });
  if (tabName === 'review') refreshWeakPoints();
  if (tabName === 'courses') refreshCollections();
}

function navigateToSearchWithQuery(query: string) {
  switchTab('search');
  renderSearch();
  const input = document.getElementById('search-input') as HTMLInputElement;
  if (input) {
    input.value = query;
    input.focus();
  }
}

export function initUI() {
  const saved = loadState();
  if (saved.currentCourse) state.currentCourse = saved.currentCourse;
  setupNav();
  renderCourses();
  renderImport();
  renderSearch();
  renderReview();
  initModel();
}

function setupNav() {
  document.querySelectorAll('.nav-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.getAttribute('data-tab');
      if (tab) switchTab(tab);
    });
  });
}

async function initModel() {
  setStatus('正在加载向量化模型...');
  try {
    const meta = await ensureModelReady();
    state.modelReady = true;
    const sizeMB = (meta.modelSizeBytes / (1024 * 1024)).toFixed(1);
    const backendLabel = meta.backend.toUpperCase();
    const badge = document.getElementById('model-badge');
    if (badge) {
      clearChildren(badge);
      const dot = el('span', { className: 'dot' });
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode(` ${backendLabel} · ${meta.dtype} · ${sizeMB}MB`));
      badge.style.display = 'inline-flex';
    }
    setStatus(`模型就绪 (${backendLabel} ${meta.dtype})`);
    showToast('向量化模型加载完成', 'success');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    setStatus('模型加载失败: ' + msg);
    showToast('模型加载失败，请检查 /models 目录', 'error');
  }
}

function buildTabHeader(tabId: string): HTMLElement {
  const header = el('div', { className: 'tab-header' });
  if (state.currentCourse) {
    const nameEl = el('div', { className: 'course-name' });
    nameEl.appendChild(el('span', { className: 'label-prefix' }, '当前课程:'));
    nameEl.appendChild(document.createTextNode(state.currentCourse));
    header.appendChild(nameEl);
  } else {
    const hint = el('div', { className: 'course-name' });
    hint.appendChild(document.createTextNode('尚未选择课程'));
    header.appendChild(hint);
    const link = el('button', { className: 'hint-link' }, '去课程管理 →');
    link.addEventListener('click', () => switchTab('courses'));
    header.appendChild(link);
  }
  return header;
}

// ─── Courses Tab ───

function renderCourses() {
  const container = document.getElementById('tab-courses');
  if (!container) return;
  clearChildren(container);

  const newCard = el('div', { className: 'card' });
  newCard.appendChild(el('h3', {}, '新建课程'));
  const row = el('div', { className: 'row' });
  const input = el('input', { type: 'text', id: 'new-course-id', placeholder: '课程 ID（英文，如 math101)' }) as HTMLInputElement;
  const btn = el('button', { className: 'primary', id: 'btn-create-course' }, '创建');
  row.appendChild(input);
  row.appendChild(btn);
  newCard.appendChild(row);
  container.appendChild(newCard);

  const listCard = el('div', { className: 'card' });
  listCard.appendChild(el('h3', {}, '课程列表'));
  const listEl = el('div', { id: 'course-list' });
  listEl.appendChild(el('div', { className: 'empty-hint' }, '加载中...'));
  listCard.appendChild(listEl);
  container.appendChild(listCard);

  btn.addEventListener('click', createCourse);
  refreshCollections();
}

async function refreshCollections() {
  try {
    state.collections = await api.listCollections();
    renderCourseList();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const listEl = document.getElementById('course-list');
    if (listEl) {
      clearChildren(listEl);
      listEl.appendChild(el('div', { className: 'empty-hint' }, `加载失败: ${msg}`));
    }
  }
}

function renderCourseList() {
  const listEl = document.getElementById('course-list');
  if (!listEl) return;
  clearChildren(listEl);

  if (state.collections.length === 0) {
    listEl.appendChild(el('div', { className: 'empty-hint' }, '暂无课程，请先创建'));
    return;
  }

  for (const col of state.collections) {
    const card = el('div', { className: 'card' });
    const row = el('div', { className: 'row' });
    row.style.marginBottom = '0';

    const info = el('div');
    info.style.flex = '2';
    const h3 = el('h3');
    h3.textContent = col.courseId + ' ';
    if (state.currentCourse === col.courseId) {
      const badge = el('span', { className: 'badge badge-mastery-2' }, '当前');
      h3.appendChild(badge);
    }
    info.appendChild(h3);

    const meta = el('div', { className: 'collection-info' });
    meta.appendChild(el('span', {}, `文档: ${col.docCount}`));
    meta.appendChild(el('span', {}, `分块: ${col.chunkCount}`));
    meta.appendChild(el('span', {}, `维度: ${col.dimension}`));
    info.appendChild(meta);
    row.appendChild(info);

    const actions = el('div');
    actions.style.flex = '0';
    actions.style.display = 'flex';
    actions.style.gap = '6px';

    const isCurrent = state.currentCourse === col.courseId;
    const switchBtn = el('button', { className: 'small' }, isCurrent ? '已选中' : '切换');
    switchBtn.addEventListener('click', () => {
      state.currentCourse = col.courseId;
      saveState(state);
      refreshCollections();
      updateImportButtonState();
      refreshTabHeaders();
      showToast('已切换课程', 'success');
    });

    const deleteBtn = el('button', { className: 'danger' }, '删除');
    deleteBtn.addEventListener('click', () => {
      if (confirm(`确定删除课程「${col.courseId}」？此操作不可恢复。`)) {
        deleteCourse(col.courseId);
      }
    });

    actions.appendChild(switchBtn);
    actions.appendChild(deleteBtn);
    row.appendChild(actions);
    card.appendChild(row);
    listEl.appendChild(card);
  }
}

function refreshTabHeaders() {
  for (const tabId of ['import', 'search', 'review']) {
    const container = document.getElementById(`tab-${tabId}`);
    if (!container) continue;
    const existing = container.querySelector('.tab-header');
    if (existing) {
      const newHeader = buildTabHeader(tabId);
      existing.replaceWith(newHeader);
    }
  }
  updateImportButtonState();
}

async function createCourse() {
  const input = document.getElementById('new-course-id') as HTMLInputElement;
  const courseId = input?.value.trim();
  if (!courseId) { showToast('请输入课程 ID', 'error'); return; }
  if (!/^[a-zA-Z0-9_]+$/.test(courseId)) { showToast('课程 ID 只能包含英文、数字和下划线', 'error'); return; }
  try {
    setStatus(`正在创建课程 ${courseId}...`);
    await api.createCollection(courseId);
    state.currentCourse = courseId;
    saveState(state);
    input.value = '';
    showToast(`课程「${courseId}」创建成功`, 'success');
    setStatus('就绪');
    refreshCollections();
    updateImportButtonState();
    refreshTabHeaders();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`创建失败: ${msg}`, 'error');
    setStatus('就绪');
  }
}

async function deleteCourse(courseId: string) {
  try {
    setStatus(`正在删除课程 ${courseId}...`);
    await api.deleteCollection(courseId);
    if (state.currentCourse === courseId) {
      state.currentCourse = null;
      saveState(state);
    }
    showToast(`课程「${courseId}」已删除`, 'success');
    setStatus('就绪');
    refreshCollections();
    updateImportButtonState();
    refreshTabHeaders();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`删除失败: ${msg}`, 'error');
    setStatus('就绪');
  }
}

// ─── Import Tab ───

function renderImport() {
  const container = document.getElementById('tab-import');
  if (!container) return;
  clearChildren(container);

  container.appendChild(buildTabHeader('import'));

  const card = el('div', { className: 'card' });
  card.appendChild(el('h3', {}, '导入笔记'));
  card.appendChild(el('p', { className: 'label' }, '支持 .md / .txt / .json（数组格式 {id, title, text}）'));

  const configRow = el('div', { className: 'config-row' });
  const sizeLabel = el('label');
  sizeLabel.appendChild(el('span', {}, '分块大小（字符）'));
  const sizeInput = el('input', { type: 'number', id: 'chunk-size', value: '300', min: '50', max: '2000' }) as HTMLInputElement;
  sizeLabel.appendChild(sizeInput);
  configRow.appendChild(sizeLabel);

  const overlapLabel = el('label');
  overlapLabel.appendChild(el('span', {}, '重叠（字符）'));
  const overlapInput = el('input', { type: 'number', id: 'chunk-overlap', value: '50', min: '0', max: '500' }) as HTMLInputElement;
  overlapLabel.appendChild(overlapInput);
  configRow.appendChild(overlapLabel);
  card.appendChild(configRow);

  const row = el('div', { className: 'row' });
  const fileInput = el('input', { type: 'file', id: 'file-input' }) as HTMLInputElement;
  fileInput.multiple = true;
  fileInput.accept = '.md,.txt,.json';
  fileInput.style.flex = '2';
  const importBtn = el('button', { className: 'primary', id: 'btn-import' }, '开始导入');
  if (!state.currentCourse) importBtn.setAttribute('disabled', '');
  row.appendChild(fileInput);
  row.appendChild(importBtn);
  card.appendChild(row);

  const sampleRow = el('div', { className: 'row' });
  sampleRow.style.justifyContent = 'flex-start';
  const sampleBtn = el('button', { className: 'small', id: 'btn-import-sample' }, '导入示例笔记（机器学习 12 篇）');
  if (!state.currentCourse) sampleBtn.setAttribute('disabled', '');
  sampleRow.appendChild(sampleBtn);
  card.appendChild(sampleRow);

  const progressArea = el('div', { id: 'import-progress-area' });
  progressArea.style.display = 'none';
  progressArea.appendChild(el('div', { className: 'label', id: 'import-status-text' }, '准备中...'));
  const bar = el('div', { className: 'progress-bar' });
  bar.appendChild(el('div', { className: 'fill', id: 'import-progress-fill' }));
  progressArea.appendChild(bar);
  card.appendChild(progressArea);

  card.appendChild(el('div', { id: 'import-file-list', className: 'file-list' }));
  container.appendChild(card);

  importBtn.addEventListener('click', handleImport);
  sampleBtn.addEventListener('click', handleSampleImport);
}

function updateImportButtonState() {
  const importBtn = document.getElementById('btn-import') as HTMLButtonElement;
  const sampleBtn = document.getElementById('btn-import-sample') as HTMLButtonElement;
  if (importBtn) {
    if (state.currentCourse) {
      importBtn.removeAttribute('disabled');
    } else {
      importBtn.setAttribute('disabled', '');
    }
  }
  if (sampleBtn) {
    if (state.currentCourse) {
      sampleBtn.removeAttribute('disabled');
    } else {
      sampleBtn.setAttribute('disabled', '');
    }
  }
}

function splitIntoChunks(text: string, size: number, overlap: number): string[] {
  const sentences = text.match(/[^。！？.!?\n]+[。！？.!?\n]?/g) || [text];
  const chunks: string[] = [];
  let current = '';
  for (const sentence of sentences) {
    if (current.length + sentence.length > size && current.length > 0) {
      chunks.push(current.trim());
      const words = current.split(/\s+/);
      let keep = '';
      let keepLen = 0;
      for (let i = words.length - 1; i >= 0; i--) {
        if (keepLen + words[i].length > overlap) break;
        keep = words[i] + ' ' + keep;
        keepLen += words[i].length + 1;
      }
      current = keep.trim() + sentence;
    } else {
      current += sentence;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

interface ParsedFile {
  fileName: string;
  chunks: Array<{ id: string; text: string; fileName: string; chunkIndex: number }>;
}

function parseFile(fileName: string, content: string, chunkSize: number, chunkOverlap: number): ParsedFile {
  const chunks: ParsedFile['chunks'] = [];
  if (fileName.endsWith('.json')) {
    try {
      const arr = JSON.parse(content);
      if (Array.isArray(arr)) {
        arr.forEach((item: { id?: string; title?: string; text?: string }, idx: number) => {
          const text = item.text || item.title || '';
          if (!text) return;
          const subChunks = splitIntoChunks(text, chunkSize, chunkOverlap);
          subChunks.forEach((c, ci) => {
            chunks.push({
              id: `${item.id || idx}_${ci}`,
              text: c,
              fileName: item.title || fileName,
              chunkIndex: ci,
            });
          });
        });
      }
    } catch {
      const textChunks = splitIntoChunks(content, chunkSize, chunkOverlap);
      textChunks.forEach((c, i) => {
        chunks.push({ id: `${fileName}_${i}`, text: c, fileName, chunkIndex: i });
      });
    }
  } else {
    const textChunks = splitIntoChunks(content, chunkSize, chunkOverlap);
    textChunks.forEach((c, i) => {
      chunks.push({ id: `${fileName}_${i}`, text: c, fileName, chunkIndex: i });
    });
  }
  return { fileName, chunks };
}

async function handleImport() {
  if (!state.currentCourse) { showToast('请先选择课程', 'error'); return; }
  if (!state.modelReady) { showToast('模型尚未加载完成', 'error'); return; }

  const fileInput = document.getElementById('file-input') as HTMLInputElement;
  const files = fileInput?.files;
  if (!files || files.length === 0) { showToast('请选择文件', 'error'); return; }

  const chunkSize = parseInt((document.getElementById('chunk-size') as HTMLInputElement)?.value || '300');
  const chunkOverlap = parseInt((document.getElementById('chunk-overlap') as HTMLInputElement)?.value || '50');

  const progressArea = document.getElementById('import-progress-area');
  const statusText = document.getElementById('import-status-text');
  const progressFill = document.getElementById('import-progress-fill');
  const fileListEl = document.getElementById('import-file-list');
  if (progressArea) progressArea.style.display = 'block';
  if (statusText) statusText.textContent = '正在读取文件...';
  if (progressFill) progressFill.style.width = '0%';
  if (fileListEl) clearChildren(fileListEl);

  try {
    const allParsed: ParsedFile[] = [];
    for (const file of Array.from(files)) {
      const content = await file.text();
      const parsed = parseFile(file.name, content, chunkSize, chunkOverlap);
      allParsed.push(parsed);
      if (fileListEl) {
        const item = el('div', { className: 'file-item' }, `${file.name} — ${parsed.chunks.length} 个分块`);
        fileListEl.appendChild(item);
      }
    }

    const totalChunks = allParsed.reduce((sum, p) => sum + p.chunks.length, 0);
    if (totalChunks === 0) { showToast('未解析到任何内容', 'error'); return; }

    if (statusText) statusText.textContent = `正在向量化 0/${totalChunks}...`;
    if (progressFill) progressFill.style.width = '0%';

    const allChunks = allParsed.flatMap((p) => p.chunks);
    const batchSize = 16;
    const embedded: Array<typeof allChunks[0] & { embedding: number[] }> = [];

    for (let i = 0; i < allChunks.length; i += batchSize) {
      const batch = allChunks.slice(i, i + batchSize);
      const texts = batch.map((c) => c.text);
      const vectors = await embedTexts(texts);
      batch.forEach((c, j) => {
        embedded.push({ ...c, embedding: vectors[j] });
      });
      const done = Math.min(i + batchSize, totalChunks);
      if (statusText) statusText.textContent = `正在向量化 ${done}/${totalChunks}...`;
      if (progressFill) progressFill.style.width = `${(done / totalChunks) * 80}%`;
    }

    if (statusText) statusText.textContent = '正在写入 seekdb...';
    if (progressFill) progressFill.style.width = '85%';

    const importBatchSize = 50;
    for (let i = 0; i < embedded.length; i += importBatchSize) {
      const batch = embedded.slice(i, i + importBatchSize);
      await api.importChunks(
        state.currentCourse,
        batch.map((c) => ({
          id: c.id,
          text: c.text,
          embedding: c.embedding,
          fileName: c.fileName,
          chunkIndex: c.chunkIndex,
        }))
      );
      const done = Math.min(i + importBatchSize, embedded.length);
      if (progressFill) progressFill.style.width = `${85 + (done / embedded.length) * 15}%`;
    }

    if (statusText) statusText.textContent = `导入完成: ${embedded.length} 个分块`;
    if (progressFill) progressFill.style.width = '100%';
    showToast(`成功导入 ${embedded.length} 个分块`, 'success');
    refreshCollections();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`导入失败: ${msg}`, 'error');
    if (statusText) statusText.textContent = `导入失败: ${msg}`;
  }
}

async function handleSampleImport() {
  if (!state.currentCourse) { showToast('请先选择课程', 'error'); return; }
  if (!state.modelReady) { showToast('模型尚未加载完成', 'error'); return; }

  const chunkSize = parseInt((document.getElementById('chunk-size') as HTMLInputElement)?.value || '300');
  const chunkOverlap = parseInt((document.getElementById('chunk-overlap') as HTMLInputElement)?.value || '50');

  const progressArea = document.getElementById('import-progress-area');
  const statusText = document.getElementById('import-status-text');
  const progressFill = document.getElementById('import-progress-fill');
  const fileListEl = document.getElementById('import-file-list');
  if (progressArea) progressArea.style.display = 'block';
  if (statusText) statusText.textContent = '正在加载示例笔记...';
  if (progressFill) progressFill.style.width = '0%';
  if (fileListEl) clearChildren(fileListEl);

  try {
    const res = await fetch('/notes/sample.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const samples: Array<{ id: string; title: string; text: string }> = await res.json();

    const allParsed: ParsedFile[] = [];
    for (const item of samples) {
      const text = item.text || '';
      if (!text) continue;
      const subChunks = splitIntoChunks(text, chunkSize, chunkOverlap);
      const chunks = subChunks.map((c, ci) => ({
        id: `${item.id}_${ci}`,
        text: c,
        fileName: item.title || item.id,
        chunkIndex: ci,
      }));
      allParsed.push({ fileName: item.title || item.id, chunks });
      if (fileListEl) {
        const itemEl = el('div', { className: 'file-item' }, `${item.title} — ${chunks.length} 个分块`);
        fileListEl.appendChild(itemEl);
      }
    }

    const totalChunks = allParsed.reduce((sum, p) => sum + p.chunks.length, 0);
    if (totalChunks === 0) { showToast('示例笔记为空', 'error'); return; }

    if (statusText) statusText.textContent = `正在向量化 0/${totalChunks}...`;

    const allChunks = allParsed.flatMap((p) => p.chunks);
    const batchSize = 16;
    const embedded: Array<typeof allChunks[0] & { embedding: number[] }> = [];

    for (let i = 0; i < allChunks.length; i += batchSize) {
      const batch = allChunks.slice(i, i + batchSize);
      const texts = batch.map((c) => c.text);
      const vectors = await embedTexts(texts);
      batch.forEach((c, j) => {
        embedded.push({ ...c, embedding: vectors[j] });
      });
      const done = Math.min(i + batchSize, totalChunks);
      if (statusText) statusText.textContent = `正在向量化 ${done}/${totalChunks}...`;
      if (progressFill) progressFill.style.width = `${(done / totalChunks) * 80}%`;
    }

    if (statusText) statusText.textContent = '正在写入 seekdb...';
    if (progressFill) progressFill.style.width = '85%';

    const importBatchSize = 50;
    for (let i = 0; i < embedded.length; i += importBatchSize) {
      const batch = embedded.slice(i, i + importBatchSize);
      await api.importChunks(
        state.currentCourse,
        batch.map((c) => ({
          id: c.id,
          text: c.text,
          embedding: c.embedding,
          fileName: c.fileName,
          chunkIndex: c.chunkIndex,
        }))
      );
      const done = Math.min(i + importBatchSize, embedded.length);
      if (progressFill) progressFill.style.width = `${85 + (done / embedded.length) * 15}%`;
    }

    if (statusText) statusText.textContent = `导入完成: ${embedded.length} 个分块`;
    if (progressFill) progressFill.style.width = '100%';
    showToast(`成功导入 ${embedded.length} 个示例分块`, 'success');
    refreshCollections();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`导入示例失败: ${msg}`, 'error');
    if (statusText) statusText.textContent = `导入失败: ${msg}`;
  }
}

// ─── Search Tab ───

function renderSearch() {
  const container = document.getElementById('tab-search');
  if (!container) return;
  clearChildren(container);

  container.appendChild(buildTabHeader('search'));

  const card = el('div', { className: 'card' });
  card.appendChild(el('h3', {}, '混合检索'));
  const row = el('div', { className: 'search-row' });
  const input = el('input', { type: 'text', id: 'search-input', placeholder: '输入问题或关键词...' }) as HTMLInputElement;
  const btn = el('button', { className: 'primary', id: 'btn-search' }, '检索');
  row.appendChild(input);
  row.appendChild(btn);
  card.appendChild(row);
  card.appendChild(el('div', { id: 'search-timing', className: 'label' }));
  container.appendChild(card);
  container.appendChild(el('div', { id: 'search-results' }));

  btn.addEventListener('click', handleSearch);
  input.addEventListener('keydown', (e) => {
    if ((e as KeyboardEvent).key === 'Enter') handleSearch();
  });
}

async function handleSearch() {
  if (!state.currentCourse) { showToast('请先选择课程', 'error'); return; }
  if (!state.modelReady) { showToast('模型尚未加载完成', 'error'); return; }

  const input = document.getElementById('search-input') as HTMLInputElement;
  const query = input?.value.trim();
  if (!query) { showToast('请输入查询内容', 'error'); return; }

  const resultsEl = document.getElementById('search-results');
  const timingEl = document.getElementById('search-timing');
  if (resultsEl) {
    clearChildren(resultsEl);
    resultsEl.appendChild(el('div', { className: 'empty-hint' }, '检索中...'));
  }

  try {
    const t0 = performance.now();
    const vector = await embedSingle(query);
    const t1 = performance.now();

    const { results } = await api.search(state.currentCourse, query, vector, 10);
    const t2 = performance.now();

    state.lastSearchTime = {
      embed: Math.round(t1 - t0),
      search: Math.round(t2 - t1),
      total: Math.round(t2 - t0),
    };
    if (timingEl) {
      timingEl.textContent = `向量化: ${state.lastSearchTime.embed}ms | seekdb 检索: ${state.lastSearchTime.search}ms | 总计: ${state.lastSearchTime.total}ms`;
    }

    if (!resultsEl) return;
    clearChildren(resultsEl);
    if (results.length === 0) {
      resultsEl.appendChild(el('div', { className: 'empty-hint' }, '未找到相关结果'));
      return;
    }

    for (const r of results) {
      resultsEl.appendChild(buildSearchResultCard(r, query));
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`检索失败: ${msg}`, 'error');
    if (resultsEl) {
      clearChildren(resultsEl);
      resultsEl.appendChild(el('div', { className: 'empty-hint' }, `检索失败: ${msg}`));
    }
  }
}

function buildSearchResultCard(r: SearchResult, query: string): HTMLElement {
  const card = el('div', { className: 'search-result' });

  const headerRow = el('div', { className: 'result-header' });
  headerRow.appendChild(el('div', { className: 'score' }, `得分 ${(r.score ?? 0).toFixed(4)}`));
  headerRow.appendChild(el('span', { className: 'meta-tag' }, `ID: ${r.id}`));
  card.appendChild(headerRow);

  const textDiv = el('div', { className: 'text' });
  highlightInto(textDiv, r.text || '', query);
  card.appendChild(textDiv);

  const metaDiv = el('div', { className: 'meta' });
  metaDiv.appendChild(el('span', {}, `来源: ${r.file_name || '未知'}`));
  metaDiv.appendChild(el('span', {}, `分块 #${r.chunk_index ?? '-'}`));
  card.appendChild(metaDiv);

  const actions = el('div', { className: 'actions' });
  const alreadyAdded = addedReviewSet.has(r.id);
  const addBtn = el('button', { className: 'small' + (alreadyAdded ? ' added' : '') }, alreadyAdded ? '已加入' : '加入复习');
  if (alreadyAdded) {
    addBtn.setAttribute('disabled', '');
  }
  addBtn.addEventListener('click', () => {
    if (addedReviewSet.has(r.id)) return;
    addReview(r.id, r.text || '', r.file_name || '').then((ok) => {
      if (ok) {
        addedReviewSet.add(r.id);
        addBtn.textContent = '已加入';
        addBtn.classList.add('added');
        addBtn.setAttribute('disabled', '');
      }
    });
  });
  actions.appendChild(addBtn);
  card.appendChild(actions);

  return card;
}

function highlightInto(parent: HTMLElement, text: string, query: string) {
  if (!query.trim()) {
    parent.appendChild(document.createTextNode(text));
    return;
  }
  const words = query.split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    parent.appendChild(document.createTextNode(text));
    return;
  }
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const regex = new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts = text.split(regex);
  for (const part of parts) {
    if (regex.test(part)) {
      const mark = el('mark');
      mark.textContent = part;
      parent.appendChild(mark);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
    regex.lastIndex = 0;
  }
}

async function addReview(chunkId: string, text: string, fileName: string): Promise<boolean> {
  if (!state.currentCourse) return false;
  try {
    await api.addReview(state.currentCourse, chunkId, text, fileName);
    showToast('已加入复习', 'success');
    return true;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    showToast(`加入复习失败: ${msg}`, 'error');
    return false;
  }
}

// ─── Review Tab ───

function renderReview() {
  const container = document.getElementById('tab-review');
  if (!container) return;
  clearChildren(container);

  container.appendChild(buildTabHeader('review'));

  const weakCard = el('div', { className: 'card' });
  weakCard.appendChild(el('h3', {}, '薄弱知识点 Top 5'));
  const weakList = el('div', { id: 'weak-points-list' });
  weakList.appendChild(el('div', { className: 'empty-hint' }, '加载中...'));
  weakCard.appendChild(weakList);
  container.appendChild(weakCard);

  const allCard = el('div', { className: 'card' });
  allCard.appendChild(el('h3', {}, '全部复习记录'));
  const allList = el('div', { id: 'all-progress-list' });
  allList.appendChild(el('div', { className: 'empty-hint' }, '加载中...'));
  allCard.appendChild(allList);
  container.appendChild(allCard);
}

async function refreshWeakPoints() {
  if (!state.currentCourse) {
    const weakEl = document.getElementById('weak-points-list');
    if (weakEl) {
      clearChildren(weakEl);
      weakEl.appendChild(el('div', { className: 'empty-hint' }, '请先选择课程'));
    }
    return;
  }
  try {
    const weakPoints = await api.getWeakPoints(state.currentCourse);
    const allProgress = await api.getAllProgress(state.currentCourse);
    renderWeakPointsList(weakPoints);
    renderAllProgressList(allProgress);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const weakEl = document.getElementById('weak-points-list');
    if (weakEl) {
      clearChildren(weakEl);
      weakEl.appendChild(el('div', { className: 'empty-hint' }, `加载失败: ${msg}`));
    }
  }
}

function masteryLabel(mastery: number): string {
  return mastery === 2 ? '会' : mastery === 1 ? '模糊' : '不会';
}

function renderWeakPointsList(items: ReviewEntry[]) {
  const listEl = document.getElementById('weak-points-list');
  if (!listEl) return;
  clearChildren(listEl);

  if (items.length === 0) {
    listEl.appendChild(el('div', { className: 'empty-hint' }, '暂无薄弱知识点。请先在"检索复习"页面搜索并加入复习记录。'));
    return;
  }

  for (const item of items) {
    const row = el('div', { className: 'weak-item' });

    const info = el('div', { className: 'info' });
    const preview = el('div', { className: 'text-preview' });
    preview.textContent = (item.text || '').slice(0, 100) + ((item.text || '').length > 100 ? '...' : '');
    info.appendChild(preview);

    const metaLine = el('div', { className: 'meta-line' });
    const badge = el('span', { className: `badge badge-mastery-${item.mastery}` }, masteryLabel(item.mastery));
    metaLine.appendChild(badge);
    metaLine.appendChild(document.createTextNode(`${item.file_name || '未知'} · 复习 ${item.review_count} 次`));
    info.appendChild(metaLine);
    row.appendChild(info);

    const actionsCol = el('div', { className: 'actions-col' });

    const btnGroup = el('div', { className: 'mastery-btns' });
    for (const val of [2, 1, 0]) {
      const btn = el('button', { title: masteryLabel(val) }, masteryLabel(val));
      if (val === item.mastery) btn.classList.add(`selected-mastery-${val}`);
      btn.addEventListener('click', async () => {
        try {
          await api.updateMastery(item.id, val);
          showToast('掌握度已更新', 'success');
          refreshWeakPoints();
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          showToast(`更新失败: ${msg}`, 'error');
        }
      });
      btnGroup.appendChild(btn);
    }
    actionsCol.appendChild(btnGroup);

    const reviewAgainBtn = el('button', { className: 'small' }, '再次复习');
    reviewAgainBtn.addEventListener('click', () => {
      const queryText = (item.text || '').slice(0, 200);
      navigateToSearchWithQuery(queryText);
    });
    actionsCol.appendChild(reviewAgainBtn);

    row.appendChild(actionsCol);
    listEl.appendChild(row);
  }
}

function renderAllProgressList(items: ReviewEntry[]) {
  const listEl = document.getElementById('all-progress-list');
  if (!listEl) return;
  clearChildren(listEl);

  if (items.length === 0) {
    listEl.appendChild(el('div', { className: 'empty-hint' }, '暂无复习记录。请先在"检索复习"页面搜索知识点并点击"加入复习"。'));
    return;
  }

  for (const item of items) {
    const row = el('div', { className: 'weak-item' });

    const info = el('div', { className: 'info' });
    const preview = el('div', { className: 'text-preview' });
    preview.textContent = (item.text || '').slice(0, 80) + ((item.text || '').length > 80 ? '...' : '');
    info.appendChild(preview);

    const metaLine = el('div', { className: 'meta-line' });
    const badge = el('span', { className: `badge badge-mastery-${item.mastery}` }, masteryLabel(item.mastery));
    metaLine.appendChild(badge);
    metaLine.appendChild(document.createTextNode(`${item.file_name || '未知'} · 复习 ${item.review_count} 次 · ${item.last_reviewed || ''}`));
    info.appendChild(metaLine);
    row.appendChild(info);

    const btnGroup = el('div', { className: 'mastery-btns' });
    for (const val of [2, 1, 0]) {
      const btn = el('button', { title: masteryLabel(val) }, masteryLabel(val));
      if (val === item.mastery) btn.classList.add(`selected-mastery-${val}`);
      btn.addEventListener('click', async () => {
        try {
          await api.updateMastery(item.id, val);
          showToast('掌握度已更新', 'success');
          refreshWeakPoints();
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          showToast(`更新失败: ${msg}`, 'error');
        }
      });
      btnGroup.appendChild(btn);
    }
    row.appendChild(btnGroup);

    listEl.appendChild(row);
  }
}
