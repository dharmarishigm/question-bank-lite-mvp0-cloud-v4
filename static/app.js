const $ = (id) => document.getElementById(id);
const MATH_PATTERN = /(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*?\$)/g;
const KATEX_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '\\[', right: '\\]', display: true },
  { left: '\\(', right: '\\)', display: false },
  { left: '$', right: '$', display: false },
];
const TABLE_SNIPPET = '\n| Column A | Column B |\n| --- | --- |\n| value | value |\n';
const OPTION_LABELS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

let editingId = null;
let editingSourceImage = '';
let editingMeta = {};
let questions = [];
let previewConfirmed = false;
let pageOffset = 0;
const PAGE_SIZE = 25;
let searchRequest = 0;
let noticeTimer;
function notify(message) {
  const box = $('notification');
  box.textContent = String(message);
  box.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { box.hidden = true; }, 6000);
}
function invalidatePreview() {
  if (editingMeta.extraction_provider) editingMeta.verification_status = 'REVIEW';
  previewConfirmed = false;
  updatePreview();
  syncSaveState();
}

function syncSaveState() {
  const saveButton = $('btn-save');
  const hasStatement = (formValue().statement || '').trim().length > 0;
  saveButton.disabled = !previewConfirmed || !hasStatement;
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function safeUrl(value) {
  const url = String(value || '');
  return (/^\/uploads\/[a-z0-9_-]+(?:\.[a-z0-9]+)?$/i.test(url) || /^https?:\/\//i.test(url) || /^data:image\//i.test(url) || /^blob:/i.test(url)) ? escapeHtml(url) : '';
}

function renderTables(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const isRow = (s) => /^\s*\|.*\|\s*$/.test(s);
    if (isRow(lines[i]) && isRow(lines[i + 1] || '') && /^[\s|:-]+$/.test(lines[i + 1])) {
      const cells = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const header = cells(lines[i]);
      const body = [];
      i += 2;
      while (i < lines.length && isRow(lines[i])) body.push(cells(lines[i++]));
      i--;
      out.push(
        '<table><thead><tr>' + header.map((c) => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
        body.map((r) => '<tr>' + r.map((c) => `<td>${c}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>'
      );
    } else {
      out.push(lines[i]);
    }
  }
  return out;
}

/** Markdown-lite + LaTeX: math segments are shielded from markdown rewriting. */
function toHtml(source) {
  const math = [];
  let text = escapeHtml(source || '').replace(MATH_PATTERN, (m) => {
    math.push(m);
    return `\u0000${math.length - 1}\u0000`;
  });
  text = text
    .replace(/!\[formula:(\d+(?:\.\d+)?)\]\((\/uploads\/[a-f0-9]+\.png)\)/g,
      (_, height, url) => `<img class="inline-formula" src="${url}" alt="Formula from original PDF" style="height:${Math.min(12, Number(height))}em" />`)
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => safeUrl(url) ? `<img src="${url}" alt="${alt}" loading="lazy" />` : alt)
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => /^https?:\/\//i.test(url) ? `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>` : label)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  text = renderTables(text.split('\n')).join('\n');
  text = text.replace(/\n{2,}/g, '<br><br>').replace(/\n(?!<\/?table|<tbody|<thead|<tr)/g, '<br>');
  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => math[Number(i)]);
}

function typeset(el) {
  if (window.renderMathInElement) {
    renderMathInElement(el, { delimiters: KATEX_DELIMITERS, throwOnError: false, strict: false });
  }
}

function renderInto(el, source) {
  el.innerHTML = toHtml(source);
  el.classList.add('rendered');
  typeset(el);
}

function formValue() {
  const options = [...document.querySelectorAll('#options-block textarea')].map((area) => area.value.trim());
  while (options.length && options[options.length - 1] === '') options.pop();
  return {
    subject: $('f-subject').value, chapter: $('f-chapter').value.trim(),
    topic: $('f-topic').value.trim(), exam: $('f-exam').value.trim(),
    year: $('f-year').value.trim(), qtype: $('f-qtype').value,
    difficulty: $('f-difficulty').value, marks: $('f-marks').value.trim(),
    statement: $('f-statement').value, options,
    answer: $('f-answer').value.trim(), solution: $('f-solution').value,
    tags: $('f-tags').value.trim(), source_image: editingSourceImage,
    ...editingMeta,
  };
}

function fillForm(q) {
  previewConfirmed = false;
  const count = Math.max(6, (q.options || []).length);
  $('options-block').innerHTML = Array.from({ length: count }, (_, i) => `<div class="opt"><span>${OPTION_LABELS[i]}</span><textarea id="f-opt-${i}" aria-label="Option ${OPTION_LABELS[i]}" rows="1"></textarea></div>`).join('');
  document.querySelectorAll('#options-block textarea').forEach(bindEditorArea);
  $('f-subject').value = q.subject || 'Mathematics';
  $('f-chapter').value = q.chapter || '';
  $('f-topic').value = q.topic || '';
  $('f-exam').value = q.exam || '';
  $('f-year').value = q.year || '';
  $('f-qtype').value = q.qtype || 'mcq_single';
  $('f-difficulty').value = q.difficulty || 'medium';
  $('f-marks').value = q.marks || '';
  $('f-tags').value = q.tags || '';
  $('f-statement').value = q.statement || '';
  $('f-answer').value = q.answer || '';
  $('f-solution').value = q.solution || '';
  editingSourceImage = q.source_image || '';
  editingMeta = {
    source_segments: q.source_segments || [], source_document_id: q.source_document_id || '',
    source_document_sha256: q.source_document_sha256 || '', source_page: q.source_page || 0,
    source_bbox: q.source_bbox || [], extraction_run_id: q.extraction_run_id || '',
    extraction_provider: q.extraction_provider || '', extraction_model: q.extraction_model || '',
    verification_status: q.verification_status || 'UNVERIFIED', confidence: Number(q.confidence || 0),
    verification_issues: q.verification_issues || [], uncertainties: q.uncertainties || [],
    content_blocks: q.content_blocks || [], visual_assets: q.visual_assets || [], math_evidence: q.math_evidence || [],
  };
  $('f-source').hidden = !editingSourceImage;
  $('f-source-img').src = editingSourceImage || '';
  Array.from({ length: count }, (_, i) => i).forEach((i) => { $(`f-opt-${i}`).value = (q.options || [])[i] || ''; });
  updatePreview();
}

function resetForm() {
  editingId = null;
  previewConfirmed = false;
  $('editor-title').textContent = 'New question';
  fillForm({});
  syncSaveState();
}

function openEditor() {
  switchMainTab('questions');
  $('editor').hidden = false;
  $('editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function visualAssetsHtml(q) {
  const assets = q.visual_assets || [];
  if (!assets.length) return '';
  return `<div class="digital-assets">${assets.map((a) => {
    const kind = escapeHtml(a.type || a.kind || 'image');
    const url = safeUrl(a.asset);
    const table = a.table || {};
    let structured = '';
    if ((table.headers || []).length || (table.rows || []).length) {
      structured = `<div class="structured-table"><table><thead><tr>${(table.headers || []).map((h) => `<th class="rendered">${toHtml(h)}</th>`).join('')}</tr></thead><tbody>${(table.rows || []).map((row) => `<tr>${row.map((c) => `<td class="rendered">${toHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    const graph = a.graph || {};
    const graphMeta = (graph.x_axis || graph.y_axis || (graph.labels || []).length)
      ? `<div class="asset-meta">${graph.x_axis ? `x: ${escapeHtml(graph.x_axis)}` : ''}${graph.y_axis ? ` · y: ${escapeHtml(graph.y_axis)}` : ''}${(graph.labels || []).length ? ` · labels: ${escapeHtml(graph.labels.join(', '))}` : ''}</div>` : '';
    return `<figure class="digital-asset"><figcaption>${kind}${a.description ? ` — ${escapeHtml(a.description)}` : ''}</figcaption>${structured}${url ? `<img loading="lazy" src="${url}" alt="${kind} preserved from source" /><button type="button" class="image-expand" data-view-image="${url}">Expand image</button>` : ''}${graphMeta}</figure>`;
  }).join('')}</div>`;
}

function blockSummaryHtml(q) {
  const types = [...new Set((q.content_blocks || []).map((b) => b.type).filter(Boolean))];
  return types.length ? `<span class="block-summary">digital blocks: ${types.map(escapeHtml).join(', ')}</span>` : '';
}

function cardHtml(q, withAnswer) {
  const meta = [q.subject, q.chapter, q.topic, q.exam, q.year, q.difficulty, q.marks && `${q.marks} marks`, q.tags]
    .filter(Boolean).map((m) => `<span>${escapeHtml(String(m))}</span>`).join('');
  const opts = (q.options || []).length
    ? `<ul class="opts">${q.options.map((o, i) => `<li><span class="option-label">(${OPTION_LABELS[i] || i + 1})</span><div class="option-content rendered">${toHtml(o)}</div></li>`).join('')}</ul>`
    : '';
  const answer = withAnswer && (q.answer || q.solution)
    ? `<div class="answer rendered">${q.answer ? `<strong>Answer:</strong> ${toHtml(q.answer)}` : ''}${q.solution ? `<br>${toHtml(q.solution)}` : ''}</div>`
    : '';
  const evidence = (q.source_segments || []).filter((seg) => safeUrl(seg.image));
  if (!evidence.length && safeUrl(q.source_image)) evidence.push({ image: q.source_image, page: q.source_page });
  const source = q.hide_source ? '' : evidence.map((seg) => {
    const url = safeUrl(seg.image);
    return `<figure class="source-image"><figcaption>Original source evidence${seg.page ? ` · Page ${escapeHtml(seg.page)}` : ''}</figcaption>
      <img loading="lazy" src="${url}" alt="Complete original source evidence" /><button type="button" class="image-expand" data-view-image="${url}">Expand source</button></figure>`;
  }).join('');
  const status = q.verification_status && q.verification_status !== 'UNVERIFIED'
    ? `<span class="verify ${String(q.verification_status).toLowerCase()}">${escapeHtml(q.verification_status)} ${q.confidence ? Math.round(Number(q.confidence) * 100) + '%' : ''}</span>` : '';
  return `<div class="meta">${meta}${status}${blockSummaryHtml(q)}<span>#${q.id}</span></div>
    <div class="rendered">${toHtml(q.statement)}</div>${visualAssetsHtml(q)}${opts}${answer}${source}
    <div class="card-actions">
      <button data-edit="${q.id}">Edit</button>
      <button data-delete="${q.id}">Delete</button>
    </div>`;
}

function renderList() {
  const withAnswer = $('s-answers').checked;
  const list = $('list');
  list.classList.toggle('hide-source', !$('s-originals').checked);
  list.innerHTML = questions.map((q) => `<div class="question-card">${cardHtml(q, withAnswer)}</div>`).join('')
    || '<div class="empty-state"><span class="empty-icon" aria-hidden="true">Q</span><h3>No questions to show</h3><p>Upload a source or create a question to get started. If you used filters, try broadening your search.</p></div>';
  typeset(list);
}

async function loadQuestions() {
  const request = ++searchRequest;
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: pageOffset });
  if ($('s-q').value.trim()) params.set('q', $('s-q').value.trim());
  ['subject', 'chapter', 'difficulty'].forEach((k) => {
    if ($(`s-${k}`).value) params.set(k, $(`s-${k}`).value);
  });
  $('list').setAttribute('aria-busy', 'true');
  try {
    const res = await fetch(`/api/questions?${params}`);
    if (!res.ok) throw new Error(`Could not load questions (${res.status})`);
    const data = await res.json();
    if (request !== searchRequest) return;
    if (pageOffset && !data.items.length) {
      pageOffset = Math.max(0, Math.ceil(data.total / PAGE_SIZE) - 1) * PAGE_SIZE;
      return loadQuestions();
    }
    questions = data.items;
    $('count').textContent = `${data.total} question${data.total === 1 ? '' : 's'}`;
    $('page-summary').textContent = data.total ? `${pageOffset + 1}–${pageOffset + questions.length} of ${data.total}` : '0 questions';
    $('page-prev').disabled = pageOffset === 0;
    $('page-next').disabled = pageOffset + PAGE_SIZE >= data.total;
    renderList();
  } catch (err) { notify(err.message); }
  finally { if (request === searchRequest) $('list').setAttribute('aria-busy', 'false'); }
}

async function loadFacets() {
  const res = await fetch('/api/facets');
  if (!res.ok) { notify('Could not load filters. Refresh to try again.'); return; }
  const data = await res.json();
  const fill = (sel, values, allLabel) => {
    const current = sel.value;
    sel.innerHTML = `<option value="">${allLabel}</option>` +
      values.map((v) => `<option>${escapeHtml(v)}</option>`).join('');
    sel.value = current;
  };
  fill($('s-subject'), data.subjects, 'All subjects');
  fill($('s-chapter'), data.chapters, 'All chapters');
}

function updatePreview() {
  const q = formValue();
  $('preview').innerHTML = cardHtml({ ...q, id: editingId ?? 'new' }, true);
  typeset($('preview'));
  if (!previewConfirmed) {
    syncSaveState();
  }
}

async function saveRequest() {
  if (!previewConfirmed) {
    $('save-status').textContent = 'Preview required before saving';
    return;
  }
  const payload = formValue();
  if (payload.extraction_provider) payload.verification_status = 'REVIEW';
  if (!payload.statement.trim()) {
    $('save-status').textContent = 'Statement is required';
    return;
  }
  const url = editingId ? `/api/questions/${editingId}` : '/api/questions';
  const res = await fetch(url, {
    method: editingId ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    $('save-status').textContent = `Save failed (${res.status})`;
    return;
  }
  $('save-status').textContent = editingId ? 'Updated' : 'Saved';
  setTimeout(() => { $('save-status').textContent = ''; }, 2000);
  resetForm();
  $('editor').hidden = true;
  await Promise.all([loadQuestions(), loadFacets()]);
}

async function uploadImage(file, targetId) {
  const form = new FormData();
  form.append('file', file, file.name || 'paste.png');
  const res = await fetch('/api/upload', { method: 'POST', body: form });
  if (!res.ok) {
    notify('Upload failed');
    return;
  }
  const { url } = await res.json();
  insertSnippet($(targetId), `\n![diagram](${url})\n`);
}

function insertSnippet(area, snippet) {
  if (!area || typeof snippet !== 'string') return;
  previewConfirmed = false;
  const text = snippet === 'table' ? TABLE_SNIPPET : snippet;
  const start = area.selectionStart ?? area.value.length;
  const end = area.selectionEnd ?? area.value.length;
  area.value = area.value.slice(0, start) + text + area.value.slice(end);
  area.focus();
  const caret = start + text.length - (/\$\$?$/.test(text) ? 1 : 0);
  area.setSelectionRange(caret, caret);
  updatePreview();
}

function bindEditorArea(area) {
  area.addEventListener('input', invalidatePreview);
  area.addEventListener('paste', (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'));
    if (!item) return;
    e.preventDefault();
    uploadImage(item.getAsFile(), area.id);
  });
  area.addEventListener('dragover', (e) => { e.preventDefault(); area.classList.add('drop-active'); });
  area.addEventListener('dragleave', () => area.classList.remove('drop-active'));
  area.addEventListener('drop', (e) => {
    e.preventDefault();
    area.classList.remove('drop-active');
    const file = e.dataTransfer?.files?.[0];
    if (file && file.type.startsWith('image/')) uploadImage(file, area.id);
  });
}

document.querySelectorAll('textarea, #editor input, #editor select').forEach((el) => {
  if (el.tagName === 'TEXTAREA') bindEditorArea(el);
  else el.addEventListener('input', () => {
    invalidatePreview();
  });
});

document.querySelectorAll('.toolbar').forEach((bar) => {
  const targetId = bar.dataset.target;
  bar.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.upload) {
      const picker = $('upload-file');
      picker.onchange = () => {
        if (picker.files[0]) uploadImage(picker.files[0], targetId);
        picker.value = '';
      };
      picker.click();
    } else if (btn.dataset.snippet !== undefined) {
      insertSnippet($(targetId), btn.dataset.snippet);
    }
  });
});

$('list').addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  if (btn.dataset.edit) {
    const q = questions.find((item) => String(item.id) === btn.dataset.edit);
    editingId = q.id;
    $('editor-title').textContent = `Editing question #${q.id}`;
    fillForm(q);
    openEditor();
  }
  if (btn.dataset.delete && confirm('Delete this question?')) {
    const res = await fetch(`/api/questions/${btn.dataset.delete}`, { method: 'DELETE' });
    if (!res.ok) { notify('Could not delete this question. Please try again.'); return; }
    if (editingId === Number(btn.dataset.delete)) resetForm();
    await Promise.all([loadQuestions(), loadFacets()]);
  }
});

$('btn-preview').addEventListener('click', () => {
  previewConfirmed = true;
  updatePreview();
  syncSaveState();
  $('preview').scrollIntoView({ behavior: 'smooth', block: 'start' });
});
$('btn-save').addEventListener('click', save);
$('btn-reset').addEventListener('click', resetForm);
$('btn-new').addEventListener('click', () => { resetForm(); openEditor(); });
$('btn-upload-document').addEventListener('click', () => {
  $('pdf-file').click();
});

$('btn-digitize-image').addEventListener('click', () => {
  const picker = $('upload-file');
  picker.accept = '.pdf,.txt,.md,.csv,.json,.log,.html,.xml,.rtf,.ipynb,.doc,.docx,.odt,.ppt,.pptx,.xls,.xlsx,image/png,image/jpeg,image/webp';
  picker.onchange = async () => {
    const file = picker.files[0];
    if (!file) return;
    picker.value = '';
    setUploadStatus(true, 'Digitizing source…');
    try {
      const res = await fetch('/api/source/parse', {
        method: 'POST',
        body: (() => {
          const form = new FormData();
          form.append('file', file, file.name);
          form.append('mode', 'auto');
          return form;
        })(),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'digitization failed');
      if ((body.questions || []).length !== 1) {
        await openPdfModal(body);
      } else {
        const q = body.questions[0];
        resetForm();
        fillForm({ ...q, source_image: q.image || q.source_image || '' });
        openEditor();
        notify('Question digitised. Compare with the source, then preview and save.');
      }
    } catch (err) {
      notify(`Could not digitize the uploaded source: ${err.message}`);
    } finally {
      setUploadStatus(false);
    }
  };
  picker.click();
});
$('btn-close-editor').addEventListener('click', () => { $('editor').hidden = true; });
$('btn-print').addEventListener('click', () => window.print());
$('btn-export').addEventListener('click', () => { window.location.href = '/api/export'; });
$('import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const items = JSON.parse(await file.text());
  const res = await fetch('/api/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Array.isArray(items) ? items : [items]),
  });
  notify(res.ok ? 'Imported' : 'Import failed');
  e.target.value = '';
  await Promise.all([loadQuestions(), loadFacets()]);
});

let parsed = [];
let ocrReady = false;
let ocrHint = '';

function pdfItemHtml(q, index) {
  const count = Math.max(4, Math.min(12, (q.options || []).length));
  const opts = Array.from({ length: count }, (_, i) => `
    <div class="opt"><span>${OPTION_LABELS[i] || i + 1}</span>
      <textarea rows="1" data-idx="${index}" data-opt="${i}">${escapeHtml((q.options || [])[i] || '')}</textarea>
    </div>`).join('');
  const segments = (q.source_segments || []).length ? q.source_segments : (q.image ? [{ page: q.page, image: q.image }] : []);
  const crop = segments.length
    ? `<div class="crop">${segments.map((seg) => {
        const url = safeUrl(seg.image);
        return url ? `<div class="source-caption">Page ${seg.page || q.page} · Original crop<button type="button" class="image-expand" data-view-image="${url}">Expand source</button></div><div class="crop-frame"><img src="${url}" alt="Complete source crop from page ${seg.page || q.page}" /></div>` : '';
      }).join('')}</div>`
    : '<div class="crop"></div>';
  const vstatus = q.verification_status || 'UNVERIFIED';
  const score = Number(q.confidence || 0);
  const correctnessPercent = Math.round(score * 100);
  const correctnessBadge = score ? `<span class="verify ${String(vstatus).toLowerCase()}">Confidence ${correctnessPercent}%</span>` : `<span class="verify unverified">Confidence 0%</span>`;
  const issues = (q.verification_issues || []).map((i) =>
    `<div class="verify-issue ${escapeHtml(i.severity || 'warning')}"><strong>${escapeHtml(i.issue_type || 'review')}</strong>: ${escapeHtml(i.message || '')}${i.source_excerpt ? `<code>${escapeHtml(i.source_excerpt)}</code>` : ''}</div>`
  ).join('');
  const uncertainty = (q.uncertainties || []).map((u) => `<div class="verify-issue warning">Uncertain: ${escapeHtml(u)}</div>`).join('');
  const readyForReview = !!((q.statement || '').trim() || (q.answer || '').trim() || (q.options || []).some((o) => (o || '').trim()));
  return `<div class="pdf-item" data-item="${index}">
      <div class="pdf-head">
        <label class="inline"><input type="checkbox" aria-label="Include question" data-idx="${index}" data-pick="1" checked /> include</label>
        <strong>Q${q.number ?? '?'}</strong><span>page ${q.page}</span>
        <span class="verify ${String(vstatus).toLowerCase()}">${escapeHtml(vstatus)}</span>
        ${correctnessBadge}
        ${q.garbled ? '<span class="badge-warn">maths not readable as text — keep the image</span>' : ''}
        <div class="spacer"></div>
        <button data-idx="${index}" data-crop="1">Crop</button>
        <button data-idx="${index}" data-preview="1">${readyForReview ? 'Review' : 'Preview'}</button>
        <button data-idx="${index}" data-save="1" class="primary" ${readyForReview ? '' : 'disabled'}>Save</button>
        <button data-idx="${index}" data-ocr="1"${q.image && ocrReady ? '' : ' disabled'}
          title="${escapeHtml(ocrReady ? 'Drag a box over one formula in the crop to read it as LaTeX' : ocrHint)}">OCR maths</button>
      </div>
      <div class="pdf-fields" hidden>
        ${issues}${uncertainty}
        ${(q.visual_assets || []).length ? `<div class="detected-assets"><strong>Preserved visuals:</strong> ${(q.visual_assets || []).map((a) => escapeHtml(a.type || 'image')).join(', ')}${visualAssetsHtml(q)}</div>` : ''}
        <label>Statement<textarea rows="4" data-idx="${index}" data-field="statement">${escapeHtml(q.statement || '')}</textarea></label>
        ${opts}
        <label>Answer <input data-idx="${index}" data-field="answer" placeholder="B" value="${escapeHtml(q.answer || '')}" /></label>
        <label>Printed solution<textarea rows="3" data-idx="${index}" data-field="solution">${escapeHtml(q.solution || '')}</textarea></label>
      </div>
      <div class="pdf-preview question-card"></div>
      ${crop}
    </div>`;
}

function renderPdfPreview(index) {
  const q = parsed[index] || {};
  const item = $('pdf-list').querySelector(`.pdf-item[data-item="${index}"]`);
  const pane = item.querySelector('.pdf-preview');
  pane.innerHTML = cardHtml({
    ...q,
    id: `Q${q.number ?? '?'}`,
    options: (q.options || []).filter((o) => (o || '').trim()),
    source_image: '', hide_source: true, // Original crops are already shown in the adjacent source panel.
  }, true).replace(/<div class="card-actions">[\s\S]*<\/div>/, '');
  typeset(pane);
}

function openCompareModal(index) {
  const q = parsed[index] || {};
  const originalSegments = (q.source_segments || []).filter((seg) => safeUrl(seg.image));
  if (!originalSegments.length && safeUrl(q.image || q.source_image)) originalSegments.push({ image: q.image || q.source_image, page: q.page });
  const transformed = cardHtml({
    ...q,
    source_image: '', hide_source: true,
    id: `Q${q.number ?? '?'}`,
    options: (q.options || []).filter((o) => (o || '').trim()),
    confidence: Number(q.confidence || 0),
    verification_status: q.verification_status || 'UNVERIFIED',
  }, true).replace(/<div class="card-actions">[\s\S]*<\/div>/, '');

  $('compare-originals').innerHTML = originalSegments.map((seg) => {
    const url = safeUrl(seg.image);
    return `<figure class="source-image"><figcaption>Page ${escapeHtml(seg.page || q.page || '')} · Original crop</figcaption><img src="${url}" alt="Complete original crop" /><button class="image-expand" data-view-image="${url}">Expand source</button></figure>`;
  }).join('') || '<p class="muted">No original image available.</p>';
  $('compare-score').textContent = `Verification confidence: ${Math.round(Number(q.confidence || 0) * 100)}%`;
  $('compare-score').className = `verify ${String(q.verification_status || 'UNVERIFIED').toLowerCase()}`;
  $('compare-transformed').innerHTML = transformed;
  typeset($('compare-transformed'));
  $('compare-modal').hidden = false;
}

function togglePreview(index, show) {
  const item = $('pdf-list').querySelector(`.pdf-item[data-item="${index}"]`);
  if (!item) return;
  const preview = show ?? item.querySelector('.pdf-preview').hidden;
  if (preview) renderPdfPreview(index);
  item.querySelector('.pdf-preview').hidden = !preview;
  item.querySelector('.pdf-fields').hidden = preview;
  const reviewButton = item.querySelector('[data-preview]');
  if (reviewButton) reviewButton.textContent = preview ? 'Review' : 'Preview';
}

function modeNote(data) {
  if (data.llm) return `GCP: ${data.llm.model} transcription + independent verification${data.document_ai?.used ? ' + Document AI Math OCR' : ''}. Review orange/red items.`;
  if (data.source_document?.mime_type && data.source_document.mime_type !== 'application/pdf') return 'Image source loaded locally; configure Vertex AI for automatic transcription.';
  if ((data.formula_pages || []).length) return 'Equations preserved as inline images with editable text. Compare Preview with the original crop.';
  const ocr = (data.ocr_pages || []).length;
  if (!ocr) return `${data.pages || 0} page(s) read from the PDF text`;
  if (ocr === data.pages) return `all ${ocr} page(s) read with OCR`;
  return `${ocr} of ${data.pages} page(s) re-read with OCR`;
}

let cropTool = { index: null, source: '', crops: [], active: false, selectedIds: [] };

function renderCropPreviewList() {
  const list = $('crop-preview-list');
  if (!cropTool.source) {
    list.innerHTML = '<p class="muted">No source page selected.</p>';
    return;
  }
  if (!cropTool.crops.length) {
    list.innerHTML = '<p class="muted">No crop selected yet. Click “Add crop” and drag on the page.</p>';
    return;
  }
  const bulkButton = cropTool.selectedIds.length
    ? `<button class="primary" data-crop-bulk="digitize">Digitise selected (${cropTool.selectedIds.length})</button>`
    : '<button data-crop-bulk="digitize" disabled>Digitise selected (0)</button>';
  list.innerHTML = `${bulkButton}${cropTool.crops.map((crop) => `
    <div class="crop-preview-item">
      <label class="crop-select-toggle"><input type="checkbox" data-crop-toggle="1" data-crop-id="${crop.id}" ${cropTool.selectedIds.includes(crop.id) ? 'checked' : ''} /> Select</label>
      <img src="${safeUrl(crop.dataUrl)}" alt="Selected crop" />
      <div class="crop-actions">
        <button data-crop-action="digitize" data-crop-id="${crop.id}">Digitize</button>
        <button data-crop-action="remove" data-crop-id="${crop.id}">Remove</button>
      </div>
    </div>
  `).join('')}`;
}

function setCropMode(active) {
  cropTool.active = !!active;
  $('crop-add').textContent = cropTool.active ? 'Select region' : 'Add crop';
  $('crop-frame').classList.toggle('crop-active', cropTool.active);
}

function cropDataUrlFromRegion(img, region) {
  const [x0, y0, x1, y1] = region;
  const canvas = document.createElement('canvas');
  const width = Math.max(1, Math.round((x1 - x0) * img.naturalWidth || img.width || 1));
  const height = Math.max(1, Math.round((y1 - y0) * img.naturalHeight || img.height || 1));
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(
    img,
    x0 * (img.naturalWidth || img.width),
    y0 * (img.naturalHeight || img.height),
    (x1 - x0) * (img.naturalWidth || img.width),
    (y1 - y0) * (img.naturalHeight || img.height),
    0, 0, width, height
  );
  return canvas.toDataURL('image/png');
}

function addCropFromRegion(region) {
  const sourceImage = $('crop-image');
  if (!sourceImage.src || !sourceImage.complete) return;
  const img = new Image();
  img.onload = () => {
    const crop = {
      id: `crop-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      dataUrl: cropDataUrlFromRegion(img, region),
      region,
    };
    cropTool.crops.push(crop);
    cropTool.selectedIds.push(crop.id);
    renderCropPreviewList();
    setCropMode(false);
  };
  img.src = cropTool.source;
}

async function digitizeSingleCrop(crop) {
  const blob = await fetch(crop.dataUrl).then((r) => r.blob());
  const file = new File([blob], `crop-${Date.now()}.png`, { type: 'image/png' });
  const form = new FormData();
  form.append('file', file, file.name);
  form.append('mode', 'auto');
  const res = await fetch('/api/source/parse', { method: 'POST', body: form });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || 'digitization failed');
  if (!Array.isArray(body.questions) || body.questions.length < 1) {
    throw new Error('The selected crop did not produce a question.');
  }
  const hit = body.questions[0];
  return {
    ...hit,
    image: crop.dataUrl,
    source_image: crop.dataUrl,
    source_segments: [{ page: hit.page || 1, bbox: crop.region, image: crop.dataUrl }],
    source_bbox: crop.region,
    verification_status: 'HUMAN_REVIEWED',
    ready_for_review: true,
    human_modified: true,
  };
}

async function digitizeCropItem(cropId) {
  if (sourceBusy) return;
  const crop = cropTool.crops.find((item) => item.id === cropId);
  if (!crop) return;
  setUploadStatus(true, 'Digitizing question crop…');
  try {
    const hit = await digitizeSingleCrop(crop);
    const idx = cropTool.index ?? parsed.length;
    if (cropTool.index === null || cropTool.index === undefined) {
      parsed.push(hit);
    } else {
      parsed[idx] = { ...parsed[idx], ...hit };
    }
    const item = $('pdf-list').querySelector(`.pdf-item[data-item="${idx}"]`);
    if (item) item.outerHTML = pdfItemHtml(parsed[idx], idx);
    else {
      $('pdf-list').innerHTML = parsed.map(pdfItemHtml).join('');
    }
    parsed.forEach((_, i) => {
      renderPdfPreview(i);
      togglePreview(i, true);
    });
    $('crop-modal').hidden = true;
    $('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    notify(`Could not digitize this crop: ${err.message}`);
  } finally {
    setUploadStatus(false);
  }
}

async function digitizeSelectedCrops() {
  if (!cropTool.selectedIds.length) {
    alert('Select at least one crop before digitising.');
    return;
  }
  if (sourceBusy) return;
  const selected = cropTool.crops.filter((crop) => cropTool.selectedIds.includes(crop.id));
  if (!selected.length) return;
  setUploadStatus(true, 'Digitising selected question crops…');
  try {
    const results = [];
    for (const crop of selected) {
      const hit = await digitizeSingleCrop(crop);
      results.push(hit);
    }
    const baseIndex = cropTool.index ?? parsed.length;
    results.forEach((hit, offset) => {
      const idx = baseIndex + offset;
      parsed[idx] = { ...(parsed[idx] || {}), ...hit };
    });
    $('pdf-list').innerHTML = parsed.map(pdfItemHtml).join('');
    parsed.forEach((_, i) => {
      renderPdfPreview(i);
      togglePreview(i, true);
    });
    cropTool.crops = [];
    cropTool.selectedIds = [];
    renderCropPreviewList();
    $('crop-modal').hidden = true;
    $('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    alert(`Could not digitise selected crops: ${err.message}`);
  } finally {
    setUploadStatus(false);
  }
}

function switchReviewTab(tabName) {
  const isCrop = tabName === 'crop';
  const docPanel = $('review-documents-panel');
  const cropPanel = $('review-crop-panel');
  const tabs = [...document.querySelectorAll('.review-tab')];
  docPanel.hidden = isCrop;
  cropPanel.hidden = !isCrop;
  tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.reviewTab === tabName));
}

function openCropModal(index) {
  const q = parsed[index] || {};
  const source = (q.source_segments || []).find((seg) => safeUrl(seg.image))?.image || q.image || '';
  cropTool = { index, source, crops: [], active: false };
  $('crop-image').src = source;
  $('crop-modal').hidden = false;
  renderCropPreviewList();
  setCropMode(false);
}

async function openPdfModal(data) {
  parsed = data.questions || [];
  switchReviewTab('documents');
  const status = await refreshOcrStatus();
  switchMainTab('upload-crop');
  $('pdf-mode-note').textContent = modeNote(data);
  $('pdf-reocr').hidden = !(status.cloud || {}).available || data.source_document?.mime_type !== 'application/pdf';
  $('pdf-warnings').innerHTML = (data.warnings || [])
    .map((w) => `<div class="pdf-warning">${escapeHtml(w)}</div>`).join('');
  $('pdf-list').innerHTML = parsed.length
    ? parsed.map(pdfItemHtml).join('')
    : '<p class="muted">Nothing detected in this PDF.</p>';
  parsed.forEach((_, i) => {
    renderPdfPreview(i);
    togglePreview(i, true);
  });
  $('p-image-only').checked = !!data.mostly_garbled;
  $('pdf-list').scrollTop = 0;
  $('pdf-modal').hidden = false;
}

$('pdf-list').addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  const idx = Number(btn.dataset.idx);
  if (btn.dataset.crop) {
    openCropModal(idx);
    return;
  }
  if (btn.dataset.preview) {
    if (btn.textContent.trim() === 'Review') {
      togglePreview(idx, false);
      btn.textContent = 'Preview';
    } else {
      openCompareModal(idx);
    }
    return;
  }
  if (btn.dataset.save) {
    await saveSingleQuestion(idx);
    return;
  }
  if (!btn.dataset.ocr) return;
  togglePreview(idx, false);
  openOcrModal(idx);
});

$('crop-close').addEventListener('click', () => { $('crop-modal').hidden = true; $('crop-preview-list').innerHTML = ''; switchReviewTab('documents'); });
$('crop-add').addEventListener('click', () => setCropMode(!cropTool.active));
$('crop-digitize-selected')?.addEventListener('click', digitizeSelectedCrops);
$('crop-preview-list').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  const cropId = btn.dataset.cropId;
  if (btn.dataset.cropAction === 'remove') {
    cropTool.crops = cropTool.crops.filter((crop) => crop.id !== cropId);
    cropTool.selectedIds = cropTool.selectedIds.filter((id) => id !== cropId);
    renderCropPreviewList();
    return;
  }
  if (btn.dataset.cropAction === 'digitize') {
    digitizeCropItem(cropId);
    return;
  }
  if (btn.dataset.cropBulk === 'digitize') {
    digitizeSelectedCrops();
  }
});
$('crop-preview-list').addEventListener('change', (e) => {
  const checkbox = e.target.closest('[data-crop-toggle]');
  if (!checkbox) return;
  const { cropId } = checkbox.dataset;
  if (checkbox.checked) {
    if (!cropTool.selectedIds.includes(cropId)) cropTool.selectedIds.push(cropId);
  } else {
    cropTool.selectedIds = cropTool.selectedIds.filter((id) => id !== cropId);
  }
  renderCropPreviewList();
});

$('compare-close').addEventListener('click', () => { $('compare-modal').hidden = true; });

/* --- OCR: drag a box over one formula in an enlarged crop ---------------- */

let ocrIndex = null;

function openOcrModal(index) {
  ocrIndex = index;
  $('ocr-image').src = parsed[index].image;
  $('ocr-state').textContent = 'drag a box over a single formula';
  $('ocr-modal').hidden = false;
}

$('ocr-cancel').addEventListener('click', () => { $('ocr-modal').hidden = true; });

(function ocrSelection() {
  const frame = $('ocr-frame');
  const image = $('ocr-image');
  const box = document.createElement('div');
  box.className = 'ocr-box';
  let origin = null;

  const point = (event) => {
    const rect = image.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    ];
  };
  const place = (a, b) => {
    box.style.left = `${Math.min(a[0], b[0]) * 100}%`;
    box.style.top = `${Math.min(a[1], b[1]) * 100}%`;
    box.style.width = `${Math.abs(a[0] - b[0]) * 100}%`;
    box.style.height = `${Math.abs(a[1] - b[1]) * 100}%`;
  };

  image.addEventListener('mousedown', (event) => {
    event.preventDefault();
    if (!ocrIndex && ocrIndex !== 0) return;
    origin = point(event);
    frame.appendChild(box);
    place(origin, origin);
  });
  window.addEventListener('mousemove', (event) => { if (origin) place(origin, point(event)); });
  window.addEventListener('mouseup', async (event) => {
    if (origin === null) return;
    const end = point(event);
    const region = [
      Math.min(origin[0], end[0]),
      Math.min(origin[1], end[1]),
      Math.max(origin[0], end[0]),
      Math.max(origin[1], end[1]),
    ];
    origin = null;
    box.remove();
    if (region[2] - region[0] < 0.01 || region[3] - region[1] < 0.01) return;
    await runOcr(ocrIndex, region);
  });
}());

(function cropSelection() {
  const frame = $('crop-frame');
  const image = $('crop-image');
  const box = document.createElement('div');
  box.className = 'ocr-box';
  let origin = null;

  const point = (event) => {
    const rect = image.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    ];
  };
  const place = (a, b) => {
    box.style.left = `${Math.min(a[0], b[0]) * 100}%`;
    box.style.top = `${Math.min(a[1], b[1]) * 100}%`;
    box.style.width = `${Math.abs(a[0] - b[0]) * 100}%`;
    box.style.height = `${Math.abs(a[1] - b[1]) * 100}%`;
  };

  image.addEventListener('mousedown', (event) => {
    if (!cropTool.active || !cropTool.source) return;
    event.preventDefault();
    origin = point(event);
    frame.appendChild(box);
    place(origin, origin);
  });
  window.addEventListener('mousemove', (event) => { if (origin) place(origin, point(event)); });
  window.addEventListener('mouseup', (event) => {
    if (origin === null) return;
    const end = point(event);
    const region = [
      Math.min(origin[0], end[0]),
      Math.min(origin[1], end[1]),
      Math.max(origin[0], end[0]),
      Math.max(origin[1], end[1]),
    ];
    origin = null;
    box.remove();
    if (region[2] - region[0] < 0.01 || region[3] - region[1] < 0.01) return;
    addCropFromRegion(region);
  });
}());

async function runOcr(index, region) {
  $('ocr-state').textContent = 'reading…';
  try {
    const res = await fetch('/api/ocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: parsed[index].image, box: region }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.status);
    const field = $('pdf-list')
      .querySelector(`textarea[data-idx="${index}"][data-field="statement"]`);
    const at = field.selectionStart ?? field.value.length;
    field.value = `${field.value.slice(0, at)}${body.text}${field.value.slice(at)}`;
    parsed[index].statement = field.value;
    parsed[index].human_modified = true;
    parsed[index].verification_status = 'REVIEW';
    field.focus();
    field.selectionStart = field.selectionEnd = at + body.text.length;
    $('ocr-modal').hidden = true;
  } catch (err) {
    notify(`OCR failed: ${err.message}`);
  }
  $('ocr-state').textContent = 'drag a box over a single formula';
}

$('pdf-list').addEventListener('input', (e) => {
  const el = e.target;
  const idx = Number(el.dataset.idx);
  if (Number.isNaN(idx)) return;
  if (!el.dataset.field && el.dataset.opt === undefined) return;
  parsed[idx].human_modified = true;
  if (el.dataset.opt !== undefined) {
    parsed[idx].options = parsed[idx].options || [];
    parsed[idx].options[Number(el.dataset.opt)] = el.value;
  } else if (el.dataset.field) {
    parsed[idx][el.dataset.field] = el.value;
  }
});

let lastPdf = null;
let sourceBusy = false;

function setUploadStatus(isProcessing, message = 'Processing…') {
  sourceBusy = isProcessing;
  ['pdf-file', 'btn-digitize-image', 'pdf-local', 'pdf-reocr', 'crop-add'].forEach((id) => { $(id).disabled = isProcessing; });
  const status = $('upload-status');
  const text = status.querySelector('.upload-text');
  status.hidden = !isProcessing;
  text.textContent = message;
}

function showPdfLoadingState(message = 'Processing document…') {
  switchMainTab('upload-crop');
  $('pdf-modal').hidden = false;
  $('pdf-mode-note').textContent = message;
  $('pdf-warnings').innerHTML = '<div class="pdf-warning">Uploading and parsing the document. This may take a few seconds.</div>';
  $('pdf-list').innerHTML = `
    <div class="pdf-item">
      <div class="pdf-head">
        <span class="pdf-status">Loading pages…</span>
      </div>
      <div class="crop"><div class="spinner" aria-hidden="true"></div> Preparing the scrollable document preview.</div>
    </div>
  `;
}

async function readPdf(file, mode) {
  if (sourceBusy) { notify('Please wait for the current source to finish.'); return; }
  const form = new FormData();
  form.append('file', file, file.name);
  form.append('mode', mode);
  const label = document.querySelector('label[for="pdf-file"]');
  label.textContent = 'Digitizing source…';
  showPdfLoadingState('Processing document…');
  setUploadStatus(true, 'Processing PDF… This may take a few seconds.');
  try {
    const res = await fetch('/api/source/parse', { method: 'POST', body: form });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    lastPdf = file;
    switchMainTab('upload-crop');
    await openPdfModal(await res.json());
  } catch (err) {
    $('pdf-list').innerHTML = '<div class="empty-state"><h3>Source could not be processed</h3><p>Try another file or check your extraction configuration.</p></div>';
    $('pdf-mode-note').textContent = 'Processing failed';
    notify(`Could not digitize source: ${err.message}`);
  } finally {
    label.textContent = 'Upload document';
    setUploadStatus(false);
  }
}

$('pdf-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = '';
  if (/\.pdf$/i.test(file.name)) {
    await previewPdfDocument(file);
    return;
  }
  $('pdf-viewer').hidden = true;
  await readPdf(file, 'auto');
  if ($('pdf-modal') && !$('pdf-modal').hidden) {
    $('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

$('pdf-local').addEventListener('click', async () => {
  if (lastPdf) await readPdf(lastPdf, 'text');
});

$('pdf-reocr').addEventListener('click', async () => {
  if (!lastPdf || lastPdf.type !== 'application/pdf') return;
  $('pdf-mode-note').textContent = 'reading pages with OCR…';
  await readPdf(lastPdf, 'ocr');
});

$('pdf-cancel').addEventListener('click', () => { $('pdf-modal').hidden = true; });

function questionPayloadFromIndex(index) {
  const q = parsed[index];
  if (!q || q.saved) return null;
  const keepImage = $('p-keep-image').checked;
  const imageOnly = $('p-image-only').checked;
  const image = q.image ? `![Q${q.number ?? ''} from paper](${q.image})` : '';
  const body = imageOnly && image ? image : (q.statement || '');
  return {
    subject: $('p-subject').value, chapter: $('p-chapter').value.trim(),
    exam: $('p-exam').value.trim(), year: $('p-year').value.trim(),
    qtype: q.qtype || $('p-qtype').value, tags: $('p-tags').value.trim(),
    statement: body,
    options: (q.options || []).filter((o) => (o || '').trim()),
    answer: q.answer || '',
    solution: q.solution || '',
    source_image: keepImage ? (q.image || '') : '',
    source_segments: keepImage ? (q.source_segments || []) : [],
    source_document_id: q.source_document_id || '', source_document_sha256: q.source_document_sha256 || '',
    source_page: q.source_page || q.page || 0, source_bbox: q.source_bbox || [],
    extraction_run_id: q.extraction_run_id || '', extraction_provider: q.extraction_provider || '',
    extraction_model: q.extraction_model || '', verification_status: q.human_modified ? 'REVIEW' : (q.verification_status || 'UNVERIFIED'),
    confidence: Number(q.confidence || 0), verification_issues: q.verification_issues || [],
    uncertainties: q.uncertainties || [], content_blocks: q.content_blocks || [],
    visual_assets: q.visual_assets || [], math_evidence: q.math_evidence || [],
  };
}

async function importSelectedQuestionsRequest() {
  const picked = [...$('pdf-list').querySelectorAll('[data-pick]')]
    .filter((cb) => cb.checked && !parsed[Number(cb.dataset.idx)]?.saved).map((cb) => Number(cb.dataset.idx));
  if (!picked.length) return;
  const items = picked.map((i) => questionPayloadFromIndex(i)).filter(Boolean);
  if (!items.length) return;
  const res = await fetch('/api/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  });
  if (!res.ok) {
    notify('Import failed');
    return;
  }
  picked.forEach((i) => { parsed[i].saved = true; });
  $('pdf-modal').hidden = true;
  switchMainTab('questions');
  notify(`${items.length} question(s) saved to your library.`);
  await Promise.all([loadQuestions(), loadFacets()]);
}

async function saveSingleQuestionRequest(index) {
  const payload = questionPayloadFromIndex(index);
  if (!payload) return;
  const res = await fetch('/api/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify([payload]),
  });
  if (!res.ok) {
    notify('Save failed');
    return;
  }
  const item = $('pdf-list').querySelector(`.pdf-item[data-item="${index}"]`);
  if (item) {
    const saveBtn = item.querySelector('[data-save]');
    if (saveBtn) {
      saveBtn.textContent = 'Saved';
      saveBtn.disabled = true;
      parsed[index].saved = true;
      const checkbox = item.querySelector('[data-pick]');
      checkbox.checked = false;
      checkbox.disabled = true;
    }
  }
  await Promise.all([loadQuestions(), loadFacets()]);
}

let savingQuestions = false;
async function runSave(action) {
  if (savingQuestions) return;
  savingQuestions = true;
  const buttons = [...document.querySelectorAll('#btn-save, #pdf-import, #pdf-save, [data-save]')];
  const prior = buttons.map((button) => button.disabled);
  buttons.forEach((button) => { button.disabled = true; });
  try { await action(); }
  catch (err) { notify(`Could not save: ${err.message}. Please try again.`); }
  finally {
    savingQuestions = false;
    buttons.forEach((button, i) => {
      button.disabled = prior[i] || (button.dataset.save !== undefined && !!parsed[Number(button.dataset.idx)]?.saved);
    });
    syncSaveState();
  }
}
function save() { return runSave(saveRequest); }
function saveSingleQuestion(index) { return runSave(() => saveSingleQuestionRequest(index)); }
function importSelectedQuestions() { return runSave(importSelectedQuestionsRequest); }

$('pdf-import').addEventListener('click', importSelectedQuestions);
$('pdf-save').addEventListener('click', importSelectedQuestions);
document.querySelectorAll('.review-tab').forEach((tab) => {
  tab.addEventListener('click', () => switchReviewTab(tab.dataset.reviewTab));
});

let searchTimer;
$('page-prev').addEventListener('click', () => { pageOffset = Math.max(0, pageOffset - PAGE_SIZE); loadQuestions(); });
$('page-next').addEventListener('click', () => { pageOffset += PAGE_SIZE; loadQuestions(); });
$('back-to-review').addEventListener('click', () => switchReviewTab('documents'));
['s-q', 's-subject', 's-chapter', 's-difficulty'].forEach((id) => {
  $(id).addEventListener('input', () => {
    pageOffset = 0;
    ++searchRequest;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadQuestions, id === 's-q' ? 250 : 0);
  });
});
$('s-answers').addEventListener('change', renderList);
$('s-originals').addEventListener('change', renderList);
$('pdf-preview-all').addEventListener('click', () => {
  const showing = $('pdf-list').querySelector('.pdf-preview:not([hidden])');
  parsed.forEach((_, i) => togglePreview(i, !showing));
});

async function refreshOcrStatus() {
  const status = await fetch('/api/ocr/status').then((r) => r.json()).catch(() => ({}));
  ocrReady = !!status.available;
  ocrHint = `Math OCR is not configured (${status.hint || 'no backend'})`;
  return status;
}

function switchMainTab(tabName) {
  $('pdf-modal').hidden = tabName !== 'upload-crop' || !(parsed.length || sourceBusy);
  const panels = {
    questions: $('questions-panel'),
    'upload-crop': $('upload-crop-panel'),
  };
  const tabs = [...document.querySelectorAll('.main-tab')];
  Object.entries(panels).forEach(([name, panel]) => {
    if (!panel) return;
    const active = name === tabName;
    panel.hidden = !active;
    panel.classList.toggle('active', active);
  });
  tabs.forEach((tab) => {
    const active = tab.dataset.mainTab === tabName;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-pressed', String(active));
  });
}

document.querySelectorAll('.main-tab').forEach((tab) => {
  tab.addEventListener('click', () => switchMainTab(tab.dataset.mainTab));
});

$('btn-open-review')?.addEventListener('click', () => {
  switchMainTab('upload-crop');
  if (!parsed.length) { $('pdf-file').click(); return; }
  if ($('pdf-modal')) {
    $('pdf-modal').hidden = false;
    $('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

window.addEventListener('load', async () => {
  resetForm();
  syncSaveState();
  switchMainTab('questions');
  await Promise.all([loadQuestions(), loadFacets(), refreshOcrStatus()]);
});

// Keep keyboard navigation available for upload actions and overlay dismissal.
document.querySelectorAll('label.btn[for]').forEach((label) => {
  label.tabIndex = 0;
  label.setAttribute('role', 'button');
  label.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const input = document.getElementById(label.htmlFor);
      if (input && !input.disabled) input.click();
    }
  });
});
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const overlay = ['ocr-modal', 'crop-modal', 'compare-modal'].map($).find((el) => !el.hidden);
  if (overlay) overlay.hidden = true;
});

let imageViewerOpener = null;
function closeImageViewer() {
  $('image-viewer-modal').hidden = true;
  $('image-viewer-img').removeAttribute('src');
  imageViewerOpener?.focus();
}
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-view-image]');
  if (!button) return;
  const url = safeUrl(button.dataset.viewImage);
  if (!url) return;
  imageViewerOpener = button;
  $('image-viewer-img').src = button.dataset.viewImage;
  $('image-viewer-modal').hidden = false;
  $('image-viewer-close').focus();
});
$('image-viewer-close').addEventListener('click', closeImageViewer);
$('image-viewer-modal').addEventListener('click', (event) => {
  if (event.target === $('image-viewer-modal')) closeImageViewer();
});
$('image-viewer-modal').addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { event.stopPropagation(); closeImageViewer(); }
  if (event.key === 'Tab') { event.preventDefault(); $('image-viewer-close').focus(); }
});
