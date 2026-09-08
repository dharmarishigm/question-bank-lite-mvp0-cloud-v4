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
function renderMarkdownBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      const match = line.match(/^(#{1,6})\s+(.*)$/);
      if (match) {
        const level = Math.min(6, match[1].length);
        blocks.push(`<h${level}>${match[2].trim()}</h${level}>`);
        i += 1;
        continue;
      }
    }
    if (/^>\s?/.test(line)) {
      const items = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        items.push(lines[i].replace(/^>\s?/, '').trim());
        i += 1;
      }
      blocks.push(`<blockquote>${items.join('<br>')}</blockquote>`);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^[-*]\s+/, '').trim()}</li>`);
        i += 1;
      }
      blocks.push(`<ul>${items.join('')}</ul>`);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^\d+\.\s+/, '').trim()}</li>`);
        i += 1;
      }
      blocks.push(`<ol>${items.join('')}</ol>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^#{1,6}\s+/.test(lines[i]) && !/^>\s?/.test(lines[i]) && ! /^[-*]\s+/.test(lines[i]) && !/^\d+\.\s+/.test(lines[i])) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    if (paragraph.length) {
      blocks.push(`<p>${paragraph.join('<br>')}</p>`);
    }
  }
  return blocks.join('');
}

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
  text = renderMarkdownBlocks(text);
  text = renderTables(text.split('\n')).join('\n');
  text = text.replace(/\n{2,}/g, '<br><br>').replace(/\n(?!<\/?table|<tbody|<thead|<tr|<h|<p|<ul|<ol|<blockquote)/g, '<br>');
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

function scrollToPageTop() {
  window.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
  const appHeader = document.querySelector('header');
  if (appHeader) appHeader.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function openEditor() {
  switchMainTab('edit');
  $('editor-modal').hidden = false;
  $('editor').hidden = false;
  $('editor').dataset.activeDraft = 'true';
  scrollToPageTop();
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
  const sourceType = q.source_type === 'AI_GENERATED' ? '<span class="badge">AI Generated</span>' : '';
  return `<div class="meta">${sourceType}${meta}${status}${blockSummaryHtml(q)}<span>#${q.id}</span></div>
    <div class="rendered">${toHtml(q.statement)}</div>${visualAssetsHtml(q)}${opts}${answer}${source}
    <div class="card-actions">
      <button data-edit="${q.id}">Edit</button>
      <button data-explain="${q.id}">Explain</button>
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
  $('preview').innerHTML = cardHtml({ ...q, id: editingId ?? 'new', hide_source: true }, true);
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
  scrollToPageTop();
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

function renderStructuredExplanation(target, body) {
  target.lang=body?.language==='te'?'te':'en';
  const data = body?.structured;
  target.dataset.rawExplanation = body?.explanation || '';
  target.dataset.structured = data ? JSON.stringify(data) : '';
  if (!data) {
    target.innerHTML = toHtml(body?.explanation || 'No explanation available.');
    typeset(target);
    return;
  }
  const section = (icon, title, value, kind = '') => value ? `<section class="explain-section ${kind}"><div class="explain-section-title"><span aria-hidden="true">${icon}</span><h3>${escapeHtml(title)}</h3></div><div class="rendered">${toHtml(value)}</div></section>` : '';
  const steps = (data.steps || []).map((step, index) => `<li><span>${index + 1}</span><div class="rendered">${toHtml(step)}</div></li>`).join('');
  const distractors = (data.distractors || []).map(item => `<li><strong>${escapeHtml(item.option || 'Option')}</strong><div class="rendered">${toHtml(item.reason)}</div></li>`).join('');
  const references = (data.references || []).map(item => `<li class="rendered">${toHtml(item)}</li>`).join('');
  target.innerHTML = `<article class="structured-explanation"><header class="explain-hero"><span class="explain-eyebrow">Concept mastery</span><h2>${escapeHtml(data.title)}</h2><div class="rendered">${toHtml(data.summary)}</div></header>${section('💡','Core concept',data.concept,'concept')}${steps ? `<section class="explain-section"><div class="explain-section-title"><span aria-hidden="true">🧩</span><h3>Step-by-step reasoning</h3></div><ol class="explain-steps">${steps}</ol></section>` : ''}${section('✓','Why this answer is correct',data.correct_answer,'correct')}${distractors ? `<section class="explain-section distractors"><div class="explain-section-title"><span aria-hidden="true">🔍</span><h3>Why the other options do not fit</h3></div><ul>${distractors}</ul></section>` : ''}${section('📘','Useful background',data.background)}${section('🎯','Remember this',data.memory_tip,'memory-tip')}${references ? `<section class="explain-section references"><div class="explain-section-title"><span aria-hidden="true">🔖</span><h3>Learn more</h3></div><ul>${references}</ul></section>` : ''}</article>`;
  typeset(target);
}

async function openExplainModal(questionId) {
  const explainContent = $('explain-content');
  $('explain-like').hidden = false;
  explainContent.textContent = 'Preparing an explanation...';
  $('explain-modal').hidden = false;
  $('explain-like').dataset.questionId = String(questionId);
  $('explain-modal').dataset.questionId = String(questionId);
  delete $('explain-modal').dataset.studentReview;
  $('explain-like').disabled = false;
  try {
    const language = $('explain-language')?.value || 'en';
    const res = await fetch(`/api/questions/${questionId}/explain?language=${encodeURIComponent(language)}`);
    const rawText = await res.text();
    let body = {};
    if (rawText) {
      try {
        body = JSON.parse(rawText);
      } catch {
        body = { explanation: rawText };
      }
    }
    if (!res.ok) {
      const detail = body?.detail || body?.error || body?.message || rawText || 'Could not load explanation.';
      throw new Error(detail);
    }
    body.explanation = body.explanation || body?.message || 'No explanation available.';
    renderStructuredExplanation(explainContent, body);
    if (body.cached) {
      $('explain-like').textContent = 'Saved';
      $('explain-like').disabled = true;
    } else {
      $('explain-like').textContent = 'Like & save';
      $('explain-like').disabled = false;
    }
  } catch (err) {
    explainContent.textContent = err.message || 'Could not load explanation.';
    $('explain-like').disabled = true;
  }
}

async function saveLikedExplanation() {
  const questionId = $('explain-like')?.dataset.questionId;
  const explainContent = $('explain-content');
  if (!questionId || !explainContent) return;
  const explanation = explainContent.dataset.rawExplanation || explainContent.innerText || explainContent.textContent || '';
  const structured = explainContent.dataset.structured ? JSON.parse(explainContent.dataset.structured) : null;
  if (!explanation.trim()) {
    notify('There is no explanation to save yet.');
    return;
  }
  try {
    const res = await fetch(`/api/questions/${questionId}/explain/like`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ explanation, structured, language: $('explain-language')?.value || 'en' }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || 'Could not save the explanation.');
    $('explain-like').textContent = 'Saved';
    $('explain-like').disabled = true;
    notify('Explanation saved for reuse.');
  } catch (err) {
    notify(err.message || 'Could not save the explanation.');
  }
}

$('list').addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  if (btn.dataset.edit) {
    const q = questions.find((item) => String(item.id) === btn.dataset.edit);
    if (!q) return;
    editingId = q.id;
    $('editor-title').textContent = `Editing question #${q.id}`;
    fillForm(q);
    openEditor();
  }
  if (btn.dataset.explain) {
    await openExplainModal(btn.dataset.explain);
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
$('btn-close-editor').addEventListener('click', () => {
  $('editor-modal').hidden = true;
  $('editor').hidden = true;
  $('editor').dataset.activeDraft = 'false';
  switchMainTab('questions');
});
$('explain-close').addEventListener('click', () => { $('explain-modal').hidden = true; });
$('explain-like')?.addEventListener('click', saveLikedExplanation);
$('explain-language')?.addEventListener('change', () => {
  const modal = $('explain-modal'), questionId = modal?.dataset.questionId;
  if (questionId && !modal.hidden && modal.dataset.studentReview !== '1') openExplainModal(questionId);
});
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
  const status = await refreshOcrStatus().catch(()=>({cloud:{available:false}}));
  $('upload-crop-panel').append($('pdf-modal'));
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
  $('pdf-modal').scrollIntoView({block:'start',behavior:'smooth'});
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
  $('upload-crop-panel').append($('pdf-modal'));
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

async function loadExamRegistrations() {
  const list = $('exam-registration-list');
  const search = $('exam-search');
  if (!list) return;
  list.innerHTML = '<p class="muted">Loading registrations…</p>';
  try {
    const params = new URLSearchParams();
    if (search && search.value.trim()) params.set('query', search.value.trim());
    const res = await fetch(`/api/exam-registrations${params.toString() ? `?${params}` : ''}`);
    if (!res.ok) throw new Error('Could not load registration data');
    const items = await res.json();
    if (!items.length) {
      list.innerHTML = '<div class="empty-state"><span class="empty-icon" aria-hidden="true">E</span><h3>No registrations yet</h3><p>Register an individual candidate to start the exam workflow.</p></div>';
      await loadExamAnalytics();
      return;
    }
    list.innerHTML = items.map((item) => `
      <div class="exam-registration-item">
        <div class="exam-registration-header">
          <strong>${escapeHtml(item.full_name || 'Unnamed candidate')}</strong>
          <span class="status-pill ${escapeHtml(item.status || 'pending')}">${escapeHtml(item.status || 'pending')}</span>
        </div>
        <div class="exam-registration-meta">
          <span>Date of birth: ${escapeHtml(item.date_of_birth || 'Not provided')}</span>
        </div>
        <div class="exam-registration-meta smaller">
          <span>${escapeHtml(item.email || 'No email')}</span>
        </div>
        ${item.notes ? `<p class="exam-registration-notes">${escapeHtml(item.notes)}</p>` : ''}
        <div class="card-actions">
          <button type="button" data-exam-approve="${item.id}">Approve</button>
          <button type="button" data-exam-reject="${item.id}">Reject</button>
          <button type="button" data-exam-edit="${item.id}">Edit</button>
          <button type="button" data-exam-delete="${item.id}">Delete</button>
        </div>
      </div>
    `).join('');
    await loadExamAnalytics();
  } catch (err) {
    list.innerHTML = `<div class="empty-state"><h3>Unable to load registrations</h3><p>${escapeHtml(err.message || 'Please try again.')}</p></div>`;
  }
}

async function loadExamAnalytics() {
  const analytics = $('exam-analytics');
  if (!analytics) return;
  try {
    const res = await fetch('/api/exam-registrations/analytics');
    if (!res.ok) throw new Error('Could not load analytics');
    const data = await res.json();
    const cards = [
      { label: 'Total', value: data.total ?? 0 },
      { label: 'Pending', value: data.status_counts?.pending ?? 0 },
      { label: 'Approved', value: data.status_counts?.approved ?? 0 },
      { label: 'Rejected', value: data.status_counts?.rejected ?? 0 },
    ];
    const byExam = (data.by_exam || []).slice(0, 5);
    analytics.innerHTML = `
      <div class="exam-analytics-card"><h4>Total registrations</h4><strong>${cards[0].value}</strong></div>
      <div class="exam-analytics-card"><h4>Pending</h4><strong>${cards[1].value}</strong></div>
      <div class="exam-analytics-card"><h4>Approved</h4><strong>${cards[2].value}</strong></div>
      <div class="exam-analytics-card"><h4>Rejected</h4><strong>${cards[3].value}</strong></div>
      <div class="exam-analytics-card" style="grid-column: 1 / -1;"><h4>Top exam groups</h4><ul class="exam-analytics-list">${byExam.length ? byExam.map((item) => `<li>${escapeHtml(item.exam_name)} — ${item.count}</li>`).join('') : '<li>No exam data</li>'}</ul></div>
    `;
  } catch (err) {
    analytics.innerHTML = '<div class="exam-analytics-card"><h4>Analytics</h4><p class="muted">Unavailable right now.</p></div>';
  }
}

const EXAM_TIME_SECONDS = 30 * 60;
const examState = {
  questions: [],
  currentIndex: 0,
  answers: {},
  markedForReview: new Set(),
  timerId: null,
  timeRemaining: EXAM_TIME_SECONDS,
  started: false,
  submitted: false,
};

function renderExamPaper(questions) {
  const container = $('exam-paper-preview');
  if (!container) return;
  if (!questions || !questions.length) {
    container.innerHTML = '<div class="empty-state"><h3>No exam paper generated</h3><p>There are not enough valid questions in the question bank yet.</p></div>';
    return;
  }
  container.innerHTML = `
    <div class="exam-paper-header">
      <strong>Randomised 15-question paper</strong>
      <span>${questions.length} questions</span>
    </div>
    <ol class="exam-paper-list">
      ${questions.map((q, idx) => `
        <li class="exam-paper-item">
          <div class="exam-paper-meta"><span>${escapeHtml(q.subject || 'General')}</span><span>${escapeHtml(q.chapter || 'General')}</span><span>${escapeHtml(q.difficulty || 'medium')}</span></div>
          <div class="rendered">${toHtml(q.statement || '')}</div>
          <ol class="exam-option-list">
            ${(q.options || []).map((option, optionIndex) => `<li><span class="option-label">${OPTION_LABELS[optionIndex] || optionIndex + 1}.</span> <span class="rendered">${toHtml(option || '')}</span></li>`).join('')}
          </ol>
        </li>
      `).join('')}
    </ol>
  `;
  container.querySelectorAll('.rendered').forEach((node) => typeset(node));
}

function formatExamTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function normalizeExamChoice(value) {
  return String(value || '').trim().toUpperCase();
}

function loadExamPaperIntoTab() {
  const preview = $('exam-paper-preview-tab');
  if (!preview) return Promise.resolve([]);
  preview.innerHTML = '<p class="muted">Generating a realistic 15-question paper…</p>';
  return fetch('/api/exam-registrations/sample-paper')
    .then((res) => {
      if (!res.ok) throw new Error('Could not load the exam paper');
      return res.json();
    })
    .then((body) => {
      const questions = body.questions || [];
      renderExamPaperToTab(preview, questions);
      return questions;
    })
    .catch((err) => {
      preview.innerHTML = `<div class="empty-state"><h3>Exam paper unavailable</h3><p>${escapeHtml(err.message || 'Please try again.')}</p></div>`;
      return [];
    });
}

function renderExamPaperToTab(container, questions) {
  if (!container) return;
  if (!questions || !questions.length) {
    container.innerHTML = '<div class="empty-state"><h3>No exam paper generated</h3><p>There are not enough valid questions in the question bank yet.</p></div>';
    return;
  }
  container.innerHTML = `
    <div class="exam-paper-header">
      <strong>Randomised 15-question paper</strong>
      <span>${questions.length} questions</span>
    </div>
    <ol class="exam-paper-list">
      ${questions.map((q) => `
        <li class="exam-paper-item">
          <div class="exam-paper-meta"><span>${escapeHtml(q.subject || 'General')}</span><span>${escapeHtml(q.chapter || 'General')}</span><span>${escapeHtml(q.difficulty || 'medium')}</span></div>
          <div class="rendered">${toHtml(q.statement || '')}</div>
          <ol class="exam-option-list">
            ${(q.options || []).map((option, optionIndex) => `<li><span class="option-label">${OPTION_LABELS[optionIndex] || optionIndex + 1}.</span> <span class="rendered">${toHtml(option || '')}</span></li>`).join('')}
          </ol>
        </li>
      `).join('')}
    </ol>
  `;
  container.querySelectorAll('.rendered').forEach((node) => typeset(node));
}

function getExamQuestionKey(index) {
  const question = examState.questions[index];
  if (!question) return `exam-q-${index}`;
  if (!question._examKey) {
    const base = question.id ?? question.number ?? `question-${index}`;
    question._examKey = `exam-q-${index}-${String(base)}`;
  }
  return question._examKey;
}

function renderExamNav() {
  const nav = $('exam-question-nav');
  if (!nav) return;
  nav.innerHTML = examState.questions.map((question, index) => {
    const questionKey = getExamQuestionKey(index);
    const selected = examState.answers[questionKey] ?? '';
    const isActive = index === examState.currentIndex;
    const isAnswered = String(selected).trim() !== '';
    const isReview = examState.markedForReview.has(index);
    const classes = ['exam-question-pill'];
    if (isActive) classes.push('active');
    if (isAnswered) classes.push('answered');
    if (isReview) classes.push('review');
    return `<button type="button" class="${classes.join(' ')}" data-exam-jump="${index}">${index + 1}</button>`;
  }).join('');
}

function renderExamCurrentQuestion() {
  const container = $('exam-current-question');
  if (!container || !examState.questions.length) return;
  const question = examState.questions[examState.currentIndex];
  const questionNumber = question.number || examState.currentIndex + 1;
  const questionKey = getExamQuestionKey(examState.currentIndex);
  const selected = examState.answers[questionKey] ?? '';
  const isReview = examState.markedForReview.has(examState.currentIndex);
  const optionEntries = (question.options || []).map((option, index) => {
    const label = OPTION_LABELS[index] || String(index + 1);
    const checked = normalizeExamChoice(selected) === normalizeExamChoice(label) ? 'checked' : '';
    return `
      <li class="exam-option-item">
        <input type="radio" name="exam-choice-${questionKey}" value="${escapeHtml(label)}" ${checked} />
        <span class="exam-option-label">${escapeHtml(label)}</span>
        <span class="rendered">${toHtml(option || '')}</span>
      </li>
    `;
  }).join('');

  container.innerHTML = `
    <div class="exam-question-meta">
      <span>Question ${questionNumber}</span>
      <span>${escapeHtml(question.subject || 'General')}</span>
      <span>${escapeHtml(question.chapter || 'General')}</span>
      <span>${isReview ? 'Marked for review' : 'Standard view'}</span>
    </div>
    <div class="rendered">${toHtml(question.statement || '')}</div>
    <ul class="exam-option-list-compact">${optionEntries}</ul>
  `;
  container.querySelectorAll('.rendered').forEach((node) => typeset(node));
  $('exam-progress-text').textContent = `Question ${examState.currentIndex + 1} of ${examState.questions.length}`;
}

function renderExamSession() {
  const session = $('exam-session');
  const empty = $('exam-session-empty');
  if (!session) return;
  if (!examState.started || !examState.questions.length) {
    session.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  session.hidden = false;
  $('exam-timer').textContent = formatExamTime(examState.timeRemaining);
  renderExamNav();
  renderExamCurrentQuestion();
}

function saveExamAnswer(questionKey, value) {
  const answerKey = normalizeExamChoice(value);
  if (!answerKey) return;
  examState.answers[questionKey] = answerKey;
  renderExamNav();
  renderExamCurrentQuestion();
}

function toggleMarkForReview() {
  if (!examState.questions.length) return;
  const index = examState.currentIndex;
  if (examState.markedForReview.has(index)) {
    examState.markedForReview.delete(index);
  } else {
    examState.markedForReview.add(index);
  }
  renderExamNav();
  renderExamCurrentQuestion();
  const sessionId=$('exam-current-question')?.dataset.session;
  if(sessionId){const question=examState.questions[index];fetch(`/api/student/sessions/${sessionId}/questions/${question.id}/review`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({marked:examState.markedForReview.has(index)})}).catch(()=>notify('Could not save review status.'));}
}

function clearCurrentAnswer() {
  const questionKey = getExamQuestionKey(examState.currentIndex);
  delete examState.answers[questionKey];
  const sessionId=$('exam-current-question')?.dataset.session;
  if(sessionId){const question=examState.questions[examState.currentIndex];fetch(`/api/sessions/${sessionId}/answers/${question.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_answer:''})}).catch(()=>notify('Could not clear saved answer.'));}
  renderExamNav();
  renderExamCurrentQuestion();
}

function moveExamQuestion(nextIndex) {
  if (!examState.questions.length) return;
  examState.currentIndex = Math.max(0, Math.min(examState.questions.length - 1, nextIndex));
  renderExamSession();
}

function stopExamTimer() {
  if (examState.timerId) {
    clearInterval(examState.timerId);
    examState.timerId = null;
  }
}

function submitExamSession(force = false) {
  if (!examState.started || examState.submitted) return;
  if (!force && !confirm('Submit the exam now? You cannot change answers after submission.')) return;
  stopExamTimer();
  examState.submitted = true;
  const total = examState.questions.length;
  const score = examState.questions.reduce((sum, question, index) => {
    const questionKey = getExamQuestionKey(index);
    const selected = normalizeExamChoice(examState.answers[questionKey] ?? '');
    const correct = normalizeExamChoice(question.answer || '');
    return sum + (selected && selected === correct ? 1 : 0);
  }, 0);

  const reviewCount = examState.markedForReview.size;
  const answeredCount = Object.keys(examState.answers).length;
  const summary = $('exam-session');
  if (summary) {
    summary.innerHTML = `
      <div class="exam-summary">
        <div class="exam-summary-box">
          <h3>Exam submitted</h3>
          <p class="muted">Your final submission has been recorded.</p>
        </div>
        <div class="exam-summary-grid">
          <div class="exam-summary-stat"><small>Score</small><strong>${score}/${total}</strong></div>
          <div class="exam-summary-stat"><small>Answered</small><strong>${answeredCount}</strong></div>
          <div class="exam-summary-stat"><small>Review</small><strong>${reviewCount}</strong></div>
          <div class="exam-summary-stat"><small>Time left</small><strong>${formatExamTime(examState.timeRemaining)}</strong></div>
        </div>
        <div class="exam-review-list-wrap">
          <h3>Question review</h3>
          <ul class="exam-review-list">
            ${examState.questions.map((question, index) => {
              const questionKey = getExamQuestionKey(index);
              const selected = normalizeExamChoice(examState.answers[questionKey] ?? '');
              const correct = normalizeExamChoice(question.answer || '');
              const status = selected && selected === correct ? 'Correct' : (selected ? 'Incorrect' : 'Unanswered');
              return `<li><span>Q${index + 1}</span><strong>${escapeHtml(status)}</strong></li>`;
            }).join('')}
          </ul>
        </div>
      </div>
    `;
  }
  notify(`Exam submitted. Final score: ${score}/${total}.`);
}

async function startExamSession() {
  const sessionEmpty = $('exam-session-empty');
  const questions = examState.questions.length ? examState.questions : await loadExamPaperIntoTab();
  if (!questions.length) {
    notify('No questions are available to start the exam yet.');
    return;
  }

  examState.questions = questions.slice(0, 15).map((question, index) => ({
    ...question,
    _examKey: `exam-q-${index}-${String(question.id ?? question.number ?? `question-${index}`)}`,
  }));
  examState.currentIndex = 0;
  examState.answers = {};
  examState.markedForReview = new Set();
  examState.timeRemaining = EXAM_TIME_SECONDS;
  examState.started = true;
  examState.submitted = false;

  if (sessionEmpty) sessionEmpty.hidden = true;
  $('exam-session').hidden = false;
  $('exam-timer').textContent = formatExamTime(examState.timeRemaining);

  examState.timerId = setInterval(() => {
    if (!examState.started || examState.submitted) return;
    examState.timeRemaining -= 1;
    $('exam-timer').textContent = formatExamTime(examState.timeRemaining);
    if (examState.timeRemaining <= 0) {
      submitExamSession(true);
    }
  }, 1000);

  renderExamSession();
  notify('Exam started. You have 30 minutes to complete 15 questions.');
}

async function loadExamPaper() {
  const preview = $('exam-paper-preview');
  if (!preview) return;
  preview.innerHTML = '<p class="muted">Generating a realistic 15-question paper…</p>';
  try {
    const res = await fetch('/api/exam-registrations/sample-paper');
    if (!res.ok) throw new Error('Could not load the exam paper');
    const body = await res.json();
    renderExamPaper(body.questions || []);
  } catch (err) {
    preview.innerHTML = `<div class="empty-state"><h3>Exam paper unavailable</h3><p>${escapeHtml(err.message || 'Please try again.')}</p></div>`;
  }
}

async function requestExamConfirmation() {
  const form = $('exam-registration-form');
  const email = $('exam-email').value.trim();
  if (!email || !/@gmail\.com$/i.test(email)) {
    notify('Use a valid Gmail address to continue.');
    return;
  }
  try {
    const res = await fetch('/api/exam-registrations/request-confirmation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        full_name: `${$('exam-first-name').value.trim()} ${$('exam-last-name').value.trim()}`.trim(),
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || 'Could not start Gmail confirmation.');
    const status = $('exam-confirmation-status');
    if (status) {
      status.innerHTML = `Confirmation step started. Open the Gmail link to confirm your account: <a href="${escapeHtml(body.confirmation_url || '#')}" target="_blank" rel="noopener">Confirm registration</a>`;
    }
    notify('Confirmation link generated. Please click it in your Gmail inbox.');
    form.dataset.confirmationToken = body.token || '';
  } catch (err) {
    notify(err.message || 'Could not begin Gmail confirmation.');
  }
}

async function saveExamRegistration(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  const isEdit = form.dataset.registrationId;
  const method = isEdit ? 'PUT' : 'POST';
  const email = String(payload.email || '').trim();
  if (!email || !/@gmail\.com$/i.test(email)) {
    notify('Only Gmail-based sign-in is allowed for exam registration.');
    return;
  }
  const url = isEdit ? `/api/exam-registrations/${encodeURIComponent(isEdit)}` : '/api/exam-registrations';
  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, is_confirmed: true, confirmation_token: form.dataset.confirmationToken || '' }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || 'Could not save the registration');
    form.reset();
    delete form.dataset.registrationId;
    delete form.dataset.confirmationToken;
    form.querySelector('button[type="submit"]').textContent = 'Register exam';
    await loadExamRegistrations();
    notify(isEdit ? 'Exam registration updated.' : 'Exam registration saved.');
  } catch (err) {
    notify(err.message || 'Could not save the registration.');
  }
}

async function deleteExamRegistration(id) {
  if (!id || !confirm('Delete this exam registration?')) return;
  try {
    const res = await fetch(`/api/exam-registrations/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Could not delete the registration');
    await loadExamRegistrations();
    notify('Exam registration deleted.');
  } catch (err) {
    notify(err.message || 'Could not delete the registration.');
  }
}

async function editExamRegistration(id) {
  const list = $('exam-registration-list');
  if (!list) return;
  try {
    const res = await fetch(`/api/exam-registrations`);
    if (!res.ok) throw new Error('Could not load records');
    const items = await res.json();
    const entry = items.find((item) => String(item.id) === String(id));
    if (!entry) return;
    $('exam-first-name').value = entry.first_name || (entry.full_name || '').split(' ')[0] || '';
    $('exam-last-name').value = entry.last_name || (entry.full_name || '').split(' ').slice(1).join(' ') || '';
    $('exam-dob').value = entry.date_of_birth || '';
    $('exam-email').value = entry.email || '';
    const form = $('exam-registration-form');
    form.dataset.registrationId = String(entry.id);
    form.querySelector('button[type="submit"]').textContent = 'Update registration';
    switchMainTab('exam-registration');
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    notify(err.message || 'Could not open the registration for editing.');
  }
}

function switchMainTab(tabName) {
  $('pdf-modal').hidden = tabName !== 'upload-crop' || !(parsed.length || sourceBusy);
  const panels = {
    questions: $('questions-panel'),
    'exam-registration': $('exam-registration-panel'),
    exam: $('exam-panel'),
    'upload-crop': $('upload-crop-panel'),
  };
  const tabs = [...document.querySelectorAll('.main-tab')];
  Object.entries(panels).forEach(([name, panel]) => {
    if (!panel) return;
    panel.hidden = name !== tabName && !(name === 'questions' && tabName === 'edit');
    panel.classList.toggle('active', name === tabName || (name === 'questions' && tabName === 'edit'));
  });
  if (tabName === 'edit') {
    $('editor-modal').hidden = false;
    $('editor').hidden = false;
    $('editor').dataset.activeDraft = 'true';
  } else {
    $('editor-modal').hidden = true;
    $('editor').hidden = true;
    $('editor').dataset.activeDraft = 'false';
  }
  tabs.forEach((tab) => {
    const active = tab.dataset.mainTab === tabName;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-pressed', String(active));
  });
}

document.querySelectorAll('.main-tab').forEach((tab) => {
  tab.addEventListener('click', () => switchMainTab(tab.dataset.mainTab));
});

function aiGenerationPayload() {
  const form = $('ai-generation-form');
  const raw = Object.fromEntries(new FormData(form).entries());
  let extra_metadata = {};
  if (String(raw.extra_metadata || '').trim()) {
    try { extra_metadata = JSON.parse(raw.extra_metadata); }
    catch { throw new Error('Extra Metadata must be valid JSON.'); }
    if (!extra_metadata || Array.isArray(extra_metadata) || typeof extra_metadata !== 'object') throw new Error('Extra Metadata must be a JSON object.');
  }
  return {...raw,count:Number(raw.count),tags:String(raw.tags || '').split(',').map(tag=>tag.trim()).filter(Boolean),extra_metadata};
}

function renderAiGenerationResults(result) {
  const target=$('ai-generation-results');target.hidden=false;
  target.dataset.runId=result.run_id;target.innerHTML=`<div class="ai-result-summary"><h3>Review generated questions</h3><p><strong>${escapeHtml(result.exam)}</strong> · ${escapeHtml(result.subject)} · Requested ${result.requested} · Generated ${result.generated} · Awaiting review ${result.review_required} · Model ${escapeHtml(result.model)}</p><div class="actions"><button type="button" data-ai-view-prompt>View prompt</button><button type="button" data-ai-expand-all>Expand all</button><button type="button" data-ai-collapse-all>Collapse all</button><button type="button" data-ai-save-selected>Save selected</button><button type="button" class="primary" data-ai-save-all>Save all to Question Bank</button></div></div><div class="ai-question-grid">${result.questions.map((q,index)=>`<article class="ai-question-card" data-ai-review-index="${index}"><div class="meta"><label><input type="checkbox" data-ai-select checked /> Select</label><span class="badge">AI Generated</span><span class="verify review_required">REVIEW REQUIRED</span><button type="button" data-ai-toggle-question>Collapse</button></div><div class="ai-question-body"><h3>Question ${index+1}</h3><div class="rendered">${toHtml(q.statement)}</div>${(q.visual_assets||[]).map(a=>safeUrl(a.asset)?`<figure class="digital-asset"><img src="${safeUrl(a.asset)}" alt="${escapeHtml(a.description||'Generated question diagram')}"/><button type="button" class="image-expand" data-view-image="${safeUrl(a.asset)}">Expand diagram</button></figure>`:'').join('')}${(q.options||[]).length?`<ol class="ai-question-options">${q.options.map(o=>`<li><strong>${escapeHtml(o.label)}.</strong> <span class="rendered">${toHtml(o.text)}</span></li>`).join('')}</ol>`:''}<div class="ai-answer rendered"><strong>Answer:</strong> ${toHtml(q.answer)}${q.solution?`<br><strong>Solution:</strong> ${toHtml(q.solution)}`:''}</div></div></article>`).join('')}</div>`;
  target.querySelectorAll('.rendered').forEach(typeset);
}

async function loadAiGenerationRuns() {
  const target=$('ai-run-list');if(!target)return;
  target.innerHTML='<p class="empty-state">Loading saved runs…</p>';
  try {
    const runs=await api('/api/ai/runs');
    target.innerHTML=runs.length?`<table><thead><tr><th>Created</th><th>Exam and subject</th><th>Questions</th><th>Status</th><th>Model</th><th>Actions</th></tr></thead><tbody>${runs.map(run=>`<tr><td>${new Date(run.created_at*1000).toLocaleString()}</td><td><strong>${escapeHtml(run.exam_name)}</strong><small>${escapeHtml(run.subject)}${run.topic?` · ${escapeHtml(run.topic)}`:''}</small></td><td>${run.accepted_count} saved / ${run.generated_count} generated</td><td><span class="badge">${escapeHtml(run.status)}</span>${run.error_message?`<small>${escapeHtml(run.error_message)}</small>`:''}</td><td>${escapeHtml(run.model||'—')}</td><td><div class="actions"><button type="button" data-ai-review-run="${run.id}">Review</button><button type="button" data-ai-reuse-run="${run.id}">Reuse inputs</button><button type="button" class="primary" data-ai-regenerate-run="${run.id}" ${run.status==='RUNNING'?'disabled':''}>Regenerate</button></div></td></tr>`).join('')}</tbody></table>`:'<p class="empty-state">No saved generation runs yet.</p>';
  } catch(err) { target.innerHTML=`<p class="empty-state">${escapeHtml(err.message)}</p>`; }
}

async function reuseAiGenerationRun(runId) {
  const run=await api(`/api/ai/runs/${runId}`);const values=run.request||{};const form=$('ai-generation-form');
  for(const [name,value] of Object.entries(values)){const field=form.elements.namedItem(name);if(!field)continue;if(name==='tags')field.value=Array.isArray(value)?value.join(', '):value||'';else if(name==='extra_metadata')field.value=value&&Object.keys(value).length?JSON.stringify(value,null,2):'';else field.value=value??'';}
  switchAiTab('new');form.dataset.sourceRun=runId;$('ai-generation-status').textContent='Saved inputs restored. You can edit them or generate again.';form.scrollIntoView({behavior:'smooth',block:'start'});
}

function switchAiTab(name){$('ai-new-pane').hidden=name!=='new';$('ai-saved-pane').hidden=name!=='saved';document.querySelectorAll('[data-ai-tab]').forEach(button=>button.classList.toggle('active',button.dataset.aiTab===name));if(name==='saved')loadAiGenerationRuns();}
async function reviewAiGenerationRun(runId) { const run=await api(`/api/ai/runs/${runId}`);switchAiTab('new');renderAiGenerationResults({run_id:run.id,exam:run.exam_name,subject:run.subject,requested:run.requested_count,generated:run.generated_count,review_required:(run.output?.questions||[]).length,model:run.model,questions:run.output?.questions||[]});$('ai-generation-results').scrollIntoView({behavior:'smooth',block:'start'}); }

document.querySelectorAll('[data-ai-tab]').forEach(button=>button.addEventListener('click',()=>switchAiTab(button.dataset.aiTab)));
document.querySelectorAll('[data-ai-toggle-field]').forEach(button=>button.addEventListener('click',()=>{const field=button.closest('.ai-large-field');field.classList.toggle('collapsed');button.textContent=field.classList.contains('collapsed')?'Expand':'Collapse';}));

$('ai-guide-prompt')?.addEventListener('click',async()=>{const button=$('ai-guide-prompt'),form=$('ai-generation-form'),raw=Object.fromEntries(new FormData(form).entries());if(!String(raw.exam_name||'').trim()||!String(raw.subject||'').trim()){$('ai-generation-status').textContent='Enter at least the exam name and subject for Gemini guidance.';return;}if((raw.syllabus||raw.generation_prompt)&&!confirm('Replace the current syllabus and question-generation prompt with new Gemini guidance?'))return;button.disabled=true;$('ai-generation-status').textContent='Gemini is drafting curriculum context and generation instructions…';try{const fields=['exam_name','exam_type','level','subject','chapter','topic','subtopic','difficulty','question_type','marks','language'];const payload=Object.fromEntries(fields.map(name=>[name,raw[name]||'']));payload.count=Number(raw.count||5);const result=await api('/api/ai/prompt-guidance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});form.elements.syllabus.value=result.syllabus;form.elements.generation_prompt.value=result.generation_prompt;form.elements.syllabus.closest('.ai-large-field').classList.remove('collapsed');form.elements.generation_prompt.closest('.ai-large-field').classList.remove('collapsed');button.textContent='Regenerate syllabus & prompt';$('ai-model-badge').textContent=result.model;$('ai-generation-status').textContent='Gemini guidance is ready. Review or edit it, then generate questions.';}catch(err){$('ai-generation-status').textContent=err.message;}finally{button.disabled=false;}});

$('ai-preview-prompt')?.addEventListener('click',async()=>{try{const data=await api('/api/ai/prompt-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(aiGenerationPayload())});$('ai-prompt-preview').hidden=false;$('ai-prompt-preview').querySelector('pre').textContent=data.effective_prompt;$('ai-model-badge').textContent=data.model;}catch(err){$('ai-generation-status').textContent=err.message;}});
$('ai-close-preview')?.addEventListener('click',()=>{$('ai-prompt-preview').hidden=true;});
$('ai-generation-form')?.addEventListener('submit',async event=>{event.preventDefault();const button=$('ai-generate-submit');button.disabled=true;$('ai-generation-status').textContent='Gemini is generating and validating structured questions…';try{const result=await api('/api/ai/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(aiGenerationPayload())});renderAiGenerationResults(result);await loadAiGenerationRuns();$('ai-generation-status').textContent=`${result.review_required} questions are ready for review. Select the questions you want to save.`;}catch(err){$('ai-generation-status').textContent=err.message;}finally{button.disabled=false;}});
$('ai-refresh-runs')?.addEventListener('click',loadAiGenerationRuns);
$('ai-run-list')?.addEventListener('click',async event=>{const review=event.target.closest('[data-ai-review-run]');if(review){try{await reviewAiGenerationRun(review.dataset.aiReviewRun);}catch(err){notify(err.message);}return;}const reuse=event.target.closest('[data-ai-reuse-run]');if(reuse){try{await reuseAiGenerationRun(reuse.dataset.aiReuseRun);}catch(err){notify(err.message);}return;}const regenerate=event.target.closest('[data-ai-regenerate-run]');if(regenerate){regenerate.disabled=true;$('ai-generation-status').textContent='Regenerating from the saved prompt and context…';try{const result=await api(`/api/ai/runs/${regenerate.dataset.aiRegenerateRun}/regenerate`,{method:'POST'});renderAiGenerationResults(result);await loadAiGenerationRuns();$('ai-generation-status').textContent=`Regeneration completed. Review the new questions before saving.`;}catch(err){$('ai-generation-status').textContent=err.message;regenerate.disabled=false;}}});
$('ai-generation-results')?.addEventListener('click',async event=>{const toggle=event.target.closest('[data-ai-toggle-question]');if(toggle){const card=toggle.closest('.ai-question-card');card.classList.toggle('collapsed');toggle.textContent=card.classList.contains('collapsed')?'Expand':'Collapse';return;}if(event.target.closest('[data-ai-expand-all]')||event.target.closest('[data-ai-collapse-all]')){const collapse=!!event.target.closest('[data-ai-collapse-all]');$('ai-generation-results').querySelectorAll('.ai-question-card').forEach(card=>{card.classList.toggle('collapsed',collapse);card.querySelector('[data-ai-toggle-question]').textContent=collapse?'Expand':'Collapse';});return;}if(event.target.closest('[data-ai-view-prompt]')){$('ai-prompt-preview').hidden=false;$('ai-prompt-preview').scrollIntoView({behavior:'smooth'});return;}const saveAll=event.target.closest('[data-ai-save-all]');const saveSelected=event.target.closest('[data-ai-save-selected]');if(saveAll||saveSelected){const target=$('ai-generation-results');const cards=[...target.querySelectorAll('[data-ai-review-index]')];const indices=saveAll?cards.map(card=>Number(card.dataset.aiReviewIndex)):cards.filter(card=>card.querySelector('[data-ai-select]').checked).map(card=>Number(card.dataset.aiReviewIndex));if(!indices.length){notify('Select at least one question to save.');return;}const button=saveAll||saveSelected;button.disabled=true;try{const result=await api(`/api/ai/runs/${target.dataset.runId}/save`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({indices})});cards.filter(card=>indices.includes(Number(card.dataset.aiReviewIndex))).forEach(card=>{card.querySelector('[data-ai-select]').checked=false;card.classList.add('saved');card.querySelector('.verify').textContent='SAVED';});await Promise.all([loadAiGenerationRuns(),loadQuestions(),loadFacets()]);$('ai-generation-status').textContent=`${result.saved_count} questions saved to the Question Bank.${result.rejected_count?` ${result.rejected_count} duplicates or invalid questions were skipped.`:''}`;notify(`${result.saved_count} questions saved to the Question Bank.`);}catch(err){notify(err.message);}finally{button.disabled=false;}}});

$('exam-registration-form')?.addEventListener('submit', saveExamRegistration);
$('exam-reset-form')?.addEventListener('click', () => {
  const form = $('exam-registration-form');
  form.reset();
  delete form.dataset.registrationId;
  delete form.dataset.confirmationToken;
  form.querySelector('button[type="submit"]').textContent = 'Register exam';
  const status = $('exam-confirmation-status');
  if (status) status.textContent = 'Only Gmail accounts can register. Confirm the link sent to your Google account before final submission.';
});
$('exam-start-button')?.addEventListener('click', startExamSession);
$('exam-generate-paper-tab')?.addEventListener('click', () => loadExamPaperIntoTab());
$('exam-prev-question')?.addEventListener('click', () => moveExamQuestion(examState.currentIndex - 1));
$('exam-next-question')?.addEventListener('click', () => moveExamQuestion(examState.currentIndex + 1));
$('exam-mark-review')?.addEventListener('click', toggleMarkForReview);
$('exam-clear-answer')?.addEventListener('click', clearCurrentAnswer);
$('exam-submit-button')?.addEventListener('click', () => {
  if (!$('exam-current-question').dataset.session) submitExamSession();
});
$('exam-question-nav')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-exam-jump]');
  if (!button) return;
  moveExamQuestion(Number(button.dataset.examJump));
});
$('exam-current-question')?.addEventListener('change', (event) => {
  const input = event.target;
  if (!input || input.type !== 'radio' || !input.name.startsWith('exam-choice-')) return;
  saveExamAnswer(input.name.replace('exam-choice-', ''), input.value);
});
$('exam-generate-paper')?.addEventListener('click', () => loadExamPaper());
$('exam-print-paper')?.addEventListener('click', () => window.print());
$('exam-search')?.addEventListener('input', () => { loadExamRegistrations(); });
$('exam-export-csv')?.addEventListener('click', () => window.location.href = '/api/exam-registrations/export.csv');
$('exam-export-pdf')?.addEventListener('click', () => window.location.href = '/api/exam-registrations/export.pdf');
$('exam-sample-paper')?.addEventListener('click', () => window.location.href = '/api/exam-registrations/sample-paper.pdf');

if ($('exam-paper-preview')) {
  loadExamPaper();
}

$('exam-registration-list')?.addEventListener('click', async (event) => {
  const approveButton = event.target.closest('[data-exam-approve]');
  if (approveButton) {
    try {
      const res = await fetch(`/api/exam-registrations/${approveButton.dataset.examApprove}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'approved' }),
      });
      if (!res.ok) throw new Error('Could not approve the registration');
      await loadExamRegistrations();
      notify('Registration approved.');
    } catch (err) {
      notify(err.message || 'Could not approve the registration.');
    }
    return;
  }

  const rejectButton = event.target.closest('[data-exam-reject]');
  if (rejectButton) {
    try {
      const res = await fetch(`/api/exam-registrations/${rejectButton.dataset.examReject}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'rejected' }),
      });
      if (!res.ok) throw new Error('Could not reject the registration');
      await loadExamRegistrations();
      notify('Registration rejected.');
    } catch (err) {
      notify(err.message || 'Could not reject the registration.');
    }
    return;
  }

  const button = event.target.closest('[data-exam-edit]');
  if (button) {
    await editExamRegistration(button.dataset.examEdit);
    return;
  }
  const deleteButton = event.target.closest('[data-exam-delete]');
  if (deleteButton) {
    await deleteExamRegistration(deleteButton.dataset.examDelete);
  }
});

$('btn-open-review')?.addEventListener('click', () => {
  switchMainTab('upload-crop');
  if (!parsed.length) { $('pdf-file').click(); return; }
  if ($('pdf-modal')) {
    $('pdf-modal').hidden = false;
    $('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
});

document.querySelectorAll('.main-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    const nextTab = tab.dataset.mainTab;
    switchMainTab(nextTab);
    if (nextTab === 'edit' && !$('editor').hidden) {
      $('editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

window.addEventListener('load', async () => {
  resetForm();
  syncSaveState();
  switchMainTab('questions');
  // Role-specific data is loaded when its workspace view is opened.
  try { const response=await fetch('/api/auth/me');const user=await response.json();if(response.ok && user.role==='ADMIN')await Promise.all([loadQuestions(),loadFacets(),loadExamRegistrations(),refreshOcrStatus()]); } catch {}
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
