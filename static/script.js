/* Same-origin FastAPI client. Never interpret OCR or API text as HTML. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const MAX_BYTES = 8 * 1024 * 1024;
  const titles = {scanner: 'Screenshot scanner', history: 'Scan history', guide: 'How it works'};
  const verdicts = {
    SUSPICIOUS: {kind: 'suspicious', label: 'Suspicious', eyebrow: 'WARNING SIGNALS FOUND', caption: 'Review the warning signals and verify the credit in your bank app.'},
    'NEEDS MANUAL CHECK': {kind: 'manual', label: 'Needs manual check', eyebrow: 'REVIEW RECOMMENDED', caption: 'There is not enough evidence to make a confident assessment.'},
    'NO OBVIOUS ANOMALY DETECTED': {kind: 'clear', label: 'No obvious anomaly', eyebrow: 'NO MAJOR SIGNALS FOUND', caption: 'Available checks found no major issue. This is not proof of payment.'}
  };
  let selectedFile = null, previewURL = null, selectionVersion = 0;
  let busy = false, controller = null, lastResult = null, historyItems = [];
  let historyState = 'loading', historyVersion = 0, toastTimer;
  const selectedApp = () => document.querySelector('input[name="upi-app"]:checked').value;
  const text = (id, value) => { $(id).textContent = value; };
  const announce = message => text('announcer', message);
  const fmtSize = n => n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(2)} MB`;
  const kindFor = verdict => verdicts[verdict]?.kind || 'manual';
  const labelFor = verdict => verdicts[verdict]?.label || 'Assessment unavailable';

  function element(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function error(message = '') { text('upload-error', message); $('upload-error').hidden = !message; }
  function toast(message) {
    clearTimeout(toastTimer); text('toast', message); $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
  }
  function route(focus = false) {
    const name = Object.hasOwn(titles, location.hash.slice(1)) ? location.hash.slice(1) : 'scanner';
    for (const view of Object.keys(titles)) $(view + '-view').hidden = view !== name;
    document.querySelectorAll('[data-view]').forEach(link => {
      const active = link.dataset.view === name;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    text('breadcrumb-current', titles[name]); document.title = `${titles[name]} · UPI Shield`;
    if (focus) { $('main').focus({preventScroll: true}); window.scrollTo({top: 0}); }
  }
  window.addEventListener('hashchange', () => route(true));

  function clearResult() {
    lastResult = null;
    $('result-content').hidden = true; $('loading-state').hidden = true; $('empty-state').hidden = false;
    text('report-status', selectedFile ? 'Ready to analyse' : 'Awaiting screenshot');
    document.querySelector('.ocr-details').open = false;
  }
  function clearFile() {
    selectionVersion++;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = null; selectedFile = null;
    $('file-input').value = ''; $('camera-input').value = '';
    $('image-preview').removeAttribute('src'); $('preview-wrap').hidden = true; $('upload-prompt').hidden = false;
    $('analyse-button').disabled = true; clearResult();
  }
  async function chooseFile(file) {
    if (busy || !file) return;
    clearFile(); error();
    const version = selectionVersion;
    if (!/\.(png|jpe?g)$/i.test(file.name) || (file.type && !['image/png', 'image/jpeg'].includes(file.type))) {
      error('Choose a JPG or PNG image. Other formats, including HEIC, are not supported.'); return;
    }
    if (!file.size || file.size > MAX_BYTES) {
      error(file.size ? 'This image is larger than 8 MB. Choose a smaller screenshot.' : 'This file is empty. Choose another screenshot.'); return;
    }
    const url = URL.createObjectURL(file);
    try {
      // Decode before enabling submission so a renamed text file cannot look ready.
      const image = new Image(); image.src = url; await image.decode();
      if (version !== selectionVersion) { URL.revokeObjectURL(url); return; }
      selectedFile = file; previewURL = url;
      $('image-preview').src = url;
      text('file-name', file.name); text('file-size', `${fmtSize(file.size)} · ${image.naturalWidth} × ${image.naturalHeight}`);
      $('upload-prompt').hidden = true; $('preview-wrap').hidden = false;
      $('analyse-button').disabled = false; text('report-status', 'Ready to analyse');
      announce(`${file.name} selected. Ready to analyse.`);
    } catch {
      URL.revokeObjectURL(url);
      if (version === selectionVersion) error('This image could not be opened. Try an original, undamaged JPG or PNG.');
    }
  }
  $('browse-button').addEventListener('click', () => $('file-input').click());
  $('replace-file').addEventListener('click', () => $('file-input').click());
  $('camera-button').addEventListener('click', () => $('camera-input').click());
  for (const id of ['file-input', 'camera-input']) $(id).addEventListener('change', event => chooseFile(event.target.files?.[0]));
  $('remove-file').addEventListener('click', () => { if (!busy) { clearFile(); error(); $('browse-button').focus(); } });
  $('new-scan').addEventListener('click', () => { clearFile(); error(); $('browse-button').focus(); });
  for (const type of ['dragenter', 'dragover']) $('drop-zone').addEventListener(type, event => {
    event.preventDefault(); if (!busy) $('drop-zone').classList.add('dragging');
  });
  $('drop-zone').addEventListener('dragleave', event => {
    if (!$('drop-zone').contains(event.relatedTarget)) $('drop-zone').classList.remove('dragging');
  });
  $('drop-zone').addEventListener('drop', event => {
    event.preventDefault(); $('drop-zone').classList.remove('dragging');
    if (busy) return;
    if (event.dataTransfer.files.length > 1) { error('Choose one screenshot at a time.'); return; }
    chooseFile(event.dataTransfer.files[0]);
  });
  // Prevent an accidental file drop outside the target from navigating away.
  for (const type of ['dragover', 'drop']) window.addEventListener(type, event => {
    if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();
  });
  document.querySelectorAll('input[name="upi-app"]').forEach(input => input.addEventListener('change', () => { if (!busy) { clearResult(); error(); } }));

  async function fetchJSON(url, options = {}, timeout = 10000) {
    const control = new AbortController();
    const timer = setTimeout(() => control.abort(), timeout);
    try {
      const response = await fetch(url, {...options, signal: options.signal || control.signal});
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof data?.message === 'string' ? data.message : `The server could not complete the request (${response.status}). Please retry.`);
      if (!data || typeof data !== 'object') throw new Error('The server returned an unreadable response. Please retry.');
      return data;
    } finally { clearTimeout(timer); }
  }

  // A missing field is never a passed check. Match explicit backend statuses only.
  function checkModels(data) {
    const c = data.checks || {};
    const model = (label, available, warning, detail) => ({label, state: available ? (warning ? 'warning' : 'clear') : 'unavailable', detail});
    const l = c.layout_comparison, t = c.text_consistency, p = c.pixel_anomalies, ts = c.timestamp;
    return [
      model('Image validation', c.image?.status === 'valid', false, c.image?.status === 'valid' ? 'Image successfully decoded.' : 'Image validation status was not supplied.'),
      model('Text recognition', c.ocr?.status === 'available', false, c.ocr?.message || (c.ocr?.status === 'available' ? 'OCR text extracted; characters can be misread.' : 'Text recognition is unavailable.')),
      model('Payment wording', typeof c.payment_success_text?.found === 'boolean' && c.ocr?.status === 'available', !c.payment_success_text?.found, c.payment_success_text?.found ? 'Payment-success wording detected.' : 'No clear payment-success wording was detected.'),
      model('App layout', ['mismatch_signal', 'similar_structure_signal'].includes(l?.status), l?.suspicious === true, l?.note || 'No conclusive reference comparison is available.'),
      model('Text consistency', t?.status === 'analysed', t?.suspicious === true, t?.status === 'analysed' ? `${t.flagged_lines ?? 0} unusual text lines. Style differences are a heuristic signal.` : 'Not enough comparable text to assess style.'),
      model('Pixel patterns', p?.status === 'analysed', p?.suspicious === true, p?.status === 'analysed' ? `${p.anomalous_patches ?? 0} unusual patches. Compression can also affect this signal.` : 'Insufficient image information for this check.'),
      model('Timestamp', ['valid', 'invalid', 'future'].includes(ts?.status), ['invalid', 'future'].includes(ts?.status), ts?.reason || 'No supported timestamp could be validated.'),
      model('Image reuse', typeof c.duplicate_image?.detected === 'boolean', c.duplicate_image?.detected === true, c.duplicate_image?.detected ? 'This image appears in previous scans. A rescan is not proof of fraud.' : typeof c.duplicate_image?.detected === 'boolean' ? 'No exact image match in this server’s history.' : 'Reuse check was not supplied.'),
      model('Transaction reuse', Boolean(data.transaction_id) && typeof c.duplicate_transaction?.detected === 'boolean', c.duplicate_transaction?.detected === true, !data.transaction_id ? 'No readable transaction ID available for comparison.' : c.duplicate_transaction?.detected ? 'This ID appears in previous scans. Compare it with your bank records.' : 'No earlier ID match reported in this server’s history.')
    ];
  }
  function renderResult(data, elapsed) {
    const info = verdicts[data.verdict]; const checks = checkModels(data);
    const completed = checks.filter(c => c.state !== 'unavailable').length;
    const partial = completed < checks.length || data.analysis_quality === 'partial';
    lastResult = data;
    $('empty-state').hidden = true; $('result-content').hidden = false;
    $('verdict-card').className = `verdict-card ${info.kind}`;
    text('verdict-eyebrow', info.eyebrow); text('verdict-label', info.label); text('verdict-caption', info.caption);
    text('risk-score', data.risk_score); $('risk-meter').style.setProperty('--risk', data.risk_score);
    $('risk-meter').style.setProperty('--meter-color', info.kind === 'suspicious' ? 'var(--red)' : info.kind === 'clear' ? 'var(--accent)' : 'var(--amber)');
    $('risk-meter').setAttribute('aria-label', `Signal score ${data.risk_score} out of 100; not a probability of fraud`);
    $('partial-notice').hidden = !partial; text('report-status', partial ? 'Partial analysis' : 'Analysis complete');
    text('result-app', data.upi_app || selectedApp()); text('result-image-size', data.image_size || 'Size unavailable');
    text('result-scan-id', data.scan_id == null ? 'Scan ID unavailable' : `Scan #${data.scan_id}`);
    text('result-time', `${(elapsed / 1000).toFixed(2)}s round trip`);
    const reasons = Array.isArray(data.reasons) ? data.reasons.filter(reason => typeof reason === 'string') : [];
    $('reason-list').replaceChildren(...(reasons.length ? reasons : ['No explanation was supplied. Inspect the individual checks and confirm payment yourself.']).map(reason => element('li', '', reason)));
    text('reason-count', `${reasons.length} notes`); text('check-coverage', `${completed} of ${checks.length} completed`);
    $('checks-list').replaceChildren(...checks.map(check => {
      const row = element('div', `check-row ${check.state}`);
      const dot = element('span', 'check-state', check.state === 'clear' ? '✓' : check.state === 'warning' ? '!' : '–'); dot.setAttribute('aria-hidden', 'true');
      const body = element('div'); body.append(element('strong', '', check.label), element('p', '', check.detail));
      row.append(dot, body, element('small', '', {clear:'Checked', warning:'Warning', unavailable:'Unavailable'}[check.state])); return row;
    }));
    text('transaction-id', data.transaction_id || 'Not reliably detected');
    text('ocr-text', data.extracted_text || 'No readable text was extracted. Use the original image and check OCR availability.');
    text('result-notice', data.notice || 'Confirm the credit in your own bank or UPI app before handing over goods.');
    announce(`${info.label}. ${completed} of ${checks.length} checks completed.`);
    // Do not move focus away from another view if the user navigated while waiting.
    if (!$('scanner-view').hidden) $('verdict-label').focus({preventScroll: false});
  }

  $('scan-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !selectedFile) return;
    busy = true; error(); clearResult();
    $('upload-controls').disabled = true; $('analyse-button').disabled = true;
    $('report-panel').setAttribute('aria-busy', 'true'); $('empty-state').hidden = true; $('loading-state').hidden = false;
    text('analyse-label', 'Analysing screenshot…'); text('report-status', 'Analysis in progress'); text('elapsed-label', '0 seconds elapsed');
    announce('Analysis started. Screenshot and app selection are locked until it finishes.');
    const started = performance.now(); let timedOut = false;
    const interval = setInterval(() => text('elapsed-label', `${Math.floor((performance.now() - started) / 1000)} seconds elapsed`), 1000);
    const request = new AbortController(); controller = request;
    const timeout = setTimeout(() => { timedOut = true; request.abort(); }, 30000);
    const body = new FormData(); body.append('file', selectedFile, selectedFile.name); body.append('upi_app', selectedApp());
    try {
      const data = await fetchJSON('/api/analyze', {method: 'POST', body, signal: request.signal}, 30000);
      if (request.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (!Object.hasOwn(verdicts, data.verdict) || typeof data.risk_score !== 'number' || !Number.isFinite(data.risk_score) || data.risk_score < 0 || data.risk_score > 100) throw new Error('The server returned an incomplete analysis. Please retry.');
      renderResult(data, performance.now() - started);
    } catch (failure) {
      clearResult();
      const message = request.signal.aborted
        ? (timedOut ? 'The scan timed out after 30 seconds. ' : 'Stopped waiting for this scan. ') + 'The server may still save it; retrying can trigger a reuse warning.'
        : failure instanceof TypeError ? 'Cannot reach the analysis server. Check your connection and try again.' : failure.message;
      error(message); announce(message);
    } finally {
      clearTimeout(timeout); clearInterval(interval); controller = null; busy = false;
      $('upload-controls').disabled = false; $('analyse-button').disabled = !selectedFile;
      $('loading-state').hidden = true; $('report-panel').setAttribute('aria-busy', 'false'); text('analyse-label', 'Analyse screenshot');
      void loadHistory(); void loadStats();
    }
  });
  $('cancel-button').addEventListener('click', () => controller?.abort());

  function saveFile(name, content, mime) {
    const url = URL.createObjectURL(new Blob([content], {type: mime}));
    const a = element('a'); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $('download-report').addEventListener('click', () => {
    if (!lastResult) return;
    const id = String(lastResult.scan_id ?? 'latest').replace(/[^a-zA-Z0-9_-]/g, '');
    saveFile(`upi-shield-report-${id}.json`, JSON.stringify(lastResult, null, 2), 'application/json');
    toast('Report download started. It may contain private payment details.');
  });

  function formatDate(value) {
    const d = new Date(value); if (!value || !Number.isFinite(d.getTime())) return 'Date unavailable';
    return new Intl.DateTimeFormat(undefined, {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(d);
  }
  function filteredHistory() {
    const query = $('history-search').value.trim().toLowerCase(); const filter = $('history-filter').value;
    return historyItems.filter(item => (filter === 'all' || kindFor(item.verdict) === filter) && `${item.id} ${item.upi_app} ${item.verdict} ${labelFor(item.verdict)}`.toLowerCase().includes(query));
  }
  function badge(verdict) { return element('span', `badge ${kindFor(verdict)}`, labelFor(verdict)); }
  function emptyHistory(target, title, detail, retry = false) {
    const message = element('div', 'table-message'); message.append(element('strong', '', title), element('span', '', detail));
    if (retry) { const button = element('button', 'text-button', 'Retry loading history'); button.type = 'button'; button.addEventListener('click', loadHistory); message.append(button); }
    if (target.tagName === 'TBODY') { const row = element('tr'); const cell = element('td'); cell.colSpan = 5; cell.append(message); row.append(cell); target.replaceChildren(row); }
    else target.replaceChildren(message);
  }
  function renderHistory() {
    const body = $('history-body'), recent = $('recent-scans');
    $('export-history').disabled = true;
    if (historyState !== 'ready') {
      const failed = historyState === 'error';
      for (const target of [body, recent]) emptyHistory(target, failed ? 'History is unavailable' : 'Loading recent activity…', failed ? 'Your scanner is still available. Try loading these records again.' : 'Retrieving scans saved on this server.', failed);
      text('history-summary', failed ? 'Could not load history.' : 'Loading history…'); return;
    }
    const rows = filteredHistory(); text('history-summary', `${rows.length} of ${historyItems.length} recent scans shown`);
    $('export-history').disabled = rows.length === 0;
    if (!rows.length) emptyHistory(body, historyItems.length ? 'No matching scans' : 'Your history starts here', historyItems.length ? 'Try another search or choose All results.' : 'Completed screenshot checks will appear here.');
    else body.replaceChildren(...rows.map(item => {
      const row = element('tr');
      for (const value of [`#${item.id}`, item.upi_app, null, `${item.risk_score ?? '—'} / 100`, formatDate(item.created_at)]) {
        const cell = element('td'); if (value === null) cell.append(badge(item.verdict)); else cell.textContent = value; row.append(cell);
      } return row;
    }));
    if (!historyItems.length) emptyHistory(recent, 'No scans yet', 'Your recent screenshot checks will appear here.');
    else recent.replaceChildren(...historyItems.slice(0, 4).map(item => {
      const row = element('div', 'recent-row');
      const appClass = item.upi_app === 'PhonePe' ? 'phonepe' : item.upi_app === 'Paytm' ? 'paytm' : 'google';
      const logo = element('span', `app-logo ${appClass}-logo`, appClass === 'phonepe' ? 'पे' : appClass === 'paytm' ? 'P' : 'G');
      const details = element('div'); details.append(element('strong', '', item.upi_app), element('small', '', `#${item.id} · ${formatDate(item.created_at)}`));
      row.append(logo, details, badge(item.verdict), element('span', '', `${item.risk_score ?? '—'}/100`)); return row;
    }));
  }
  async function loadHistory() {
    const version = ++historyVersion; historyState = 'loading'; renderHistory(); $('refresh-history').disabled = true;
    try {
      const data = await fetchJSON('/api/history?limit=100');
      if (!Array.isArray(data.items)) throw new Error('Invalid history');
      if (version !== historyVersion) return;
      historyItems = data.items.filter(item => item && typeof item === 'object'); historyState = 'ready';
    } catch { if (version === historyVersion) { historyItems = []; historyState = 'error'; } }
    finally { if (version === historyVersion) { renderHistory(); $('refresh-history').disabled = false; } }
  }
  $('refresh-history').addEventListener('click', () => { void loadHistory(); void loadStats(); });
  $('history-search').addEventListener('input', renderHistory); $('history-filter').addEventListener('change', renderHistory);
  $('export-history').addEventListener('click', () => {
    // Quote cells and neutralize spreadsheet formulas in server-supplied strings.
    const cell = value => { let s = String(value ?? ''); if (/^[\s]*[=+@-]/.test(s)) s = "'" + s; return '"' + s.replaceAll('"', '""') + '"'; };
    const rows = [['Scan ID', 'Payment app', 'Assessment', 'Signal score', 'Timestamp'], ...filteredHistory().map(item => [item.id, item.upi_app, item.verdict, item.risk_score, item.created_at])];
    saveFile('upi-shield-history.csv', '\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n'), 'text/csv;charset=utf-8');
    toast('Filtered history download started.');
  });
  async function loadStats() {
    try {
      const data = await fetchJSON('/api/stats');
      if (!Number.isFinite(data.total_scans) || !Number.isFinite(data.suspicious_scans)) throw new Error('Invalid stats');
      text('stat-total', data.total_scans.toLocaleString()); text('stat-suspicious', data.suspicious_scans.toLocaleString()); $('stats-notice').hidden = true;
    } catch { text('stat-total', '—'); text('stat-suspicious', '—'); $('stats-notice').hidden = false; }
  }
  async function health() {
    $('service-button').disabled = true; text('service-label', 'Checking connection');
    try { const data = await fetchJSON('/api/health', {}, 5000); if (data.status !== 'ok') throw new Error(); $('service-button').className = 'service-status online'; text('service-label', 'Analysis service online'); }
    catch { $('service-button').className = 'service-status offline'; text('service-label', 'Service offline · retry'); }
    finally { $('service-button').disabled = false; }
  }
  $('service-button').addEventListener('click', () => { void health(); void loadStats(); void loadHistory(); });
  window.addEventListener('beforeunload', () => { controller?.abort(); if (previewURL) URL.revokeObjectURL(previewURL); });
  route(); void health(); void loadHistory(); void loadStats();
})();
