/* One viewer implementation, with isolated state and workflow adapters. */
const pdfWorkspaceTemplate = document.getElementById('pdf-viewer').cloneNode(true);
function createPdfDigitisationWorkspace(root, workflow = {}) {
const $ = (id) => (root.id === id || root.dataset.pdfId === id) ? root : root.querySelector(`[data-pdf-id="${id}"], [id="${id}"]`);
let busy = false;
const isBusy = () => busy || (workflow.isBusy ? workflow.isBusy() : sourceBusy);
/* Original PDF pages are rendered locally, independently of AI extraction. */
let previewFile = null;
let previewRequest = 0;
let previewController = null;
let previewSourceId = null;
let pdfCropMode = false;
let pdfSelection = [];
let pdfDrag = null;

function pdfSelectionPoint(event, rect) {
  return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
          Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
}
function pdfSelectionBox(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}
function drawPdfSelection(overlay, bbox) {
  overlay.style.left = `${bbox[0] * 100}%`;
  overlay.style.top = `${bbox[1] * 100}%`;
  overlay.style.width = `${(bbox[2] - bbox[0]) * 100}%`;
  overlay.style.height = `${(bbox[3] - bbox[1]) * 100}%`;
}
function setPdfCropMode(active) {
  pdfCropMode = active;
  $('pdf-viewer-pages').classList.toggle('selecting-portion', active);
  $('pdf-viewer-crop-toggle').setAttribute('aria-pressed', String(active));
  $('pdf-viewer-crop-toggle').textContent = active ? 'Cancel selection mode' : 'Select portion';
  $('pdf-selection-bar').hidden = !active && !pdfSelection.length;
  if (active) $('pdf-selection-status').textContent = 'Drag around one or more questions, including their options and diagrams.';
}
function clearPdfSelection() {
  pdfSelection = [];
  pdfDrag = null;
  root.querySelectorAll('.pdf-selection-box').forEach((box) => box.remove());
  $('pdf-selection-clear').disabled = true;
  $('pdf-selection-digitise').disabled = true;
  $('pdf-selection-digitise').textContent = 'Digitise selected portion';
  $('pdf-selection-bar').hidden = !pdfCropMode;
  $('pdf-selection-status').textContent = 'Drag a rectangle around a question on any page.';
}
function bindPdfPageSelection(surface, image, pageNumber) {
  surface.addEventListener('pointerdown', (event) => {
    if (!pdfCropMode || isBusy() || event.button !== 0 || !event.isPrimary || !image.naturalWidth) return;
    event.preventDefault();
    const overlay = document.createElement('div');
    overlay.className = 'pdf-selection-box';
    overlay.setAttribute('aria-hidden', 'true');
    surface.append(overlay);
    const start = pdfSelectionPoint(event, image.getBoundingClientRect());
    pdfDrag = { start, overlay, page: pageNumber, pointer: event.pointerId, surface };
    surface.setPointerCapture(event.pointerId);
    drawPdfSelection(overlay, pdfSelectionBox(start, start));
  });
  surface.addEventListener('pointermove', (event) => {
    if (!pdfDrag || pdfDrag.surface !== surface || pdfDrag.pointer !== event.pointerId) return;
    drawPdfSelection(pdfDrag.overlay, pdfSelectionBox(pdfDrag.start, pdfSelectionPoint(event, image.getBoundingClientRect())));
  });
  surface.addEventListener('pointerup', (event) => {
    if (!pdfDrag || pdfDrag.surface !== surface || pdfDrag.pointer !== event.pointerId) return;
    const bbox = pdfSelectionBox(pdfDrag.start, pdfSelectionPoint(event, image.getBoundingClientRect()));
    const overlay = pdfDrag.overlay;
    pdfDrag = null;
    surface.releasePointerCapture(event.pointerId);
    if (bbox[2] - bbox[0] < .005 || bbox[3] - bbox[1] < .005) {
      overlay.remove();
      $('pdf-selection-status').textContent = 'The selection is too small. Drag a larger rectangle.';
      return;
    }
    pdfSelection.push({ page: pageNumber, bbox, overlay });
    drawPdfSelection(overlay, bbox);
    const count = pdfSelection.length;
    $('pdf-selection-digitise').textContent = count === 1 ? 'Digitise selected portion' : `Digitise ${count} selected portions`;
    $('pdf-selection-status').textContent = count === 1
      ? `Portion selected on page ${pageNumber}. Ready to digitise.`
      : `${count} portions selected across the PDF. Ready to digitise.`;
    $('pdf-selection-clear').disabled = false;
    $('pdf-selection-digitise').disabled = false;
  });
  surface.addEventListener('pointercancel', () => { if (pdfDrag?.surface === surface) { pdfDrag.overlay.remove(); pdfDrag = null; } });
}

async function previewPdfDocument(file) {
  const request = ++previewRequest;
  previewController?.abort();
  previewController = new AbortController();
  previewFile = null;
  previewSourceId = null;
  clearPdfSelection();
  setPdfCropMode(false);
  $('pdf-viewer-crop-toggle').disabled = true;
  if (!workflow.load) {
    switchMainTab('upload-crop');
    parsed = [];
    lastPdf = null;
    document.getElementById('pdf-modal').hidden = true;
  }
  $('pdf-viewer').hidden = false;
  $('pdf-viewer-name').textContent = file.name;
  $('pdf-viewer-status').textContent = 'Opening PDF…';
  $('pdf-viewer-digitise').disabled = true;
  $('pdf-viewer-pages').innerHTML = '<p class="pdf-viewer-message">Preparing your document…</p>';
  $('pdf-viewer-pages').setAttribute('aria-busy', 'true');
  $('pdf-viewer-zoom').value = '100';
  $('pdf-viewer-pages').style.setProperty('--pdf-zoom', '100%');
  try {
    let data;
    if (workflow.load) data = await workflow.load(file);
    else {
      if (file.size > 50 * 1024 * 1024) throw new Error('Choose a PDF smaller than 50 MB.');
      const form = new FormData();
      form.append('file', file, file.name);
      const response = await fetch('/api/pdf/preview', { method: 'POST', body: form, signal: previewController.signal });
      data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not open this PDF.');
    }
    if (request !== previewRequest) return;
    previewFile = file;
    previewSourceId = data.id;
    if (!workflow.load) lastPdf = file;
    $('pdf-viewer-status').textContent = `${data.page_count} page${data.page_count === 1 ? '' : 's'} · Scroll to read`;
    const fragment = document.createDocumentFragment();
    data.pages.forEach((page) => {
      const figure = document.createElement('figure');
      figure.className = 'pdf-viewer-page';
      const caption = document.createElement('figcaption');
      caption.textContent = `Page ${page.number} of ${data.page_count}`;
      const image = document.createElement('img');
      image.alt = `Page ${page.number} of ${file.name}`;
      if (page.width && page.height) {
        image.width = Math.max(1, Math.round(page.width));
        image.height = Math.max(1, Math.round(page.height));
      }
      image.loading = page.number === 1 ? 'eager' : 'lazy';
      image.decoding = 'async';
      image.src = page.url;
      image.addEventListener('error', () => {
        caption.textContent = `Page ${page.number} could not load.`;
        const retry = document.createElement('button');
        retry.textContent = 'Retry page';
        retry.addEventListener('click', () => {
          caption.textContent = `Page ${page.number} of ${data.page_count}`;
          image.src = `${page.url}?retry=${Date.now()}`;
        });
        caption.append(' ', retry);
      });
      const surface = document.createElement('div');
      surface.className = 'pdf-page-surface';
      image.draggable = false;
      surface.append(image);
      bindPdfPageSelection(surface, image, page.number);
      figure.append(caption, surface);
      fragment.append(figure);
    });
    $('pdf-viewer-pages').replaceChildren(fragment);
    $('pdf-viewer-pages').scrollTop = 0;
    $('pdf-viewer-digitise').disabled = false;
    $('pdf-viewer-crop-toggle').disabled = !!workflow.locked;
    $('pdf-viewer-digitise').disabled = !!workflow.locked;
  } catch (error) {
    if (request !== previewRequest || error.name === 'AbortError') return;
    $('pdf-viewer-status').textContent = 'Could not open PDF';
    $('pdf-viewer-pages').textContent = error.message;
  } finally {
    if (request === previewRequest) $('pdf-viewer-pages').setAttribute('aria-busy', 'false');
  }
}

$('pdf-viewer-zoom').addEventListener('change', (event) => {
  $('pdf-viewer-pages').style.setProperty('--pdf-zoom', `${event.target.value}%`);
});
$('pdf-viewer-digitise').addEventListener('click', async () => {
  if (!previewFile || isBusy()) return;
  $('pdf-viewer-digitise').disabled = true;
  try {
    if (workflow.digitise) await digitiseWorkspace([]);
    else await readPdf(previewFile, 'auto');
  }
  catch (error) { $('pdf-viewer-status').textContent = error.message; notify(error.message); }
  finally { $('pdf-viewer-digitise').disabled = !previewFile || !!workflow.locked; }
});
$('pdf-viewer-close').addEventListener('click', () => {
  ++previewRequest;
  previewController?.abort();
  previewFile = null;
  previewSourceId = null;
  clearPdfSelection();
  setPdfCropMode(false);
  $('pdf-viewer').hidden = true;
  $('pdf-viewer-pages').replaceChildren();
});

$('pdf-viewer-crop-toggle').addEventListener('click', () => {
  if (!isBusy() && previewSourceId) setPdfCropMode(!pdfCropMode);
});
$('pdf-selection-clear').addEventListener('click', () => {
  if (isBusy()) return;
  // Redraw only the latest portion; keep unrelated pages and portions intact.
  pdfSelection.pop()?.overlay.remove();
  $('pdf-selection-digitise').textContent = pdfSelection.length > 1 ? `Digitise ${pdfSelection.length} selected portions` : 'Digitise selected portion';
  $('pdf-selection-clear').disabled = !pdfSelection.length;
  $('pdf-selection-digitise').disabled = !pdfSelection.length;
  setPdfCropMode(true);
});
$('pdf-selection-digitise').addEventListener('click', async () => {
  if (!pdfSelection.length || !previewSourceId || isBusy()) return;
  const selections = pdfSelection.map(({ page, bbox }) => ({ page, bbox: [...bbox] }));
  if (workflow.digitise) { await digitiseWorkspace(selections); return; }
  const sourceId = previewSourceId;
  const request = previewRequest;
  const controls = ['pdf-selection-digitise', 'pdf-selection-clear', 'pdf-viewer-crop-toggle', 'pdf-viewer-digitise', 'pdf-viewer-close', 'pdf-viewer-zoom'];
  controls.forEach((id) => { $(id).disabled = true; });
  setPdfCropMode(false);
  setUploadStatus(true, `Digitising ${selections.length} selected portion${selections.length === 1 ? '' : 's'}…`);
  $('pdf-selection-status').textContent = 'Digitising the selected portions. You can continue scrolling the PDF.';
  try {
    const response = await fetch(`/api/sources/${sourceId}/digitise-crop`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selections }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not digitise the selected portions.');
    if (request !== previewRequest) return;
    const previous = parsed.filter((q) => !q.saved);
    const added = data.questions || [];
    await openPdfModal({ ...data, questions: [...previous, ...added] });
    $('pdf-selection-status').textContent = `${added.length} draft question(s) added to review from ${selections.length} selected portion(s).`;
    document.getElementById('pdf-modal').scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('pdf-selection-digitise').textContent = 'Digitised — select another portion';
    $('pdf-selection-bar').hidden = true;
    clearPdfSelection();
  } catch (error) {
    $('pdf-selection-status').textContent = `Digitisation failed: ${error.message}`;
    notify(error.message);
    $('pdf-selection-digitise').disabled = false;
  } finally {
    setUploadStatus(false);
    controls.filter((id) => id !== 'pdf-selection-digitise').forEach((id) => { $(id).disabled = false; });
  }
});

async function digitiseWorkspace(selections) {
  if (busy || workflow.locked) return;
  busy = true;
  const controls = [...root.querySelectorAll('button, select')];
  const disabled = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  $('pdf-viewer-status').textContent = 'Digitising… You can continue scrolling the PDF.';
  try {
    await workflow.digitise(selections);
    clearPdfSelection();
  } catch (error) {
    $('pdf-viewer-status').textContent = `Digitisation failed: ${error.message}`;
    notify(error.message);
  } finally {
    busy = false;
    controls.forEach((control, i) => { control.disabled = disabled[i]; });
  }
}
// Toolbar additions share the same fit-width zoom mechanism in both workflows.
const zoom = $('pdf-viewer-zoom');
for (const [label, step] of [['Zoom out', -1], ['Zoom in', 1], ['Fit width', 0]]) {
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = label;
  button.onclick = () => {
    if (busy || zoom.disabled) return;
    zoom.selectedIndex = step ? Math.max(0, Math.min(zoom.options.length - 1, zoom.selectedIndex + step)) : 6;
    zoom.dispatchEvent(new Event('change'));
  };
  zoom.parentElement.after(button);
}
const clear = document.createElement('button');
clear.type = 'button'; clear.textContent = 'Clear all selections';
clear.onclick = () => { if (!isBusy()) clearPdfSelection(); };
$('pdf-selection-clear').after(clear);
if (workflow.load) $('pdf-viewer-close').hidden = true;
return { open: previewPdfDocument, destroy() { ++previewRequest; previewController?.abort(); } };
}
const uploadPdfWorkspace = createPdfDigitisationWorkspace(document.getElementById('pdf-viewer'));
function previewPdfDocument(file) { return uploadPdfWorkspace.open(file); }
function mountPdfDigitisationWorkspace(host, workflow) {
  const root = pdfWorkspaceTemplate.cloneNode(true);
  for (const element of [root, ...root.querySelectorAll('[id]')]) {
    element.dataset.pdfId = element.id;
    element.removeAttribute('id');
  }
  host.replaceChildren(root);
  return createPdfDigitisationWorkspace(root, workflow);
}
