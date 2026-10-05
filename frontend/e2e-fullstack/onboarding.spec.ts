import { createHash, randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

// No API interception: every mutation below is a browser action against FastAPI.
async function clickJSON(page: Page, path: string, method: string, click: () => Promise<unknown>) {
  const response = page.waitForResponse((item) => new URL(item.url()).pathname === path && item.request().method() === method);
  await click();
  const result = await response;
  expect(result.ok(), await result.text()).toBeTruthy();
  return result.json();
}

test('Admin UI onboarding feeds the real compiler and worker and preserves project version pins', async ({ page, request }, testInfo) => {
  await page.route('**/*', (route) => ['http://127.0.0.1:4183', 'http://127.0.0.1:8183'].includes(new URL(route.request().url()).origin) ? route.continue() : route.abort());
  const suffix = randomUUID().slice(0, 8);
  const erpName = `Demo ERP ${suffix}`;
  const promptName = 'Supplier context policy';
  const promptText = 'ACCEPTANCE_PROMPT_V1: apply approved supplier_code mapping to the nightly supplier feed.';
  const knowledgeText = 'ACCEPTANCE_KNOWLEDGE: supplier_code identifies each supplier; supplier_name is the verified legal name.';
  const packageText = 'ACCEPTANCE_PACKAGE: nightly supplier feed exports supplier_code and supplier_name to an outbound sink.';
  const requirement = 'Map supplier records into a nightly supplier feed using supplier_code and supplier_name.';
  const schema = { entities: [{ name: 'SUPPLIER_RECORD', fields: ['supplier_code', 'supplier_name'] }] };
  const configuration = {
    workflow: { stages: [{ type: 'CONTEXT_ANALYSIS', label: 'Context', depends_on: [], adapter: 'generic_json', prompt_stage: 'CONTEXT_ANALYSIS', task: 'Analyze the nightly supplier feed using approved source assets.' }] },
    generation: { strategy: 'configured_adapters' },
    validation: { schema_conformity: false, rules: [{ name: 'context output contract', type: 'required_keys', keys: ['artifact_type', 'erp_name', 'implementation_guidance'] }] },
  };
  const getJSON = async (path: string) => {
    const response = await request.get(`http://127.0.0.1:8183${path}`);
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  };

  await page.goto('/erp-profiles');
  await page.getByRole('button', { name: 'Add ERP', exact: true }).click();
  const createForm = page.locator('form').first();
  await createForm.locator('input').nth(0).fill(erpName);
  await createForm.locator('input').nth(1).fill('Acceptance Fixture Systems');
  await createForm.locator('input').nth(2).fill('2026-fixture');
  await createForm.locator('textarea').fill('CONTEXT_ANALYSIS');
  const profile = await clickJSON(page, '/api/erp-profiles', 'POST', () => page.getByRole('button', { name: 'Create draft profile' }).click());
  const profilePath = `/api/erp-profiles/${profile.id}`;
  await expect(page.getByRole('heading', { name: erpName, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Validation Rules', exact: true }).click();
  await expect(page.locator('section textarea')).toHaveValue(/"workflow"/);
  await page.locator('section textarea').fill(JSON.stringify(configuration, null, 2));
  await clickJSON(page, `${profilePath}/versions/1`, 'PUT', () => page.getByRole('button', { name: 'Save validation configuration' }).click());

  await page.getByRole('button', { name: 'Prompts', exact: true }).click();
  await page.getByPlaceholder('Prompt name', { exact: true }).fill(promptName);
  await page.getByPlaceholder('Write the governed system instructions for this scope and stage.').fill(promptText);
  const prompt = await clickJSON(page, `${profilePath}/versions/1/prompts`, 'POST', () => page.getByRole('button', { name: 'Add prompt version' }).click());
  await clickJSON(page, `${profilePath}/prompts/${prompt.id}/publish`, 'POST', () => page.locator('article').filter({ hasText: promptName }).getByRole('button', { name: 'Publish', exact: true }).click());

  const assets = [];
  for (const [tab, placeholder, name, content] of [
    ['Knowledge', 'Knowledge asset name', 'Supplier mapping guide', knowledgeText],
    ['Standard Packages', 'Package name', 'Nightly supplier template', packageText],
  ]) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    await page.getByPlaceholder(placeholder, { exact: true }).fill(name!);
    await page.getByPlaceholder('Purpose / description').fill('nightly supplier feed mapping');
    await page.getByPlaceholder('Paste approved text/code or add a short reference excerpt').fill(content!);
    const asset = await clickJSON(page, `${profilePath}/versions/1/assets`, 'POST', () => page.getByRole('button', { name: 'Add text asset' }).click());
    assets.push(asset);
    expect(asset.checksum).toBe(createHash('sha256').update(content!).digest('hex'));
    await clickJSON(page, `${profilePath}/assets/${asset.asset_id}/versions/1/publish`, 'POST', () => page.locator('article').filter({ hasText: name }).getByRole('button', { name: 'Publish', exact: true }).click());
  }
  await clickJSON(page, `${profilePath}/versions/1/publish`, 'POST', () => page.getByRole('button', { name: 'Publish version', exact: true }).click());
  await expect(page.getByText('This version is immutable.', { exact: false })).toBeVisible();

  await page.getByRole('button', { name: 'Clients', exact: true }).click();
  await page.getByRole('button', { name: 'Add client', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Client key', { exact: true }).fill(`acceptance-${suffix}`);
  await dialog.getByLabel('Display name', { exact: true }).fill(`Acceptance client ${suffix}`);
  const client = await clickJSON(page, '/api/clients', 'POST', () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Add installation', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('ERP profile', { exact: true }).selectOption(profile.id);
  await dialog.getByLabel('Installation key', { exact: true }).fill('supplier');
  await dialog.getByLabel('Display name', { exact: true }).fill('Fixture supplier installation');
  const installation = await clickJSON(page, `/api/clients/${client.id}/installations`, 'POST', () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Add environment', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Environment key', { exact: true }).fill('sandbox');
  await dialog.getByLabel('Display name', { exact: true }).fill('Fixture offline sandbox');
  const environment = await clickJSON(page, `/api/clients/${client.id}/installations/${installation.id}/environments`, 'POST', () => dialog.getByRole('button', { name: 'Save', exact: true }).click());
  await expect(dialog).not.toBeVisible();

  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await page.getByRole('button', { name: 'Create New', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Client *', { exact: true }).selectOption(client.id);
  await dialog.getByLabel('ERP installation *', { exact: true }).selectOption(installation.id);
  await dialog.getByLabel('Execution environment *', { exact: true }).selectOption(environment.id);
  await dialog.getByLabel('ERP profile version *', { exact: true }).selectOption(profile.profile_version_id);
  await dialog.getByLabel('Project Name *', { exact: true }).fill('Nightly supplier context acceptance');
  const project = await clickJSON(page, '/api/projects', 'POST', () => dialog.getByRole('button', { name: 'Create Project', exact: true }).click());
  const projectPath = `/api/projects/${project.id}`;
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/studio$`));
  await page.getByLabel('Upload requirement documents').setInputFiles({ name: 'supplier-requirement.txt', mimeType: 'text/plain', buffer: Buffer.from(requirement) });
  await expect(page.getByRole('button', { name: /^supplier-requirement.txt/ })).toBeVisible();
  await expect(page.locator('#requirement-text')).toHaveValue(new RegExp('Map supplier records'));
  await page.locator('#requirement-text').fill(`${requirement}\nACCEPTANCE_REVIEWED_REQUIREMENT: preserve the original supplier identifier.`);
  await page.getByText('ERP schema and context', { exact: true }).click();
  await page.getByLabel('ERP context (JSON)', { exact: true }).fill(JSON.stringify(schema, null, 2));
  await clickJSON(page, projectPath, 'PATCH', () => page.getByRole('button', { name: 'Save requirement revision' }).click());
  await expect(page.getByRole('button', { name: 'Analyze requirements', exact: true })).toBeEnabled();
  const savedProject = await getJSON(projectPath);
  const generate = async () => {
    const run = await clickJSON(page, `${projectPath}/generate`, 'POST', () => page.getByRole('button', { name: 'Generate Context', exact: true }).click());
    expect(run.status).toBe('QUEUED');
    await expect.poll(async () => (await getJSON(`${projectPath}/generation-jobs/${run.id}`)).status, { timeout: 30_000 }).toBe('COMPLETED');
    const artifact = (await getJSON(`${projectPath}/artifacts`)).find((item: { artifact_type: string }) => item.artifact_type === 'CONTEXT_ANALYSIS');
    const versions = await getJSON(`/api/artifacts/${artifact.id}/versions`);
    const validations = await getJSON(`/api/artifacts/${artifact.id}/versions/${versions[0].version_number}/validations`);
    expect(validations.length).toBeGreaterThan(0);
    expect(validations.every((item: { status: string }) => item.status === 'PASS')).toBeTruthy();
    return { run, artifact, versions, validations };
  };
  await page.getByRole('button', { name: 'Workspace', exact: true }).click();
  const first = await generate();
  const snapshot = first.versions[0].input_context_snapshot;
  expect(snapshot.erp_profile).toEqual({ id: profile.id, version_id: profile.profile_version_id, version: 1 });
  expect(snapshot.prompt_versions).toEqual([{ id: prompt.id, scope: 'STAGE', name: promptName, stage: 'CONTEXT_ANALYSIS', version: 1, content: promptText }]);
  for (const [index, key] of ['knowledge_asset_versions', 'standard_package_versions'].entries()) {
    const asset = assets[index];
    expect(snapshot[key]).toEqual([{ id: asset.id, asset_id: asset.asset_id, kind: asset.asset_kind, name: asset.name, version: 1, checksum: asset.checksum }]);
  }
  expect(snapshot.requirement_version).toBe(savedProject.requirement_version);
  expect(snapshot.schema_context_version).toBe(savedProject.schema_context_version);
  expect(snapshot.schema_context).toEqual(schema);
  expect(first.versions[0].content).toMatchObject({ artifact_type: 'CONTEXT_ANALYSIS', erp_name: erpName, source_entities: schema.entities, knowledge_references: ['Supplier mapping guide'], standard_packages_considered: ['Nightly supplier template'] });
  for (const text of [promptText, knowledgeText, packageText]) expect(first.versions[0].content.implementation_guidance).toContain(text);
  expect(first.versions[0].generation_run_id).toBe(first.run.id);
  await expect(page.getByRole('button', { name: 'Approve Gate', exact: true })).toBeVisible();
  await page.getByText('Why was this generated this way?', { exact: true }).click();
  const shownProvenance = page.locator('.provenance-json');
  for (const id of [profile.profile_version_id, prompt.id, ...assets.map((item) => item.id)]) await expect(shownProvenance).toContainText(id);

  // Reviewer corrections stay scoped to this request and its selected ERP.
  await page.getByRole('button', { name: 'Request Changes', exact: true }).click();
  await page.getByLabel('Review feedback').fill('ACCEPTANCE_FEEDBACK: preserve supplier_code in the nightly supplier feed.');
  await clickJSON(page, `/api/reviews/artifacts/${first.artifact.id}/versions/1/review`, 'POST',
    () => page.getByRole('button', { name: 'Submit Change Request' }).click());
  const feedback = await getJSON(`${projectPath}/feedback`);
  expect(feedback).toHaveLength(1);
  expect(feedback[0]).toMatchObject({ scope: 'PROJECT', project_id: project.id, stage: 'CONTEXT_ANALYSIS', status: 'APPROVED' });
  const reviewedFirst = (await getJSON(`/api/artifacts/${first.artifact.id}/versions`))[0];
  expect(reviewedFirst.state).toBe('REQUEST_CHANGES');

  // Clone and publish through Admin UI; the existing project's pin stays on v1.
  await page.getByRole('button', { name: 'ERP Profiles', exact: true }).click();
  await page.getByRole('button', { name: new RegExp(erpName) }).click();
  const secondProfileVersion = await clickJSON(page, `${profilePath}/versions`, 'POST', () => page.getByRole('button', { name: 'New version', exact: true }).click());
  expect(secondProfileVersion.version).toBe(2);
  await page.getByRole('button', { name: 'Prompts', exact: true }).click();
  await page.getByPlaceholder('Prompt name', { exact: true }).fill(promptName);
  await page.getByPlaceholder('Write the governed system instructions for this scope and stage.').fill('ACCEPTANCE_PROMPT_V2: use canonical_supplier_id for the nightly supplier feed.');
  const secondPrompt = await clickJSON(page, `${profilePath}/versions/2/prompts`, 'POST', () => page.getByRole('button', { name: 'Add prompt version' }).click());
  await clickJSON(page, `${profilePath}/prompts/${secondPrompt.id}/publish`, 'POST', () => page.locator('article').filter({ hasText: 'ACCEPTANCE_PROMPT_V2' }).getByRole('button', { name: 'Publish', exact: true }).click());
  await clickJSON(page, `${profilePath}/versions/2/publish`, 'POST', () => page.getByRole('button', { name: 'Publish version', exact: true }).click());
  expect((await getJSON(projectPath)).erp_profile_version_id).toBe(profile.profile_version_id);
  await page.goto(`/projects/${project.id}/studio?tab=workspace&stage=CONTEXT_ANALYSIS`);
  const regenerated = await generate();
  expect(regenerated.versions).toHaveLength(2);
  expect(regenerated.versions[0].input_context_snapshot.prompt_versions).toEqual(snapshot.prompt_versions);
  expect(regenerated.versions[0].input_context_snapshot.erp_profile).toEqual(snapshot.erp_profile);
  expect(regenerated.versions[0].content.implementation_guidance).toContain('ACCEPTANCE_PROMPT_V1');
  expect(regenerated.versions[0].content.implementation_guidance).not.toContain('ACCEPTANCE_PROMPT_V2');
  expect(regenerated.versions[0].input_context_snapshot.feedback_versions).toEqual([{ id: feedback[0].id, scope: 'PROJECT', version: 1 }]);
  expect(regenerated.versions[0].content.implementation_guidance).toContain('ACCEPTANCE_FEEDBACK');
  expect(regenerated.versions[1]).toEqual(reviewedFirst);

  // The user explicitly chooses the new version; old generation sources remain frozen.
  await page.getByRole('button', { name: 'Requirements', exact: true }).click();
  await page.getByRole('button', { name: 'Use ERP profile v2', exact: true }).click();
  await clickJSON(page, projectPath, 'PATCH', () => page.getByRole('button', { name: 'Confirm profile upgrade' }).click());
  await expect(page.getByRole('dialog', { name: 'Upgrade ERP profile' })).not.toBeVisible();
  expect((await getJSON(projectPath)).erp_profile_version_id).toBe(secondProfileVersion.id);
  await page.getByRole('button', { name: 'Workspace', exact: true }).click();
  const upgraded = await generate();
  expect(upgraded.versions).toHaveLength(3);
  expect(upgraded.versions[0].input_context_snapshot.erp_profile).toMatchObject({ version_id: secondProfileVersion.id, version: 2 });
  expect(upgraded.versions[0].input_context_snapshot.prompt_versions[0]).toMatchObject({ id: secondPrompt.id, version: 2 });
  expect(upgraded.versions[0].content.implementation_guidance).toContain('ACCEPTANCE_PROMPT_V2');
  expect(upgraded.versions[0].content.implementation_guidance).not.toContain('ACCEPTANCE_PROMPT_V1');
  expect(upgraded.versions[1]).toEqual(regenerated.versions[0]);
  expect(upgraded.versions[2]).toEqual(reviewedFirst);
  const audit = await getJSON(`${profilePath}/versions/1/audit`);
  expect(audit.map((item: { action: string }) => item.action)).toEqual(expect.arrayContaining(['PROFILE_CREATED', 'PROMPT_PUBLISHED', 'KNOWLEDGE_ASSET_CREATED', 'PACKAGE_ASSET_CREATED', 'PROFILE_VERSION_PUBLISHED']));
  await testInfo.attach('persisted-acceptance-evidence', { body: JSON.stringify({ fixture: 'offline development only', profile, secondProfileVersion, project: savedProject, first, regenerated, upgraded }, null, 2), contentType: 'application/json' });
});
