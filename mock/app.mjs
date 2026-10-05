import { STAGES, CLIENTS, SAMPLE_BRIEF, seed, createProject, currentStage, isUnlocked, packageEligible, statusOf, generate, approve, requestChanges, revise, recordTests, publishRelease, event, zipFiles } from './model.mjs';

const STORAGE_KEY = 'erpfusion-local-mock-v1';
let state;
try {
  state = JSON.parse(localStorage.getItem(STORAGE_KEY));
  if (state?.version !== 1 || !Array.isArray(state.projects) || !Array.isArray(state.profiles)) state = seed();
} catch { state = seed(); }
const filters = { search: '', erp: '', type: '', status: '', page: 0 };
let mode = 'document', fileIndex = 0, busy = new Set(), saveTimer, toastTimer, saveStatus = 'Saved on this browser';
const root = document.querySelector('#app'), dialog = document.querySelector('#dialog');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const paths = {
  home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  studio: '<path d="m13 2-9 12h7l-1 8 10-12h-7z"/>',
  clients: '<path d="M3 21V7h8v14M11 21V3h10v18M1 21h22M6 10h2m-2 4h2m-2 4h2M14 7h3m-3 4h3m-3 4h3"/>',
  settings: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>', arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>', back: '<path d="M20 12H4m6-6-6 6 6 6"/>',
  file: '<path d="M14 2H5v20h14V7zM14 2v5h5M8 12h8M8 16h6"/>', layers: '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  code: '<path d="m7 7-5 5 5 5m10-10 5 5-5 5M14 4l-4 16"/>', package: '<path d="m12 2 10 5v10l-10 5-10-5V7zM2 7l10 5 10-5M12 12v10M7 4l10 5"/>',
  flask: '<path d="M9 2h6M10 2v7l-6 10c-.8 1.5 0 3 2 3h12c2 0 2.8-1.5 2-3L14 9V2M7 16h10"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>', upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  check: '<path d="m5 12 4 4L19 6"/>', lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', history: '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l4 2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.1"/>', close: '<path d="m6 6 12 12M6 18 18 6"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4M18 4h4"/>',
  shield: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6zM8 12l3 3 5-6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
};
const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
const badge = (text, tone = 'slate') => `<span class="badge ${tone}"><span class="status-dot"></span>${esc(text)}</span>`;
const btn = (action, label, kind = 'secondary', glyph = '', extra = '') => `<button class="btn ${kind}" data-action="${action}" ${extra}>${glyph ? icon(glyph) : ''}${esc(label)}</button>`;
function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); setSaveLabel('Saved on this browser'); }
  catch { setSaveLabel('Not saved — storage unavailable'); toast('Could not save. Keep this tab open to retain your demo edits.'); }
}
function setSaveLabel(text) { saveStatus = text; document.querySelectorAll('[data-save-label]').forEach(label => { label.textContent = text; }); }
function toast(message) {
  const node = document.querySelector('#toast'); node.textContent = message; node.classList.add('visible');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.remove('visible'), 5000);
}
function route() {
  const [page = 'home', id, rawIndex = '0', tab = 'workspace'] = location.hash.slice(1).split('/');
  return { page, id, index: Math.max(0, Math.min(5, Number(rawIndex) || 0)), tab };
}
function project() { return state.projects.find(p => p.id === route().id); }
function studioUrl(p, index = currentStage(p), tab = 'workspace') { return `#studio/${encodeURIComponent(p.id)}/${index}/${tab}`; }
function dueLabel(p) {
  if (!p.due) return '<span class="muted">Not set</span>';
  const date = new Date(`${p.due}T12:00:00`), today = new Date(); today.setHours(0, 0, 0, 0);
  const overdue = date < today && statusOf(p).label !== 'Completed';
  return `<span class="${overdue ? 'overdue' : ''}">${esc(date.toLocaleDateString(undefined, { day: '2-digit', month: 'short' }))}</span>${overdue ? '<small class="overdue">Overdue</small>' : `<small>${date.getFullYear()}</small>`}`;
}
function relative(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value)) / 60000));
  return minutes < 1 ? 'Just now' : minutes < 60 ? `${minutes} min ago` : minutes < 1440 ? `${Math.floor(minutes / 60)} hr ago` : `${Math.floor(minutes / 1440)} days ago`;
}
function clientAvatar(name) { const client = CLIENTS.find(c => c.name === name); return `<span class="client-avatar ${client?.color || 'blue'}">${esc(client?.initials || name.slice(0, 2).toUpperCase())}</span>`; }
function shell(content) {
  const { page } = route(), pageTitle = { home: 'Projects', studio: 'Engineering Studio', clients: 'Clients', profiles: 'ERP Profiles' }[page] || 'Projects';
  root.innerHTML = `
    <aside class="sidebar" aria-label="Main navigation">
      <a class="rail-brand" href="#home" aria-label="HighStudio Home">${icon('layers')}</a>
      <nav>${[['home', 'Home', 'home'], ['studio', 'Studio', 'studio'], ['clients', 'Clients', 'clients'], ['profiles', 'ERP profiles', 'settings']].map(([id, title, glyph]) => `<a href="#${id}" class="rail-link ${page === id ? 'active' : ''}" ${page === id ? 'aria-current="page"' : ''} title="${title}">${icon(glyph)}<span>${title}</span></a>`).join('')}</nav>
      <div class="rail-bottom"><button class="rail-link" data-action="help" title="About this prototype" aria-label="About this prototype">${icon('info')}<span>About</span></button><div class="rail-avatar" title="Demo engineer">LE</div></div>
    </aside>
    <div class="shell-column">
      <header class="header">
        <a class="wordmark" href="#home">High<span>Studio</span></a><span class="header-divider"></span><span class="header-context">${esc(pageTitle)}</span>
        <div class="header-right"><span class="prototype-chip">Local mock</span><button class="icon-button" data-action="help" aria-label="Prototype information">${icon('info')}</button><div class="user-avatar" title="Demo engineer · simulated roles">LE</div><img class="highradius" src="/highradius-logo.svg" alt="HighRadius"></div>
      </header>
      <main id="main" class="main" tabindex="-1">${content}</main>
      <footer class="footer"><span><span class="status-dot green-dot"></span>Local prototype <span class="footer-separator">/</span> Sample data only</span><span class="footer-note">No external connections · © 2026 HighRadius</span></footer>
    </div>`;
}
function options(values, selected, first) { return `<option value="">${first}</option>` + values.map(value => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(value === 'reviews' ? 'Awaiting review' : value)}</option>`).join(''); }
function directory(selecting = false) {
  const statuses = [...new Set(state.projects.map(p => statusOf(p).label))];
  const matches = state.projects.filter(p => (!filters.search || `${p.name} ${p.client} ${p.profile.name}`.toLowerCase().includes(filters.search.toLowerCase())) && (!filters.erp || p.profile.name === filters.erp) && (!filters.type || p.type === filters.type) && (!filters.status || (filters.status === 'reviews' ? statusOf(p).label.includes('review') : statusOf(p).label === filters.status)));
  const pageCount = Math.max(1, Math.ceil(matches.length / 6)); filters.page = Math.min(filters.page, pageCount - 1);
  const rows = matches.slice(filters.page * 6, filters.page * 6 + 6);
  const reviewCount = state.projects.filter(p => statusOf(p).label.includes('review')).length;
  const sandboxCount = state.projects.filter(p => statusOf(p).label === 'Ready for sandbox').length;
  const completeCount = state.projects.filter(p => statusOf(p).label === 'Completed').length;
  return `<div class="page home-page">
    <div class="page-heading"><div><div class="eyebrow">INTEGRATION ENGINEERING</div><h1>${selecting ? 'Your engineering studio' : 'Integration projects'}</h1><p>${selecting ? 'Choose a project to pick up exactly where you left off.' : 'Every client. Every ERP. One place to manage delivery.'}</p></div>${btn('create', 'Create New', 'primary', 'plus')}</div>
    <div class="metrics">
      <button class="metric ${!filters.status ? 'selected' : ''}" data-action="metric" data-status=""><span class="metric-label">All projects ${icon('layers')}</span><strong>${state.projects.length.toString().padStart(2, '0')}</strong><span class="metric-detail">Across ${new Set(state.projects.map(p => p.client)).size} clients</span></button>
      <button class="metric ${filters.status === 'reviews' ? 'selected' : ''}" data-action="metric" data-status="reviews"><span class="metric-label">Awaiting review ${icon('clock')}</span><strong>${reviewCount.toString().padStart(2, '0')}<span class="metric-pill amber">Human approval</span></strong><span class="metric-detail">Your next decision moves work forward</span></button>
      <button class="metric ${filters.status === 'Ready for sandbox' ? 'selected' : ''}" data-action="metric" data-status="Ready for sandbox"><span class="metric-label">Ready for sandbox ${icon('flask')}</span><strong>${sandboxCount.toString().padStart(2, '0')}</strong><span class="metric-detail">Approved packages ready to test</span></button>
      <button class="metric ${filters.status === 'Completed' ? 'selected' : ''}" data-action="metric" data-status="Completed"><span class="metric-label">Completed ${icon('shield')}</span><strong>${completeCount.toString().padStart(2, '0')}<span class="metric-pill green">Signed off</span></strong><span class="metric-detail">Tested releases available to download</span></button>
    </div>
    <section class="table-card" aria-labelledby="directory-title">
      <div class="table-heading"><div><h2 id="directory-title">${selecting ? 'Select a project' : 'Project directory'} <span class="count">${matches.length}</span></h2><p>${selecting ? 'Open Studio to review, revise, test or release.' : 'Track progress, resume work and download approved packages.'}</p></div>${btn('reset-filters', 'Clear filters', 'ghost', 'settings')}</div>
      <div class="filters"><label class="search-field">${icon('search')}<input id="search" data-filter="search" placeholder="Search projects or clients…" value="${esc(filters.search)}" aria-label="Search projects or clients"></label><select aria-label="Filter ERP" data-filter="erp">${options(state.profiles.map(p => p.name), filters.erp, 'All ERPs')}</select><select aria-label="Filter type" data-filter="type">${options(['Standard', 'Custom'], filters.type, 'All types')}</select><select aria-label="Filter status" data-filter="status">${options([...statuses, 'reviews'], filters.status, 'All statuses')}</select></div>
      <div class="table-scroll"><table><thead><tr><th>CLIENT NAME</th><th>PROJECT NAME</th><th>ERP</th><th>TYPE</th><th>STATUS</th><th>DUE DATE</th><th>LAST UPDATED</th><th>PACKAGE</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${rows.map(p => {
        const status = statusOf(p), released = status.label === 'Completed';
        return `<tr><td><div class="client-cell">${clientAvatar(p.client)}<span>${esc(p.client)}</span></div></td><td><a class="project-link" href="${studioUrl(p)}">${esc(p.name)}</a><small>INT-${esc(p.id.replace('demo-', '').slice(0, 8).toUpperCase())}</small></td><td><span class="erp-name">${esc(p.profile.name)}</span><small>Profile v${p.profile.version}</small></td><td><span class="type-chip ${p.type.toLowerCase()}">${esc(p.type)}</span></td><td>${badge(status.label, status.tone)}<small>${esc(status.detail)}</small></td><td>${dueLabel(p)}</td><td title="${esc(new Date(p.updatedAt).toLocaleString())}">${relative(p.updatedAt)}<small>${esc(new Date(p.updatedAt).toLocaleDateString(undefined, { day: '2-digit', month: 'short' }))}</small></td><td>${packageEligible(p) ? `<button class="download-link" data-action="download" data-id="${p.id}">${icon('download')} ${released ? 'Release' : 'Candidate'}</button><small>${released ? 'Tester signed off' : 'For sandbox testing'}</small>` : '<span class="package-locked">—</span><small>After package approval</small>'}</td><td><a class="row-open" href="${studioUrl(p)}" aria-label="Open Studio for ${esc(p.name)}" title="Open Studio">${icon('arrow')}</a></td></tr>`;
      }).join('') || '<tr><td colspan="9"><div class="empty-table">No projects match these filters.<br><button class="btn ghost" data-action="reset-filters">Clear filters</button></div></td></tr>'}</tbody></table></div>
      <div class="table-footer"><span>Showing ${matches.length ? filters.page * 6 + 1 : 0}–${Math.min((filters.page + 1) * 6, matches.length)} of ${matches.length} projects</span><div><button class="page-button" data-action="page-prev" aria-label="Previous page" ${!filters.page ? 'disabled' : ''}>${icon('back')}</button><span>Page ${filters.page + 1} of ${pageCount}</span><button class="page-button" data-action="page-next" aria-label="Next page" ${filters.page >= pageCount - 1 ? 'disabled' : ''}>${icon('arrow')}</button></div></div>
    </section>
    <div class="home-note">${icon('shield')}Approvals apply to exact revisions. Your history stays with the project.</div>
  </div>`;
}
function stageStrip(p, index) {
  return `<nav class="stage-strip" aria-label="Project workflow">${STAGES.map((stage, n) => {
    const current = p.stages[n].current, unlocked = isUnlocked(p, n), approved = current?.status === 'approved';
    return `<a class="stage-step ${n === index ? 'selected' : ''} ${approved ? 'approved' : ''} ${!unlocked ? 'locked' : ''}" href="${studioUrl(p, n)}" ${n === index ? 'aria-current="step"' : ''}><span class="stage-number">${approved ? icon('check') : !unlocked ? icon('lock') : n + 1}</span><span><strong>${stage.name}</strong><small>${approved ? `Approved · v${current.version}` : !unlocked ? 'Locked' : current?.status === 'changes_requested' ? 'Changes requested' : current ? `In review · v${current.version}` : 'Ready to begin'}</small></span>${n < 5 ? icon('chevron', 'stage-arrow') : ''}</a>`;
  }).join('')}</nav>`;
}
function uploadWorkspace(p) {
  return `<section class="workspace-card"><div class="section-title"><span class="section-icon">${icon('upload')}</span><div><h2>Start with the requirement document</h2><p>Upload the brief from your consulting team.</p></div></div>
    <label class="dropzone" id="dropzone"><input id="files" type="file" accept=".pdf,.docx,.txt,.md" multiple><span class="upload-illustration">${icon('upload')}</span><strong>Drop your requirement files here</strong><span>or <b>browse files</b></span><small>PDF, DOCX, TXT or Markdown · up to 10 MB each</small></label>
    <div class="file-list">${p.files.map((file, i) => `<div class="uploaded-file">${icon('file')}<div><strong>${esc(file.name)}</strong><small>${Math.ceil(file.size / 1024) || 1} KB · ${file.sample ? 'Sample brief' : /\.(txt|md)$/i.test(file.name) ? 'Text read locally' : 'Metadata only · paste requirement text below'}</small></div><button class="icon-button" data-action="remove-file" data-file="${i}" aria-label="Remove ${esc(file.name)}">${icon('close')}</button></div>`).join('')}</div>
    <div class="sample-brief"><div>${icon('spark')}<span>Exploring the experience?</span></div>${btn('sample', 'Use sample brief', 'secondary', 'file')}</div>
    <label class="field-label" for="brief">Requirement text <span class="optional">editable preview</span></label><textarea id="brief" class="brief" maxlength="20000" placeholder="Upload a TXT / Markdown file, paste a sample requirement, or use the sample brief above.">${esc(p.brief)}</textarea><p class="input-note">PDF and DOCX parsing is outside this mock. Use sample data; document text is saved on this browser.</p>
    <div class="workspace-bottom"><span data-save-label>${esc(saveStatus)}</span>${btn('generate', 'Analyze requirements', 'primary', 'spark', p.brief.trim().length < 30 ? 'disabled' : '')}</div>
  </section>`;
}
function documentWorkspace(p, index) {
  const stage = p.stages[index], current = stage.current;
  if (!isUnlocked(p, index)) return `<section class="workspace-card locked-workspace"><span class="big-icon">${icon('lock')}</span><h2>This stage is waiting for approval</h2><p>Approve ${STAGES[index - 1].name} before starting ${STAGES[index].name}.<br>You can inspect earlier work without changing the workflow.</p><a class="btn secondary" href="${studioUrl(p, Math.max(0, index - 1))}">Review ${STAGES[Math.max(0, index - 1)].name}${icon('arrow')}</a></section>`;
  if (busy.has(`${p.id}:${index}`)) return `<section class="workspace-card locked-workspace"><span class="busy-icon">${icon('spark')}</span><h2>Preparing your sample ${STAGES[index].name}</h2><p>Resolving the pinned profile, upstream revisions and reviewer guidance.<br>This is a simulated generation. You can return Home while it finishes.</p><div class="loading-track"><span></span></div></section>`;
  if (!current && index === 0) return uploadWorkspace(p);
  if (index === 4) return sandboxWorkspace(p);
  if (index === 5) return releaseWorkspace(p);
  if (!current) return `<section class="workspace-card locked-workspace"><span class="big-icon orange">${icon(STAGES[index].icon)}</span><div class="eyebrow">UPSTREAM APPROVALS COMPLETE</div><h2>Ready for ${STAGES[index].short.toLowerCase()}</h2><p>Use ${esc(p.profile.name)} profile v${p.profile.version} and the exact approved upstream revisions.${stage.feedback ? `<br>Reviewer guidance: ${esc(stage.feedback)}` : ''}</p>${btn('generate', STAGES[index].action, 'primary', 'spark')}</section>`;
  const json = JSON.stringify({ stage: STAGES[index].name, version: current.version, status: current.status, sources: current.sources, feedback: current.feedback, content: current.content }, null, 2);
  return `<section class="workspace-card document-card"><div class="document-toolbar"><div>${icon(STAGES[index].icon)}<strong>${STAGES[index].short}</strong><span class="version">v${current.version}</span></div><div class="view-toggle" aria-label="Artifact view"><button data-action="view" data-mode="document" class="${mode === 'document' ? 'active' : ''}">Document</button><button data-action="view" data-mode="json" class="${mode === 'json' ? 'active' : ''}">JSON</button></div></div>
    ${mode === 'json' ? `<pre class="json-view"><code>${esc(json)}</code></pre>` : `<article class="document"><div class="document-brand"><span>High<span>Studio</span></span><span>ENGINEERING DOCUMENT</span></div><div class="document-eyebrow">${esc(p.profile.name)} / ${STAGES[index].name} / V${current.version}</div><h2>${esc(p.name)}</h2><div class="document-metadata"><span>${esc(p.client)}</span><span>${esc(new Date(current.createdAt).toLocaleDateString())}</span></div><div class="document-rule"></div><div class="document-body">${esc(current.content.split('\n\n').slice(1).join('\n\n'))}</div></article>`}
    <div class="document-disclaimer">${icon('info')}Illustrative sample artifact. AI and deterministic validation are simulated.</div>
  </section>`;
}
function sandboxWorkspace(p) {
  const current = p.stages[4].current, approved = current?.status === 'approved';
  return `<section class="workspace-card"><div class="section-title"><span class="section-icon">${icon('flask')}</span><div><h2>Client sandbox verification</h2><p>Test the exact approved package before release.</p></div></div><div class="environment-tile"><span class="environment-icon">${icon('clients')}</span><div><strong>${esc(p.client)} · Sandbox</strong><small>${esc(p.profile.name)} · Simulated environment</small></div>${badge('Demo only', 'violet')}</div><div class="notice amber">No ERP is connected. The controls below record simulated outcomes, not real test evidence.</div>
    <div class="test-list">${['Installation contract', 'Output reconciliation', 'Retry and recovery'].map((name, i) => `<label class="test-row"><span><strong>${i + 1}. ${name}</strong><small>${['Verify configured files and installation order.', 'Compare output counts, totals and mapping.', 'Check duplicate delivery and failure recovery.'][i]}</small></span><select data-test="${i}" aria-label="${name} result" ${approved ? 'disabled' : ''}><option value="pass" ${p.tests[i]?.result !== 'fail' ? 'selected' : ''}>Demo: pass</option><option value="fail" ${p.tests[i]?.result === 'fail' ? 'selected' : ''}>Demo: fail</option></select></label>`).join('')}</div>
    ${current ? `<div class="notice ${approved ? 'green' : 'blue'}">${approved ? 'Tester signed off on the exact mock package revision.' : 'Results recorded. Review the outcomes and give explicit tester sign-off.'}</div>` : ''}<div class="workspace-bottom"><span>Package v${p.stages[3].current.version}</span>${!approved ? btn('record-tests', 'Record simulated run', 'primary', 'flask') : `<a class="btn primary" href="${studioUrl(p, 5)}">Continue to release${icon('arrow')}</a>`}</div></section>`;
}
function releaseWorkspace(p) {
  const current = p.stages[5].current;
  return `<section class="workspace-card release-workspace"><span class="release-emblem">${icon(current ? 'shield' : 'package')}</span><div class="eyebrow">${current ? 'DEMO DELIVERY COMPLETE' : 'ALL APPROVALS COMPLETE'}</div><h2>${current ? 'Your sample release is ready.' : 'Ready for final release.'}</h2><p>${current ? 'Download the configured files, source manifest and approval summary.' : 'The mock package has been reviewed and its simulated sandbox run signed off.'}<br>Artifacts are illustrative stubs. Do not install them in an ERP.</p><div class="release-summary">${[['ERP profile', `${p.profile.name} v${p.profile.version}`], ['Package revision', `v${p.stages[3].current.version}`], ['Sandbox evidence', `Simulated run v${p.stages[4].current.version}`]].map(([name, value]) => `<div><small>${name}</small><strong>${esc(value)}</strong></div>`).join('')}</div>${current ? btn('download', 'Download sample release', 'primary', 'download', `data-id="${p.id}"`) : btn('publish-release', 'Publish demo release', 'primary', 'shield')}<a class="text-link" href="${studioUrl(p, 3, 'files')}">Inspect configured files ${icon('arrow')}</a></section>`;
}
function reviewPanel(p, index) {
  const current = p.stages[index].current, unlocked = isUnlocked(p, index), isApproved = current?.status === 'approved';
  const waiting = current?.status === 'review';
  return `<aside class="context-panel"><section class="context-card"><div class="context-heading">${icon('shield')}<h3>Review & approval</h3></div>${badge(!unlocked ? 'Upstream approval required' : isApproved ? 'Approved' : current?.status === 'changes_requested' ? 'Changes requested' : waiting ? 'Awaiting human review' : 'Not submitted', isApproved ? 'green' : waiting ? 'amber' : 'slate')}
    <p>${isApproved ? `You approved revision v${current.version}. Revising it will invalidate current downstream work and retain the history.` : !unlocked ? 'Stages unlock in order. Historical approvals do not unlock a revised dependency.' : waiting ? 'Review this exact revision. Approve it or leave specific feedback for a new revision.' : current?.status === 'changes_requested' ? esc(current.changeRequest) : 'Generate or record the stage output before submitting an approval.'}</p>
    ${waiting ? `${index === 0 ? '<label class="acknowledge"><input id="acknowledge" type="checkbox">I have confirmed the scope, assumptions and acceptance criteria.</label>' : ''}${btn('approve', index === 4 ? 'Tester sign-off' : `Approve ${STAGES[index].name}`, 'primary full', 'check')}<label class="field-label" for="feedback">Reviewer feedback</label><textarea id="feedback" maxlength="2000" class="feedback" placeholder="What should change in the next revision?"></textarea>${index < 4 ? btn('request-changes', 'Request changes', 'secondary full', 'history') : ''}` : current ? btn('revise', current.status === 'changes_requested' ? 'Create corrected revision' : 'Revise this stage', 'secondary full', 'history') : ''}
    ${isApproved && index < 5 ? `<a class="text-link" href="${studioUrl(p, index + 1)}">Continue to ${STAGES[index + 1].name} ${icon('arrow')}</a>` : ''}<div class="reviewer"><span class="tiny-avatar">LE</span><span>Demo ${index === 4 ? 'tester' : 'reviewer'}<small>Roles simulated in this prototype</small></span></div></section>
    <section class="context-card"><div class="context-heading">${icon('layers')}<h3>Configured context</h3></div><dl><dt>ERP profile</dt><dd>${esc(p.profile.name)} <span class="version">v${p.profile.version}</span></dd><dt>Standard package</dt><dd>${esc(p.profile.baseline)}</dd><dt>Knowledge pack</dt><dd>${esc(p.profile.knowledge)}</dd><dt>Implementation strategy</dt><dd>${esc(p.profile.language)}</dd></dl><a class="text-link" href="${studioUrl(p, index, 'sources')}">Why this output? ${icon('arrow')}</a></section>
    <section class="context-card"><div class="context-heading">${icon('history')}<h3>Recent activity</h3></div><div class="activity-list">${p.events.slice(0, 3).map(e => `<div><span class="activity-dot"></span><strong>${esc(e.summary)}</strong><small>${relative(e.at)}</small></div>`).join('') || '<p>Project draft saved. Add requirements to get started.</p>'}</div></section></aside>`;
}
function historyWorkspace(p) {
  const revisions = p.stages.flatMap((stage, index) => [stage.current && { ...stage.current, index, active: true }, ...stage.history.map(current => ({ ...current, index, active: false }))].filter(Boolean));
  return `<section class="workspace-card"><div class="section-title"><span class="section-icon">${icon('history')}</span><div><h2>Revision history</h2><p>Old content and approval decisions stay unchanged when you revise.</p></div></div>${revisions.length ? `<div class="revision-list">${revisions.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).map(r => `<button class="revision-row" data-action="inspect-revision" data-stage="${r.index}" data-version="${r.version}"><span class="revision-icon">${icon(STAGES[r.index].icon)}</span><span><strong>${STAGES[r.index].short} <span class="version">v${r.version}</span></strong><small>${esc(new Date(r.createdAt).toLocaleString())} · ${r.active ? 'Current revision' : 'Historical · read only'}</small></span>${badge(r.status === 'approved' ? 'Approved' : r.status === 'changes_requested' ? 'Changes requested' : 'In review', r.status === 'approved' ? 'green' : 'amber')}${icon('chevron')}</button>`).join('')}</div>` : '<div class="empty-table">Your first generation will appear here.</div>'}
    ${p.releases.length ? `<h3 class="subheading">Preserved releases</h3>${p.releases.map(r => `<div class="uploaded-file">${icon('package')}<div><strong>Sample release v${r.version}</strong><small>${esc(new Date(r.at).toLocaleString())} · immutable demo snapshot</small></div>${btn('download-history', 'Download', 'secondary', 'download', `data-version="${r.version}"`)}</div>`).join('')}` : ''}<h3 class="subheading">Activity log</h3><div class="event-log">${p.events.map(e => `<div><span>${esc(new Date(e.at).toLocaleString())}</span><strong>${esc(e.summary)}</strong></div>`).join('') || '<p>No engineering activity yet.</p>'}</div></section>`;
}
function sourcesWorkspace(p, index) {
  const current = p.stages[index].current;
  return `<section class="workspace-card"><div class="section-title"><span class="section-icon">${icon('layers')}</span><div><h2>Why was this generated this way?</h2><p>Configuration and source versions. No hidden reasoning.</p></div></div><div class="notice blue">Source selection and generation are simulated. The profile is pinned to this project.</div><div class="source-grid">${[['ERP profile', `${p.profile.name} v${p.profile.version}`], ['Prompt version', current?.sources?.prompt || p.profile.prompt], ['Standard package', current?.sources?.baseline || p.profile.baseline], ['Knowledge asset', current?.sources?.knowledge || p.profile.knowledge], ['Model', 'Simulated · no API call'], ['Generation configuration', `Profile strategy: ${p.profile.language}`]].map(([label, value]) => `<div><span>${icon('file')}</span><small>${label}</small><strong>${esc(value)}</strong></div>`).join('')}</div><h3 class="subheading">Approved upstream artifact versions</h3>${(current?.sources?.upstream || []).map(source => `<div class="source-row">${icon('check')}<span>${esc(source.stage)}</span><span class="version">v${source.version}</span></div>`).join('') || '<p class="muted">No upstream versions recorded for this stage yet.</p>'}<h3 class="subheading">Reviewer guidance</h3><div class="notice slate">${esc(current?.feedback || p.stages[index].feedback || 'No reviewer feedback used for this revision.')}</div></section>`;
}
function filesWorkspace(p) {
  const current = p.stages[3].current;
  if (!current?.files?.length) return `<section class="workspace-card locked-workspace"><span class="big-icon">${icon('package')}</span><h2>No package files yet</h2><p>Approve Requirements, FDD and TDD, then generate the configured package.</p><a class="btn secondary" href="${studioUrl(p, currentStage(p))}">Return to current stage ${icon('arrow')}</a></section>`;
  fileIndex = Math.min(fileIndex, current.files.length - 1);
  return `<section class="workspace-card files-card"><div class="section-title"><span class="section-icon">${icon('package')}</span><div><h2>Configured implementation files</h2><p>${esc(p.profile.language)} · Package revision v${current.version} · Sample stubs</p></div>${packageEligible(p) ? btn('download', 'Download package', 'primary', 'download', `data-id="${p.id}"`) : badge('Review required', 'amber')}</div><div class="file-tabs">${current.files.map((file, i) => `<button class="${fileIndex === i ? 'active' : ''}" data-action="select-file" data-file="${i}">${icon('code')}${esc(file.name)}</button>`).join('')}</div><div class="code-caption"><span>${esc(current.files[fileIndex].name)}</span>${btn('download-file', 'Download file', 'ghost', 'download', `data-file="${fileIndex}" ${!packageEligible(p) ? 'disabled' : ''}`)}</div><pre class="code-view"><code>${esc(current.files[fileIndex].content)}</code></pre><div class="document-disclaimer">${icon('info')}Mock code cannot implement a client requirement. Never install these files.</div></section>`;
}
function studio() {
  const p = project(), { index, tab } = route();
  if (!p) return route().id ? `<div class="page"><div class="workspace-card locked-workspace"><h1>Project not found</h1><p>This mock does not contain that project.</p><a class="btn secondary" href="#home">Back to Home</a></div></div>` : directory(true);
  const status = statusOf(p), active = p.stages.filter(s => s.current?.status === 'approved').length;
  const tabs = [['workspace', 'Workspace'], ['history', 'History'], ['sources', 'Source details'], ['files', 'Package files']];
  return `<div class="page studio-page"><div class="breadcrumbs"><a href="#home">${icon('back')}All projects</a><span>/</span><span>Engineering Studio</span></div><div class="studio-heading"><div><div class="eyebrow">${esc(p.client)} <span>·</span> ${esc(p.type)} INTEGRATION</div><h1>${esc(p.name)}</h1><div class="project-facts"><span>${esc(p.profile.name)} <b>v${p.profile.version}</b></span><span class="fact-divider"></span><span>${icon('clock')}Due ${p.due ? esc(new Date(`${p.due}T12:00:00`).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })) : 'not set'}</span><span class="fact-divider"></span><span data-save-label>${esc(saveStatus)}</span>${btn('edit-project', 'Edit details', 'ghost')}</div></div><div class="studio-status">${badge(status.label, status.tone)}<small>${active} of 6 gates approved</small></div></div>${stageStrip(p, index)}
    <div class="studio-tabs" role="navigation" aria-label="Studio workspaces">${tabs.map(([id, name]) => `<a class="${tab === id ? 'active' : ''}" href="${studioUrl(p, index, id)}">${name}${id === 'history' ? `<span class="count">${p.stages.reduce((n, s) => n + s.history.length, 0)}</span>` : ''}</a>`).join('')}<span class="tab-note">${icon('lock')}Human approval at every gate</span></div>
    <div class="studio-layout">${tab === 'history' ? historyWorkspace(p) : tab === 'sources' ? sourcesWorkspace(p, index) : tab === 'files' ? filesWorkspace(p) : documentWorkspace(p, index)}${reviewPanel(p, index)}</div></div>`;
}
function clientsPage() {
  return `<div class="page"><div class="page-heading"><div><div class="eyebrow">CLIENT WORKSPACE</div><h1>Clients</h1><p>Every project belongs to a client and a pinned ERP profile.</p></div>${badge('Sample directory', 'blue')}</div><div class="client-grid">${CLIENTS.map(c => {
    const projects = state.projects.filter(p => p.client === c.name);
    return `<section class="client-card"><div class="client-card-top">${clientAvatar(c.name)}${badge('Demo client', 'slate')}</div><h2>${esc(c.name)}</h2><p>${c.industry} · ${c.region}</p><div class="client-count"><strong>${projects.length}</strong><span>Integration projects</span></div><div class="client-projects">${projects.map(p => `<a href="${studioUrl(p)}">${esc(p.name)}${icon('arrow')}</a>`).join('')}</div></section>`;
  }).join('')}</div></div>`;
}
function profilesPage() {
  return `<div class="page"><div class="page-heading"><div><div class="eyebrow">ADMINISTRATION / ERP CONFIGURATION</div><h1>ERP profiles</h1><p>Configure an ERP's intelligence and implementation artifacts.</p></div>${btn('add-profile', 'Add ERP', 'primary', 'plus')}</div><div class="notice blue">Mock registry. Add a profile through this UI to use it in a new project. Existing projects retain their pinned version.</div><div class="profile-grid">${state.profiles.map(p => `<section class="profile-card"><div class="profile-top"><span class="profile-icon">${icon('layers')}</span>${badge('Published · demo', 'green')}</div><h2>${esc(p.name)}</h2><p>${esc(p.vendor)} <span class="version">v${p.version}</span></p><dl><dt>Generation strategy</dt><dd>${esc(p.language)}</dd><dt>Prompt</dt><dd>${esc(p.prompt)}</dd><dt>Standard package</dt><dd>${esc(p.baseline)}</dd><dt>Knowledge</dt><dd>${esc(p.knowledge)}</dd></dl><div class="profile-outputs">${p.templates.map(t => `<span>${esc(t.name.replace('{{package}}', 'package'))}</span>`).join('')}</div>${btn('edit-profile', 'Configure new version', 'secondary full', 'settings', `data-id="${p.id}"`)}</section>`).join('')}</div></div>`;
}
function render() {
  const { page } = route();
  const active = document.activeElement, focusId = active?.id, cursor = active?.selectionStart;
  const scroll = document.querySelector('#main')?.scrollTop || 0;
  shell(page === 'studio' ? studio() : page === 'clients' ? clientsPage() : page === 'profiles' ? profilesPage() : directory());
  const main = document.querySelector('#main'); main.scrollTop = scroll;
  if (focusId) { const input = document.getElementById(focusId); input?.focus(); if (typeof cursor === 'number' && input?.setSelectionRange) input.setSelectionRange(cursor, cursor); }
  attachUpload();
}
function modal(title, body, submit = '', form = '') {
  dialog.innerHTML = `<div class="modal-heading"><div><div class="eyebrow">HIGHSTUDIO WORKSPACE</div><h2 id="dialog-title">${title}</h2></div><button class="icon-button" data-action="close" aria-label="Close dialog">${icon('close')}</button></div><form ${form ? `data-form="${form}"` : ''}><div class="modal-body">${body}</div><div class="modal-footer">${btn('close', 'Cancel', 'secondary')}${submit ? `<button class="btn primary" type="submit">${submit}${icon('arrow')}</button>` : ''}</div></form>`;
  dialog.showModal();
}
function createModal() {
  modal('Create a new integration project', `<p class="modal-intro">Save a draft, then upload the consulting requirement in Studio.</p><div class="form-grid"><label class="span-two">Project name<input name="name" required maxlength="100" placeholder="e.g. AP invoice extraction"></label><label>Client<select name="client" required>${CLIENTS.map(c => `<option>${esc(c.name)}</option>`).join('')}</select></label><label>ERP profile<select name="profile" required>${state.profiles.map(p => `<option value="${p.id}">${esc(p.name)} · v${p.version}</option>`).join('')}</select></label><label>Integration type<select name="type"><option>Custom</option><option>Standard</option></select></label><label>Due date <span class="optional">optional</span><input name="due" type="date"></label></div><div class="notice slate">Standard uses supported baseline configuration. Custom modifies or extends the baseline. The ERP profile version is pinned when you create this project.</div>`, 'Create & open Studio', 'create');
}
function revisionModal() {
  const p = project(), { index } = route(), downstream = p.stages.slice(index + 1).filter(stage => stage.current).length;
  modal(`Revise ${STAGES[index].name}`, `<p class="modal-intro">Create a new revision at this point in the workflow.</p><div class="notice amber"><strong>${downstream ? `${downstream} downstream stages will return to a locked state.` : 'Subsequent stages will require this new approval.'}</strong> Existing revisions, approval decisions and previous releases remain in History.</div><label class="field-label" for="revision-reason">Requested changes</label><textarea id="revision-reason" name="reason" required maxlength="2000" class="feedback" placeholder="Describe what should change">${esc(p.stages[index].current?.changeRequest || '')}</textarea>${index === 0 ? `<label class="field-label" for="revised-brief">Updated requirement text</label><textarea id="revised-brief" name="brief" minlength="30" maxlength="20000" required class="brief">${esc(p.brief)}</textarea>` : ''}`, 'Create revision', 'revise');
}
function profileModal(profile) {
  modal(profile ? `Publish ${esc(profile.name)} v${profile.version + 1}` : 'Add an ERP profile', `<p class="modal-intro">Configure a demo ERP without changing application code.</p><div class="form-grid"><label>ERP name<input name="name" required maxlength="80" value="${esc(profile?.name || '')}" placeholder="e.g. Contoso ERP"></label><label>Vendor<input name="vendor" required maxlength="80" value="${esc(profile?.vendor || '')}"></label><label>Implementation strategy<input name="language" required maxlength="80" value="${esc(profile?.language || 'JavaScript')}"></label><label>Output filename<input name="filename" required pattern="[A-Za-z0-9_.{}-]+" maxlength="100" value="${esc(profile?.templates[0].name || '{{package}}.js')}"></label><label class="span-two">Prompt / guidance<input name="prompt" required maxlength="1000" value="${esc(profile?.prompt || '')}" placeholder="Describe guidance for this ERP"></label><label>Standard package<input name="baseline" required maxlength="100" value="${esc(profile?.baseline || '')}" placeholder="Demo baseline v1"></label><label>Knowledge pack<input name="knowledge" required maxlength="100" value="${esc(profile?.knowledge || '')}" placeholder="Demo ERP standards v1"></label><label class="span-two">Sample output template<textarea name="template" required maxlength="10000" class="code-input">${esc(profile?.templates[0].content || '// MOCK ONLY · {{erp}} · {{project}} · revision {{revision}}\n// Implementation follows the approved TDD.\n')}</textarea></label></div><div class="notice slate">This mock publishes the new version immediately. It simulates profile configuration; production review and role enforcement are not included.</div><input type="hidden" name="profileId" value="${esc(profile?.id || '')}">`, 'Publish demo profile', 'profile');
}
function blobDownload(name, content, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([content], { type })), anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
}
async function download(p, historical) {
  if (!historical && !packageEligible(p)) throw new Error('Approve the current package before downloading.');
  const released = historical || (p.stages[5].current?.status === 'approved' ? p.releases.find(r => r.version === p.stages[5].current.releaseVersion) : null);
  const files = released?.files || p.stages[3].current.files;
  const manifest = { mock: true, warning: 'SAMPLE ARTIFACTS ONLY. Do not install or execute.', project: p.name, client: p.client, profile: `${p.profile.name} v${p.profile.version}`, kind: released ? 'demo-release' : 'demo-candidate', sources: released?.sources || p.stages[3].current.sources, approvals: released?.approvals || p.stages.slice(0, 4).map((s, i) => ({ stage: STAGES[i].name, version: s.current.version, approvedAt: s.current.approvedAt })), files: await Promise.all(files.map(async file => ({ name: file.name, sha256: [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(file.content)))].map(b => b.toString(16).padStart(2, '0')).join('') }))) };
  const archive = zipFiles([...files, { name: 'manifest.json', content: JSON.stringify(manifest, null, 2) }, { name: 'README.txt', content: 'HighStudio mock package\n\nSample stubs only. Do not deploy or execute these files.\nNo AI generation, ERP connection, installation or live tests occurred.\nSee manifest.json for the exact demo source versions and file checksums.\n' }]);
  blobDownload(`${p.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${released ? `release-v${released.version}` : 'candidate'}.zip`, archive, 'application/zip');
  toast('Sample package downloaded. Do not install these mock artifacts.');
}
async function action(button) {
  const name = button.dataset.action, p = project(), { index } = route();
  try {
    if (name === 'close') return dialog.close();
    if (name === 'help') return modal('About this local prototype', '<p>This is a standalone vanilla JavaScript mock of HighStudio. Use it to explore Home, Engineering Studio, document intake, approvals, revisions and downloads.</p><div class="notice amber">Use sample documents only. Demo data and text you enter are stored on this browser. No real client credentials should be entered.</div><p>No AI calls, ERP connections, authentication, PDF/DOCX parsing or real sandbox tests are performed. No external scripts, fonts, analytics or telemetry are loaded.</p><div class="about-actions">' + btn('sample-download', 'Download sample requirement', 'secondary', 'download') + btn('reset-demo', 'Reset demo data', 'secondary', 'history') + '</div>');
    if (name === 'create') return createModal();
    if (name === 'reset-demo') { modal('Reset demo data?', '<p>This clears locally saved demo projects, revisions and ERP profile changes, then restores the sample data.</p>', 'Reset demo', 'reset'); return; }
    if (name === 'sample-download') return blobDownload('Consulting_requirement_brief.txt', SAMPLE_BRIEF);
    if (name === 'metric') { filters.status = button.dataset.status; filters.page = 0; return render(); }
    if (name === 'reset-filters') { Object.assign(filters, { search: '', erp: '', type: '', status: '', page: 0 }); return render(); }
    if (name === 'page-prev' || name === 'page-next') { filters.page += name === 'page-prev' ? -1 : 1; return render(); }
    if (name === 'add-profile' || name === 'edit-profile') return profileModal(state.profiles.find(profile => profile.id === button.dataset.id));
    if (name === 'download') return await download(state.projects.find(item => item.id === button.dataset.id) || p);
    if (!p) throw new Error('Open a project first.');
    if (name === 'sample') { p.brief = SAMPLE_BRIEF; p.files = [{ name: 'Consulting_requirement_brief.txt', size: SAMPLE_BRIEF.length, sample: true }]; event(p, 'Sample consulting brief added', 0); }
    if (name === 'remove-file') { p.files.splice(Number(button.dataset.file), 1); event(p, 'Requirement document metadata removed', 0); }
    if (name === 'view') { mode = button.dataset.mode; return render(); }
    if (name === 'select-file') { fileIndex = Number(button.dataset.file); return render(); }
    if (name === 'download-file') { if (!packageEligible(p)) throw new Error('Approve the package first.'); const file = p.stages[3].current.files[Number(button.dataset.file)]; return blobDownload(file.name, file.content); }
    if (name === 'download-history') return await download(p, p.releases.find(r => r.version === Number(button.dataset.version)));
    if (name === 'generate') {
      const key = `${p.id}:${index}`;
      if (busy.has(key)) return;
      busy.add(key); render();
      setTimeout(() => {
        try { generate(p, index); persist(); toast(`${STAGES[index].name} sample ready for review.`); }
        catch (error) { toast(error.message); }
        finally { busy.delete(key); render(); }
      }, 1000);
      return;
    }
    if (name === 'approve') {
      if (index === 0 && !document.querySelector('#acknowledge')?.checked) throw new Error('Confirm the requirement scope and assumptions before approving.');
      if (index === 4 && [...document.querySelectorAll('[data-test]')].some((input, i) => input.value !== p.tests[i]?.result)) throw new Error('Record the updated demo test outcomes before signing off.');
      modal(`Approve ${STAGES[index].name} v${p.stages[index].current.version}?`, `<p>You are approving the exact displayed revision for <strong>${esc(p.name)}</strong>.</p><div class="notice slate">${index === 4 ? 'This records a demo tester sign-off. No real sandbox testing occurred.' : 'The next stage will unlock. This approval is recorded in project history.'}</div><input name="stage" type="hidden" value="${index}"><input name="version" type="hidden" value="${p.stages[index].current.version}">`, index === 4 ? 'Confirm tester sign-off' : 'Confirm approval', 'approve'); return;
    }
    if (name === 'request-changes') requestChanges(p, index, document.querySelector('#feedback').value);
    if (name === 'revise') return revisionModal();
    if (name === 'record-tests') recordTests(p, [...document.querySelectorAll('[data-test]')].map((input, i) => ({ name: ['Installation contract', 'Output reconciliation', 'Retry and recovery'][i], result: input.value })));
    if (name === 'publish-release') publishRelease(p);
    if (name === 'edit-project') return modal('Edit project details', `<div class="form-grid"><label class="span-two">Project name<input name="name" required maxlength="100" value="${esc(p.name)}"></label><label>Due date<input name="due" type="date" value="${esc(p.due)}"></label><label>Integration type<input value="${esc(p.type)}" disabled></label></div><div class="notice slate">Changing the deadline does not invalidate approvals. Revise the relevant stage to change engineering inputs.</div>`, 'Save details', 'details');
    if (name === 'inspect-revision') {
      const stage = p.stages[Number(button.dataset.stage)], version = Number(button.dataset.version), historical = stage.history.find(r => r.version === version), revision = historical || stage.current;
      return modal(`${STAGES[Number(button.dataset.stage)].name} v${version} · ${historical ? 'historical' : 'current'}`, `<div class="notice slate">Read only. Opening history does not change current work or approvals.</div>${badge(revision.status, revision.status === 'approved' ? 'green' : 'amber')}<pre class="history-preview">${esc(revision.content || '')}</pre>`);
    }
    persist(); render();
  } catch (error) { toast(error.message || 'This action could not be completed.'); }
}
document.addEventListener('click', e => {
  const button = e.target.closest('[data-action]');
  if (button) { e.preventDefault(); action(button); }
});
document.addEventListener('input', e => {
  if (e.target.dataset.filter) {
    filters[e.target.dataset.filter] = e.target.value; filters.page = 0; render();
  }
  if (e.target.id === 'brief') {
    const p = project(); p.brief = e.target.value; p.updatedAt = new Date().toISOString(); setSaveLabel('Saving…');
    document.querySelector('[data-action="generate"]').disabled = p.brief.trim().length < 30;
    clearTimeout(saveTimer); saveTimer = setTimeout(persist, 350);
  }
});
document.addEventListener('submit', e => {
  if (!e.target.dataset.form) return;
  e.preventDefault();
  const form = e.target.dataset.form, data = Object.fromEntries(new FormData(e.target)), p = project();
  try {
    if (form === 'create') {
      if (!data.name.trim()) throw new Error('Enter a project name.');
      const profile = state.profiles.find(profile => profile.id === data.profile);
      const created = createProject({ ...data, name: data.name.trim(), profile });
      state.projects.unshift(created); event(created, 'Project draft created'); persist(); dialog.close(); location.hash = studioUrl(created, 0); toast('Draft created. Add your requirement document to begin.'); return;
    }
    if (form === 'approve') {
      const index = Number(data.stage); if (p.stages[index].current?.version !== Number(data.version)) throw new Error('This revision has changed. Reopen the approval.');
      approve(p, index); toast(`${STAGES[index].name} approved. ${index < 5 ? STAGES[index + 1].name + ' is unlocked.' : ''}`);
    }
    if (form === 'revise') { revise(p, route().index, data.reason); if (route().index === 0) p.brief = data.brief; toast('New revision started. Prior revisions are preserved in History.'); }
    if (form === 'details') { if (!data.name.trim()) throw new Error('Enter a project name.'); p.name = data.name.trim(); p.due = data.due; event(p, 'Project details updated'); }
    if (form === 'reset') { if (busy.size) throw new Error('Wait for simulated generation to finish before resetting.'); state = seed(); location.hash = '#home'; }
    if (form === 'profile') {
      if (Object.entries(data).some(([key, value]) => key !== 'profileId' && !value.trim())) throw new Error('Complete all ERP configuration fields.');
      const existing = state.profiles.find(profile => profile.id === data.profileId);
      if (!existing && state.profiles.some(profile => profile.name.toLowerCase() === data.name.trim().toLowerCase())) throw new Error('An ERP profile with this name already exists.');
      const profile = { id: existing?.id || crypto.randomUUID(), name: data.name.trim(), vendor: data.vendor.trim(), version: (existing?.version || 0) + 1, language: data.language.trim(), prompt: data.prompt.trim(), baseline: data.baseline.trim(), knowledge: data.knowledge.trim(), templates: existing ? existing.templates.map((template, i) => i ? template : { name: data.filename, content: data.template }) : [{ name: data.filename, content: data.template }] };
      if (existing) state.profiles[state.profiles.indexOf(existing)] = profile; else state.profiles.push(profile);
      toast(`Published demo profile v${profile.version}. Existing projects keep their pinned version.`);
    }
    persist(); dialog.close(); render();
  } catch (error) { toast(error.message || 'Could not save these changes.'); }
});
async function upload(files) {
  const p = project(); if (!p || p.stages[0].current || busy.has(`${p.id}:0`)) return;
  let textAdded = false, added = false;
  for (const file of files) {
    if (!/\.(pdf|docx|txt|md)$/i.test(file.name) || file.size > 10 * 1024 * 1024) { toast(`${file.name}: use PDF, DOCX, TXT or MD under 10 MB.`); continue; }
    if (p.files.length >= 10) { toast('This mock allows up to 10 requirement files.'); break; }
    if (p.files.some(f => f.name === file.name)) { toast(`${file.name} is already listed.`); continue; }
    if (/\.(txt|md)$/i.test(file.name)) { const text = await file.text(); p.brief = (p.brief + '\n\n' + text).trim().slice(0, 20000); textAdded = true; }
    p.files.push({ name: file.name, size: file.size, sample: false }); added = true;
  }
  if (added) { event(p, 'Requirement document added (local mock)', 0); persist(); render(); toast(textAdded ? 'Text read locally. Review the extracted brief before analysis.' : 'File metadata added. PDF/DOCX parsing is not included; paste text or use the sample brief.'); }
}
function attachUpload() {
  document.querySelector('#files')?.addEventListener('change', e => upload(e.target.files).catch(() => toast('Could not read the selected document.')));
  const drop = document.querySelector('#dropzone');
  drop?.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragging'); });
  drop?.addEventListener('dragleave', () => drop.classList.remove('dragging'));
  drop?.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('dragging'); upload(e.dataTransfer.files).catch(() => toast('Could not read the dropped document.')); });
}
window.addEventListener('hashchange', () => { mode = 'document'; render(); document.querySelector('#main').scrollTop = 0; });
window.addEventListener('pagehide', () => { clearTimeout(saveTimer); persist(); });
dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
persist(); render();
