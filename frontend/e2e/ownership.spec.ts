import { expect, test } from '@playwright/test';
import { adminIdentity } from '../tests/fixtures';
import { installEngineeringFixture } from './fixtures';

test('Create New selects a matching client, installation, environment and pinned profile', async ({ page }) => {
  await installEngineeringFixture(page);
  let submitted: Record<string, unknown> | null = null;
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 201, json: { ...submitted, id: 'new-project' } });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Integration projects' })).toBeVisible();
  await page.getByRole('button', { name: 'Create New', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Client *', { exact: true })).toHaveValue('');
  await expect(dialog.getByRole('button', { name: 'Create Project' })).toBeDisabled();
  await dialog.getByLabel('Client *', { exact: true }).selectOption('client-a');
  await dialog.getByLabel('ERP installation *', { exact: true }).selectOption('installation-0');
  await expect(dialog.getByLabel('ERP installation *')).not.toContainText('Beta Industries');
  await dialog.getByLabel('Execution environment *', { exact: true }).selectOption('environment-0');
  await dialog.getByLabel('ERP profile version *', { exact: true }).selectOption('profile-version-0');
  await dialog.getByLabel('Project Name *', { exact: true }).fill('Supplier invoice reconciliation');
  await dialog.getByLabel('Integration type', { exact: true }).selectOption('STANDARD');
  await dialog.getByLabel('Due date', { exact: true }).fill('2026-10-15');
  await dialog.getByRole('button', { name: 'Create Project' }).click();
  await expect(dialog).not.toBeVisible();
  expect(submitted).toMatchObject({ client_id: 'client-a', erp_installation_id: 'installation-0',
    erp_environment_id: 'environment-0', erp_profile_version_id: 'profile-version-0',
    project_type: 'STANDARD', due_date: '2026-10-15' });
  await expect(page).toHaveURL(/\/projects\/new-project\/studio$/);
});

test('identity failure blocks private data loads and administration controls', async ({ page }) => {
  await installEngineeringFixture(page);
  const privateRequests: string[] = [];
  page.on('request', (request) => { if (/\/api\/(projects|clients|erp-profiles)/.test(request.url())) privateRequests.push(request.url()); });
  await page.route('**/api/identity/me', (route) => route.fulfill({ status: 401, json: { detail: 'Authentication required' } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sign-in required' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'ERP Profiles', exact: true })).toHaveCount(0);
  expect(privateRequests).toEqual([]);
});

test('consultant cannot review a pending functional gate from a deep Studio link', async ({ page }) => {
  await installEngineeringFixture(page, {
    ...adminIdentity,
    user_id: 'fixture-consultant',
    platform_roles: [],
    capabilities: { manage_clients: false, configure_erp: false, publish_erp: false },
    clients: [{ id: 'client-a', display_name: 'Alpha Industries', roles: ['CONSULTANT'], permissions: {
      manage_environment: false, create_request: true, review_functional: false, review_technical: false, test: false,
    } }],
  });
  const writes: string[] = [];
  page.on('request', (request) => { if (request.method() !== 'GET' && request.url().includes('/api/')) writes.push(`${request.method()} ${request.url()}`); });
  await page.goto('/projects/fixture-project/studio?tab=workspace&stage=CONTEXT_ANALYSIS');
  await expect(page.getByRole('combobox', { name: 'Configured engineering stage' })).toHaveValue('CONTEXT_ANALYSIS');
  await expect(page.getByRole('button', { name: 'Generate Requirements analysis' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Request Changes', exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test('administrator onboards a client, ERP installation, sandbox and client role through the UI', async ({ page }) => {
  await installEngineeringFixture(page);
  const client = { id: 'new-client', client_key: 'delta', display_name: 'Delta Industries', status: 'ACTIVE' };
  const installation = { id: 'new-installation', client_id: client.id, erp_profile_id: 'profile-0',
    installation_key: 'finance', display_name: 'Delta finance', status: 'ACTIVE' };
  const environment = { id: 'new-environment', client_id: client.id, installation_id: installation.id,
    display_name: 'Delta sandbox', environment_type: 'SANDBOX', status: 'ACTIVE' };
  const membership = { id: 'new-membership', client_id: client.id, subject_id: 'fixture-principal-id', role: 'CONSULTANT', status: 'ACTIVE' };
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const createResponses: Record<string, unknown> = {
    '/api/clients': client,
    '/api/clients/new-client/installations': installation,
    '/api/clients/new-client/installations/new-installation/environments': environment,
    '/api/clients/new-client/memberships': membership,
  };
  await page.route('**/api/clients**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (method === 'POST' && Object.hasOwn(createResponses, path)) {
      writes.push({ path, body: route.request().postDataJSON() as Record<string, unknown> });
      await route.fulfill({ status: 201, json: createResponses[path] }); return;
    }
    if (method === 'GET' && Object.hasOwn(createResponses, path)) {
      const created = writes.some((write) => write.path === path);
      await route.fulfill({ json: created ? [createResponses[path]] : [] }); return;
    }
    await route.fallback();
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Clients', exact: true }).click();
  await page.getByRole('button', { name: 'Add client', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('Client key', { exact: true }).fill('delta');
  await dialog.getByLabel('Display name', { exact: true }).fill('Delta Industries');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'Delta Industries', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Add installation', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('ERP profile', { exact: true }).selectOption('profile-0');
  await dialog.getByLabel('Installation key', { exact: true }).fill('finance');
  await dialog.getByLabel('Display name', { exact: true }).fill('Delta finance');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Add environment', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('Environment key', { exact: true }).fill('sandbox');
  await dialog.getByLabel('Display name', { exact: true }).fill('Delta sandbox');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByText('Delta sandbox', { exact: true })).toBeVisible();
  await page.getByLabel('Identity provider subject', { exact: true }).fill('fixture-consultant');
  await page.getByRole('button', { name: 'Assign role', exact: true }).click();
  await expect(page.getByText('Client role assigned.', { exact: true })).toBeVisible();
  await expect(page.getByText('Principal ID: fixture-principal-id', { exact: true })).toBeVisible();
  expect(writes.map((write) => write.path)).toEqual(Object.keys(createResponses));
  expect(writes[1]?.body).toMatchObject({ erp_profile_id: 'profile-0', installation_key: 'finance' });
  expect(writes[2]?.body).toMatchObject({ environment_key: 'sandbox', environment_type: 'SANDBOX' });
  expect(writes[3]?.body).toEqual({ subject_id: 'fixture-consultant', role: 'CONSULTANT' });
});
