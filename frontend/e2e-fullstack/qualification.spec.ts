import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

async function clickJSON(page: Page, path: string, click: () => Promise<unknown>, method = 'POST') {
  const pending = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === method);
  await click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test('Admin-created Publisher pattern reaches a human-approved simulated release with exact baseline evidence', async ({ page, request }, testInfo) => {
  page.setDefaultTimeout(15_000);
  // No API mutation shortcuts, seeded profiles, external requests or live ERP/model calls.
  await page.route('**/*', (route) => ['http://127.0.0.1:4183', 'http://127.0.0.1:8183'].includes(new URL(route.request().url()).origin) ? route.continue() : route.abort());
  const fixture = JSON.parse(readFileSync(new URL('../../backend/app/cli/fixtures/oracle-publisher-harness-v1.json', import.meta.url), 'utf8')).profiles[0];
  const suffix = randomUUID().slice(0, 8);
  const name = `Oracle Fusion fixture ${suffix}`;
  const pattern = fixture.integration_patterns[0];
  const config = structuredClone(fixture.profile_version.configuration);
  config.workflow.stages.forEach((stage: { type: string; label: string; prompt_stage: string }) => {
    stage.label = stage.type;
    stage.prompt_stage = stage.type;
  });
  const getJSON = async (path: string) => {
    const response = await request.get(`http://127.0.0.1:8183${path}`);
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };

  await page.goto('/erp-profiles');
  await expect(page).toHaveTitle('HighStudio');
  expect(await page.locator('meta[name="author"]').getAttribute('content')).toBe('Srikara Krishna Vuyyuru');
  await expect(page.locator('body')).not.toContainText('Srikara Krishna Vuyyuru');
  await page.getByRole('button', { name: 'Add ERP', exact: true }).click();
  const form = page.locator('form').first();
  await form.locator('input').nth(0).fill(name);
  await form.locator('input').nth(1).fill('Oracle');
  await form.locator('input').nth(2).fill('synthetic-test');
  await form.locator('textarea').fill('CONTEXT_ANALYSIS\nFDD\nTDD\nPUBLISHER');
  const profile = await clickJSON(page, '/api/erp-profiles', () => page.getByRole('button', { name: 'Create draft profile' }).click());
  const profilePath = `/api/erp-profiles/${profile.id}`;
  await page.getByRole('button', { name: 'Validation Rules', exact: true }).click();
  await expect(page.locator('section textarea')).toHaveValue(/"workflow"/);
  await page.locator('section textarea').fill(JSON.stringify(config, null, 2));
  await clickJSON(page, `${profilePath}/versions/1`, () => page.getByRole('button', { name: 'Save validation configuration' }).click(), 'PUT');
  await page.getByRole('button', { name: 'Prompts', exact: true }).click();
  for (const [index, stage] of config.workflow.stages.entries()) {
    const promptName = `Fixture ${stage.type}`;
    await page.getByPlaceholder('Prompt name', { exact: true }).fill(promptName);
    await page.locator('form select').last().selectOption(stage.type);
    await page.getByPlaceholder('Write the governed system instructions for this scope and stage.').fill(fixture.profile_version.prompts[index].content);
    const prompt = await clickJSON(page, `${profilePath}/versions/1/prompts`, () => page.getByRole('button', { name: 'Add prompt version' }).click());
    await clickJSON(page, `${profilePath}/prompts/${prompt.id}/publish`, () => page.locator('article').filter({ hasText: promptName }).getByRole('button', { name: 'Publish', exact: true }).click());
  }
  await page.getByRole('button', { name: 'Standard Packages', exact: true }).click();
  await page.getByPlaceholder('Package name', { exact: true }).fill(pattern.baseline.name);
  await page.getByPlaceholder('Purpose / description').fill('Synthetic Publisher named-file baseline; no native qualification.');
  await page.getByPlaceholder('Paste approved text/code or add a short reference excerpt').fill(JSON.stringify(pattern.baseline.content));
  const baseline = await clickJSON(page, `${profilePath}/versions/1/assets`, () => page.getByRole('button', { name: 'Add text asset' }).click());
  await clickJSON(page, `${profilePath}/assets/${baseline.asset_id}/versions/1/publish`, () => page.locator('article').filter({ hasText: pattern.baseline.name }).getByRole('button', { name: 'Publish', exact: true }).click());
  await clickJSON(page, `${profilePath}/versions/1/publish`, () => page.getByRole('button', { name: 'Publish version', exact: true }).click());

  await page.getByRole('button', { name: 'Integration Patterns', exact: true }).click();
  await page.getByLabel('Pattern key', { exact: true }).fill('publisher-outbound');
  await page.getByLabel('Pattern name', { exact: true }).fill(pattern.name);
  await page.getByRole('combobox', { name: 'Pinned ERP intelligence version', exact: true }).selectOption(profile.profile_version_id);
  await page.getByRole('combobox', { name: 'Runtime model', exact: true }).selectOption('ERP_NATIVE');
  await page.getByLabel('Deliverable type', { exact: true }).fill(pattern.deliverable_type);
  await page.getByLabel('Delivery method', { exact: true }).fill(pattern.delivery_method);
  await expect(page.getByLabel('Approved baseline asset versions')).toContainText(pattern.baseline.name);
  await page.getByLabel('Approved baseline asset versions').selectOption([baseline.id]);
  await page.getByRole('textbox', { name: 'Pattern contract (generation rules, capabilities, test plan, assurance)', exact: true }).fill(JSON.stringify(pattern.configuration, null, 2));
  const patternCreation = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/integration-patterns' && r.request().method() === 'POST');
  const versionCreation = page.waitForResponse((r) => /\/api\/integration-patterns\/[^/]+\/versions$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save draft pattern version', exact: true }).click();
  const registeredPattern = await (await patternCreation).json();
  const versionResponse = await versionCreation;
  expect(versionResponse.ok(), await versionResponse.text()).toBeTruthy();
  const version = await versionResponse.json();
  await clickJSON(page, `/api/integration-patterns/${registeredPattern.id}/versions/${version.id}/publish`, () => page.locator('.pattern-studio article').getByRole('button', { name: 'Publish', exact: true }).click());

  await page.getByRole('button', { name: 'Clients', exact: true }).click();
  await page.getByRole('button', { name: 'Add client', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Client key', { exact: true }).fill(`publisher-${suffix}`);
  await dialog.getByLabel('Display name', { exact: true }).fill(`Publisher client ${suffix}`);
  const client = await clickJSON(page, '/api/clients', () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Add installation', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('ERP profile', { exact: true }).selectOption(profile.id);
  await dialog.getByLabel('Installation key', { exact: true }).fill('publisher');
  await dialog.getByLabel('Display name', { exact: true }).fill('Publisher synthetic installation');
  const installation = await clickJSON(page, `/api/clients/${client.id}/installations`, () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Add environment', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Environment key', { exact: true }).fill('company-test');
  await dialog.getByLabel('Display name', { exact: true }).fill('Synthetic company TEST');
  await dialog.getByLabel('Environment type', { exact: true }).selectOption('TEST');
  await dialog.getByLabel('Environment custody', { exact: true }).selectOption('CUSTOMER');
  await dialog.getByLabel('Execution mode', { exact: true }).selectOption('SIMULATED');
  const environment = await clickJSON(page, `/api/clients/${client.id}/installations/${installation.id}/environments`, () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();

  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await page.getByRole('button', { name: 'Create New', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Client *', { exact: true }).selectOption(client.id);
  await dialog.getByLabel('ERP installation *', { exact: true }).selectOption(installation.id);
  await dialog.getByLabel('Execution environment *', { exact: true }).selectOption(environment.id);
  await dialog.getByLabel('Integration pattern and version *', { exact: true }).selectOption(version.id);
  await dialog.getByLabel('Project Name *', { exact: true }).fill('Publisher qualification acceptance');
  const project = await clickJSON(page, '/api/projects', () => dialog.getByRole('button', { name: 'Create Project', exact: true }).click());
  expect(project.integration_pattern_version_id).toBe(version.id);
  const projectPath = `/api/projects/${project.id}`;
  await page.getByLabel('Upload requirement documents').setInputFiles({ name: 'publisher-requirement.txt', mimeType: 'text/plain', buffer: Buffer.from('Extract one synthetic invoice with invoice_id, amount and currency using the approved baseline; CSV totals equal 10.00 USD.') });
  await expect(page.getByRole('button', { name: /^publisher-requirement.txt/ })).toBeVisible();
  await expect(page.locator('#requirement-text')).toHaveValue(/Extract one synthetic invoice/);
  await page.getByRole('button', { name: 'Workspace', exact: true }).click();
  for (const stage of config.workflow.stages) {
    await page.getByLabel('Configured engineering stage', { exact: true }).selectOption(stage.type);
    const run = await clickJSON(page, `${projectPath}/generate`, () => page.getByRole('button', { name: `Generate ${stage.type}`, exact: true }).click());
    await expect.poll(async () => (await getJSON(`${projectPath}/generation-jobs/${run.id}`)).status, { timeout: 30_000 }).toBe('COMPLETED');
    const artifact = (await getJSON(`${projectPath}/artifacts`)).find((a: { artifact_type: string }) => a.artifact_type === stage.type);
    await page.getByRole('button', { name: 'Approve Gate', exact: true }).click();
    await clickJSON(page, `/api/reviews/artifacts/${artifact.id}/versions/1/review`, () => page.getByRole('dialog', { name: 'Approve artifact revision', exact: true }).getByRole('button', { name: 'Confirm approval', exact: true }).click());
  }

  await page.getByRole('button', { name: 'Sandbox', exact: true }).click();
  const candidate = await clickJSON(page, `${projectPath}/package/candidates`, () => page.getByRole('button', { name: 'Prepare exact candidate', exact: true }).click());
  const packageState = await getJSON(`${projectPath}/package`);
  expect(packageState.manifest.integration_pattern_version_id).toBe(version.id);
  expect(packageState.manifest.baseline_versions[0].id).toBe(baseline.id);
  await page.getByLabel(/I approve the implemented capabilities for this exact pattern/).check();
  await clickJSON(page, `${projectPath}/executions/qualifications`, () => page.getByRole('button', { name: 'Approve target capabilities', exact: true }).click());
  const attempt = await clickJSON(page, `${projectPath}/executions`, () => page.getByRole('button', { name: 'Request deliverable test', exact: true }).click());
  expect(attempt.status).toBe('AWAITING_APPROVAL');
  expect(attempt.integration_pattern_version_id).toBe(version.id);
  await page.getByText(/SIMULATED · AWAITING_APPROVAL/).click();
  await clickJSON(page, `${projectPath}/executions/${attempt.id}/approve`, () => page.getByRole('button', { name: 'Approve this exact test', exact: true }).click());
  await expect.poll(async () => (await getJSON(`${projectPath}/executions/${attempt.id}`)).status, { timeout: 30_000 }).toBe('COMPLETED');
  const completed = await getJSON(`${projectPath}/executions/${attempt.id}`);
  expect(completed.verdict).toBe('PASSED');
  expect(completed.assurance).not.toContain('REMOTE_ARTIFACT_IDENTITY_VERIFIED');
  const receipt = await getJSON(`${projectPath}/executions/${attempt.id}/evidence/receipt.json`);
  expect(receipt.candidate_checksum).toBe(candidate.checksum);
  expect(receipt.remote_exact_bytes_verified).toBe(false);
  await page.getByRole('button', { name: 'Refresh qualification', exact: true }).click();
  const summary = page.locator('.qualification-workspace > details > summary').filter({ hasText: 'SIMULATED · COMPLETED · PASSED' });
  await expect(summary).toBeVisible();
  if (!(await page.getByRole('button', { name: 'Sign off simulated evidence', exact: true }).isVisible())) await summary.click();
  const release = await clickJSON(page, `${projectPath}/executions/${attempt.id}/sign-off`, () => page.getByRole('button', { name: 'Sign off simulated evidence', exact: true }).click());
  expect(release.simulated).toBe(true);
  await page.getByRole('button', { name: 'Release', exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download immutable release ZIP', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/release.*\.zip$/);
  await testInfo.attach('simulated-pattern-evidence', { body: JSON.stringify({ qualification: 'SIMULATED_ONLY', version, baseline, candidate, completed, receipt, release }, null, 2), contentType: 'application/json' });
});
