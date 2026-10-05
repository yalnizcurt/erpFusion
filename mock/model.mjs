// This is a browser-only product prototype. All generation and test evidence is synthetic.
export const STAGES = [
  { key: 'requirements', name: 'Requirements', short: 'Requirement assessment', icon: 'file', action: 'Analyze requirements' },
  { key: 'fdd', name: 'FDD', short: 'Functional design', icon: 'layers', action: 'Generate FDD' },
  { key: 'tdd', name: 'TDD', short: 'Technical design', icon: 'code', action: 'Generate TDD' },
  { key: 'package', name: 'Package', short: 'Package adaptation', icon: 'package', action: 'Generate package' },
  { key: 'sandbox', name: 'Sandbox', short: 'Sandbox testing', icon: 'flask', action: 'Record test run' },
  { key: 'release', name: 'Release', short: 'Final release', icon: 'download', action: 'Publish demo release' },
];
export const SAMPLE_BRIEF = `Invoice extraction and reconciliation integration

Business objective
Send open accounts-payable invoices and invoice lines to the HighRadius reconciliation platform every business day at 02:00 UTC.

Scope
Include invoices in approved and unpaid status. Exclude cancelled invoices and confidential supplier bank information. Include invoice number, supplier ID, currency, gross amount, remaining amount, due date and line distributions.

Delivery contract
UTF-8 CSV with a header row, ISO-8601 dates and decimal amounts. Deliver through the organization's approved secure file channel. Maximum 50,000 invoices per run. Use the approved ERP standard extraction package as the baseline.

Operations
Support incremental extraction using last-updated timestamp, idempotent reruns, an audit log and three retries on transient errors. Alert the operations team after final failure.

Acceptance criteria
Reconcile row count and totals with source data. Test empty results, duplicate delivery and failure recovery in the client sandbox. No production deployment before tester sign-off.`;

const oracleTemplates = [
  { name: '{{package}}.pks', content: '-- MOCK ONLY. Not a deployable ERP implementation.\n-- {{project}} | {{erp}} | revision {{revision}}\nCREATE OR REPLACE PACKAGE {{package}} AS\n  PROCEDURE run_extract(p_from_date IN DATE, p_run_id IN VARCHAR2);\nEND {{package}};\n/\n' },
  { name: '{{package}}.pkb', content: '-- MOCK ONLY. Do not install in any ERP environment.\n-- Baseline: approved extraction / logging / file writer patterns\nCREATE OR REPLACE PACKAGE BODY {{package}} AS\n  PROCEDURE run_extract(p_from_date IN DATE, p_run_id IN VARCHAR2) IS\n  BEGIN\n    RAISE_APPLICATION_ERROR(-20000, \'Mock artifact: implementation is not generated\');\n  END run_extract;\nEND {{package}};\n/\n' },
];
const initialProfiles = [
  { id: 'fusion', name: 'Oracle Fusion Cloud', vendor: 'Oracle', version: 4, language: 'SQL + PL/SQL', baseline: 'Standard Extract Package v5', knowledge: 'Integration standards v3', prompt: 'Invoice engineering v7', templates: oracleTemplates },
  { id: 'sap', name: 'SAP S/4HANA', vendor: 'SAP', version: 2, language: 'ABAP', baseline: 'Integration Pattern Pack v2', knowledge: 'ABAP standards v4', prompt: 'SAP integration design v3', templates: [{ name: '{{package}}.abap', content: '* MOCK ONLY. Not a deployable implementation.\n* {{project}} | {{erp}} | revision {{revision}}\nREPORT {{package}}.\nWRITE: / \'Demo artifact. Implementation adapter required.\'.\n' }] },
  { id: 'netsuite', name: 'Oracle NetSuite', vendor: 'Oracle', version: 3, language: 'SuiteScript', baseline: 'SuiteScript Extract Template v2', knowledge: 'Integration handbook v2', prompt: 'SuiteScript engineering v4', templates: [{ name: '{{package}}.js', content: '// MOCK ONLY. Not a deployable ERP implementation.\n// {{project}} | {{erp}} | revision {{revision}}\nthrow new Error("Demo artifact: implementation is not generated");\n' }] },
  { id: 'dynamics', name: 'Dynamics 365 F&O', vendor: 'Microsoft', version: 2, language: 'X++', baseline: 'Data Export Pattern v3', knowledge: 'Data entity standards v2', prompt: 'Finance integration design v2', templates: [{ name: '{{package}}.xpp', content: '// MOCK ONLY. Not a deployable ERP implementation.\n// {{project}} | {{erp}} | revision {{revision}}\n// Approved data-entity adapter implementation belongs here.\n' }] },
  { id: 'demo', name: 'Demo ERP', vendor: 'Demo Systems', version: 1, language: 'JavaScript', baseline: 'Demo Integration Template v1', knowledge: 'Demo ERP handbook v1', prompt: 'Demo engineering v1', templates: [{ name: '{{package}}.js', content: '// MOCK ONLY. {{project}} | {{erp}} | revision {{revision}}\nexport function extract() { throw new Error("Demo artifact only"); }\n' }] },
];
export const CLIENTS = [
  { name: 'Northstar Manufacturing', initials: 'NM', color: 'blue', industry: 'Manufacturing', region: 'North America' },
  { name: 'Meridian Healthcare', initials: 'MH', color: 'violet', industry: 'Healthcare', region: 'Europe' },
  { name: 'Atlas Retail Group', initials: 'AR', color: 'orange', industry: 'Retail', region: 'North America' },
  { name: 'Summit Energy', initials: 'SE', color: 'green', industry: 'Energy', region: 'Asia Pacific' },
  { name: 'Cedar Financial', initials: 'CF', color: 'teal', industry: 'Financial services', region: 'Europe' },
];
export function createProject({ name, client, profile, type = 'Custom', due = '' }) {
  return {
    id: globalThis.crypto.randomUUID(), name, client, profile: structuredClone(profile), type, due,
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), brief: '', files: [],
    stages: STAGES.map(() => ({ current: null, history: [], serial: 0 })), events: [], tests: [], releases: [],
  };
}
export function currentStage(project) {
  const index = project.stages.findIndex(stage => stage.current?.status !== 'approved');
  return index < 0 ? STAGES.length - 1 : index;
}
export function isUnlocked(project, index) {
  return project.stages.slice(0, index).every(stage => stage.current?.status === 'approved');
}
export function packageEligible(project) {
  return project.stages.slice(0, 4).every(stage => stage.current?.status === 'approved');
}
export function statusOf(project) {
  if (project.stages.every(stage => stage.current?.status === 'approved')) return { label: 'Completed', tone: 'green', detail: 'Tested release available' };
  const index = currentStage(project), current = project.stages[index].current;
  if (current?.status === 'changes_requested') return { label: 'Changes requested', tone: 'red', detail: `${STAGES[index].name} · revision v${current.version}` };
  if (index === 4 && !current) return { label: 'Ready for sandbox', tone: 'blue', detail: 'Package approved' };
  if (index === 5) return { label: 'Ready for release', tone: 'green', detail: 'Sandbox signed off' };
  if (index === 4) return { label: 'Testing', tone: 'violet', detail: 'Awaiting tester sign-off' };
  if (current) return { label: index === 0 ? 'Requirement review' : `${STAGES[index].name} review`, tone: 'amber', detail: `Waiting for approval · v${current.version}` };
  return { label: index === 0 ? 'Draft' : `${STAGES[index].name} pending`, tone: 'slate', detail: index === 0 ? 'Upload requirements to begin' : 'Ready to generate' };
}
export function event(project, summary, index, version) {
  project.updatedAt = new Date().toISOString();
  project.events.unshift({ id: globalThis.crypto.randomUUID(), at: project.updatedAt, summary, stage: index, version });
}
function invalidateAfter(project, index) {
  for (const stage of project.stages.slice(index + 1)) {
    if (stage.current) stage.history.unshift(structuredClone(stage.current));
    stage.current = null;
  }
  project.tests = [];
  // Historical releases and approval decisions remain unchanged.
}
export function revise(project, index, reason) {
  if (!reason.trim()) throw new Error('Describe the requested change.');
  if (!isUnlocked(project, index)) throw new Error('Approve the preceding stage first.');
  const stage = project.stages[index];
  if (stage.current) stage.history.unshift(structuredClone(stage.current));
  stage.current = null;
  stage.feedback = reason.trim();
  invalidateAfter(project, index);
  event(project, `Revision requested: ${reason.trim()}`, index);
}
function fill(template, values) {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key] ?? `{{${key}}}`);
}
export function generate(project, index) {
  if (!isUnlocked(project, index)) throw new Error('Approve the preceding stage first.');
  if (project.stages[index].current) throw new Error('Start a revision before regenerating.');
  if (index > 3) throw new Error('Use the sandbox or release actions.');
  if (project.brief.trim().length < 30) throw new Error('Add a requirement brief of at least 30 characters.');
  const stage = project.stages[index], version = ++stage.serial;
  const profile = project.profile;
  const sources = { profile: `${profile.name} v${profile.version}`, prompt: profile.prompt, knowledge: profile.knowledge, baseline: profile.baseline, requirementVersion: project.stages[0].current?.version || version, upstream: project.stages.slice(0, index).map((s, i) => ({ stage: STAGES[i].name, version: s.current.version })), model: 'Simulated · no LLM request' };
  const feedback = stage.feedback || '';
  const intro = `${project.name}\n${STAGES[index].short} · v${version}\n${profile.name} · profile v${profile.version}\n\nMOCK DOCUMENT — illustrative content; not generated by AI.\n\n`;
  const sections = [
    `01  Requirement assessment\nThe supplied brief describes a scheduled extraction integration. Confirm the scope and acceptance criteria before approving.\n\n02  Items for human confirmation\n• Source object names and field permissions are not verified.\n• Confirm the client's business timezone and cutoff.\n• Confirm the secure delivery endpoint and retention policy.\n\n03  Requirement brief\n${project.brief}\n\n04  Proposed next step\nApprove this exact requirement revision to unlock the functional design.`,
    `01  Business objective\nCreate a traceable extraction and reconciliation process for ${project.client}.\n\n02  Functional scope\nApply the filters, delivery schedule and exclusions in the approved requirement. Map invoice header and line data to the agreed output contract.\n\n03  Operational behavior\nIncremental processing, duplicate protection, bounded retries and an exception report.\n\n04  Acceptance criteria\nReconcile counts and totals, test empty results and failure recovery, and obtain sandbox sign-off.\n\n05  Source requirement\n${project.brief}`,
    `01  Implementation strategy\nUse the profile-configured ${profile.language} strategy and ${profile.baseline}.\n\n02  Technical contract\nInput: last successful cutoff and unique run identifier.\nOutput: the approved mapping and delivery contract.\n\n03  Baseline adaptation\nRetain standard logging, secure delivery and error handling. Adapt selection and mapping to the approved FDD.\n\n04  Safety and validation\nVerify schema objects, access permissions, mapping completeness and retry behavior in the client sandbox. This mock does not perform these checks.\n\n05  Deployment\nPrepare versioned artifacts and installation instructions. Tester approval is required before a release.`,
    `01  Adapted package preview\nBaseline: ${profile.baseline}\nStrategy: ${profile.language}\n\n02  Configured outputs\n${profile.templates.map(t => `• ${t.name}`).join('\n')}\n\n03  Review checklist\nConfirm adaptation matches the approved TDD, approved package interfaces, logging and file output contracts.\n\n04  Prototype limitation\nFiles contain illustrative stubs. No executable implementation has been generated; no ERP connection is made.`,
  ];
  stage.current = { version, status: 'review', createdAt: new Date().toISOString(), content: intro + sections[index] + (feedback ? `\n\nReviewer guidance incorporated in this mock revision\n${feedback}` : ''), feedback, sources, files: index === 3 ? profile.templates.map(t => {
    const values = { package: 'hr_invoice_extract', erp: profile.name, project: project.name, revision: version };
    return { name: fill(t.name, values), content: fill(t.content, values) };
  }) : [] };
  event(project, `${STAGES[index].short} generated for review (simulated)`, index, version);
  return stage.current;
}
export function approve(project, index) {
  if (!isUnlocked(project, index)) throw new Error('Approve the preceding stage first.');
  const current = project.stages[index].current;
  if (current?.status !== 'review') throw new Error('Only the current review revision can be approved.');
  if (index === 4 && (project.tests.length !== 3 || project.tests.some(t => t.result !== 'pass'))) throw new Error('All three demo checks must pass before tester sign-off.');
  current.status = 'approved';
  current.approvedAt = new Date().toISOString();
  event(project, `${STAGES[index].name} v${current.version} approved by demo reviewer`, index, current.version);
}
export function requestChanges(project, index, feedback) {
  if (!feedback.trim()) throw new Error('Enter reviewer feedback.');
  if (!isUnlocked(project, index)) throw new Error('Approve the preceding stage first.');
  const current = project.stages[index].current;
  if (current?.status !== 'review') throw new Error('This revision is not awaiting review.');
  current.status = 'changes_requested';
  current.changeRequest = feedback.trim();
  event(project, `Changes requested: ${feedback.trim()}`, index, current.version);
}
export function recordTests(project, tests) {
  if (!packageEligible(project)) throw new Error('Approve the package before testing.');
  if (project.stages[4].current?.status === 'approved') throw new Error('Start a sandbox revision before recording another run.');
  if (tests.length !== 3 || tests.some(t => !['pass', 'fail'].includes(t.result))) throw new Error('Record a result for all three demo checks.');
  const stage = project.stages[4];
  if (stage.current) stage.history.unshift(structuredClone(stage.current));
  project.tests = structuredClone(tests);
  stage.current = { version: ++stage.serial, status: 'review', createdAt: new Date().toISOString(), content: 'SIMULATED sandbox evidence. No ERP connection or live test was performed.', tests: structuredClone(tests), sources: { packageVersion: project.stages[3].current.version } };
  event(project, 'Simulated sandbox results recorded', 4, stage.current.version);
}
export function publishRelease(project) {
  if (!isUnlocked(project, 5)) throw new Error('Obtain sandbox tester sign-off first.');
  if (project.stages[5].current) throw new Error('The current demo release is already published.');
  const version = ++project.stages[5].serial;
  const release = { version, at: new Date().toISOString(), files: structuredClone(project.stages[3].current.files), sources: structuredClone(project.stages[3].current.sources), approvals: project.stages.slice(0, 5).map((stage, index) => ({ stage: STAGES[index].name, version: stage.current.version, approvedAt: stage.current.approvedAt })), mock: true };
  project.releases.unshift(release);
  project.stages[5].current = { version, status: 'approved', createdAt: release.at, content: 'Approved mock release. Sample artifacts only.', releaseVersion: version };
  event(project, `Demo release v${version} published`, 5, version);
}
export function seed() {
  const profiles = structuredClone(initialProfiles);
  const fixtures = [
    ['AP invoice extraction', 0, 'fusion', 'Custom', 1, 'review'],
    ['Supplier master synchronization', 1, 'sap', 'Standard', 2, 'review'],
    ['Cash application outbound feed', 2, 'netsuite', 'Custom', 4, 'empty'],
    ['Receivables reconciliation', 3, 'dynamics', 'Standard', 6, 'complete'],
    ['Open invoice delta export', 4, 'fusion', 'Custom', 2, 'changes'],
    ['Vendor payment status feed', 0, 'sap', 'Custom', 0, 'empty'],
    ['Daily journal integration', 2, 'dynamics', 'Standard', 4, 'empty'],
    ['ERP onboarding proof of concept', 1, 'demo', 'Custom', 0, 'empty'],
  ];
  const today = new Date();
  const projects = fixtures.map(([name, client, id, type, stop, state], n) => {
    const due = new Date(today); due.setDate(due.getDate() + (n === 4 ? -2 : 4 + n * 2));
    const p = createProject({ name, client: CLIENTS[client].name, profile: profiles.find(profile => profile.id === id), type, due: `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, '0')}-${String(due.getDate()).padStart(2, '0')}` });
    p.id = `demo-${1001 + n}`;
    if (stop || state === 'complete') {
      p.brief = SAMPLE_BRIEF;
      p.files = [{ name: 'Consulting_requirement_brief.txt', size: SAMPLE_BRIEF.length, sample: true }];
    }
    for (let i = 0; i < Math.min(stop, 4); i++) { generate(p, i); approve(p, i); }
    if (state === 'review' || state === 'changes') generate(p, stop);
    if (state === 'changes') requestChanges(p, stop, 'Add explicit behavior for duplicate invoice delivery and partial failures.');
    if (state === 'complete') { recordTests(p, ['Installation contract', 'Output reconciliation', 'Retry and recovery'].map(name => ({ name, result: 'pass' }))); approve(p, 4); publishRelease(p); }
    p.updatedAt = new Date(today.getTime() - n * 38 * 60 * 1000).toISOString();
    return p;
  });
  return { version: 1, profiles, projects };
}

// ZIP's STORE format needs no dependency: small text-only demo packages, no compression.
export function zipFiles(files) {
  const encoder = new TextEncoder(), parts = [], directory = [];
  let offset = 0;
  const crc32 = bytes => {
    let crc = -1;
    for (const byte of bytes) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
    return (crc ^ -1) >>> 0;
  };
  for (const file of files) {
    const name = encoder.encode(file.name), body = encoder.encode(file.content), crc = crc32(body);
    const local = new Uint8Array(30 + name.length), view = new DataView(local.buffer);
    view.setUint32(0, 0x04034b50, true); view.setUint16(4, 20, true); view.setUint16(6, 0x800, true); view.setUint16(12, 33, true);
    view.setUint32(14, crc, true); view.setUint32(18, body.length, true); view.setUint32(22, body.length, true); view.setUint16(26, name.length, true); local.set(name, 30);
    const central = new Uint8Array(46 + name.length), cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0x800, true); cv.setUint16(14, 33, true);
    cv.setUint32(16, crc, true); cv.setUint32(20, body.length, true); cv.setUint32(24, body.length, true); cv.setUint16(28, name.length, true); cv.setUint32(42, offset, true); central.set(name, 46);
    parts.push(local, body); directory.push(central); offset += local.length + body.length;
  }
  const size = directory.reduce((total, item) => total + item.length, 0);
  const end = new Uint8Array(22), ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true); ev.setUint32(12, size, true); ev.setUint32(16, offset, true);
  const bytes = new Uint8Array(offset + size + end.length);
  let cursor = 0;
  for (const part of [...parts, ...directory, end]) { bytes.set(part, cursor); cursor += part.length; }
  return bytes;
}
