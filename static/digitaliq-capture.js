/* DigitalIQBank photo capture mount used by the Grand Tests workspace. */
window.mountDigitaliqCapture = (host, programOptions, onReady = () => {}, onStatus = () => {}) => {
  host.insertAdjacentHTML('beforeend', `<form class="gt-capture"><h3>Take photo or choose photos</h3><p>JPEG, PNG or WebP · up to 20 photos · 10 MB each.</p><div class="gt-fields"><label>Program<select name="program_id" required>${programOptions}</select></label><label>Subject<input name="subject" maxlength="120" required></label><label>Photo pages<input name="files" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" multiple required></label></div><p role="status" data-capture-status></p><button type="submit">Upload photo pages</button></form>`);
  const form = host.querySelector('.gt-capture'); const status = form.querySelector('[data-capture-status]');
  const say = text => { status.textContent = text; onStatus(text); };
  form.onsubmit = async event => { event.preventDefault(); const files = [...form.elements.files.files]; if (!files.length) return say('Choose at least one photo.'); if (files.length > 20 || files.some(file => file.size > 10 * 1024 * 1024)) return say('Use at most 20 photos, with each file under 10 MB.');
    const data = new FormData(form); data.delete('files'); files.forEach(file => data.append('files', file)); say('Uploading photo pages…'); form.querySelector('button').disabled = true;
    try { const response = await fetch('/api/grand-tests/documents/photos', { method: 'POST', body: data }); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.detail || `Upload failed (${response.status})`); say('Ready — stored for Admin approval.'); await onReady(body); } catch (error) { say(`Failed: ${error.message}`); } finally { form.querySelector('button').disabled = false; }
  };
};
