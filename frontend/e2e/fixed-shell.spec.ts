import { expect, test } from '@playwright/test';
import { installEngineeringFixture } from './fixtures';

test.beforeEach(async ({ page }) => installEngineeringFixture(page));

test('long Studio JSON preserves the fixed shell while the main content scrolls', async ({ page }) => {
  await page.goto('/projects/fixture-project/studio?tab=workspace&stage=CONTEXT_ANALYSIS');
  await expect(page.getByRole('heading', { name: 'Demo supplier integration' })).toBeVisible();
  await expect(page.getByLabel('Artifact revision')).toHaveValue('1');
  await page.getByRole('button', { name: 'JSON', exact: true }).click();
  const viewer = page.locator('pre.code-container');
  await expect(viewer).toContainText('viewport-regression');
  const header = page.locator('.app-header-bar');
  const sidebar = page.locator('.app-sidebar');
  const footer = page.locator('.app-footer-bar');
  const before = await Promise.all([header.boundingBox(), sidebar.boundingBox(), footer.boundingBox()]);

  const dimensions = await page.evaluate(() => ({
    width: window.innerWidth, height: window.innerHeight,
    documentWidth: document.documentElement.scrollWidth,
    documentHeight: document.documentElement.scrollHeight,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.width);
  expect(dimensions.documentHeight).toBeLessThanOrEqual(dimensions.height);
  await page.locator('.app-content-scroll').evaluate((element) => { element.scrollTop = element.scrollHeight; });
  // Native smooth scrolling starts on a later animation frame.
  await expect.poll(() => page.locator('.app-content-scroll').evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const after = await Promise.all([header.boundingBox(), sidebar.boundingBox(), footer.boundingBox()]);
  expect(after).toEqual(before);
  await expect(page.getByRole('button', { name: 'Home', exact: true })).toBeVisible();
  await expect(footer).toBeInViewport();
  await expect(header).toBeInViewport();
});

test('direct Studio links preserve configured stage order and show the active gate before locked downstream gates', async ({ page }) => {
  await page.goto('/projects/fixture-project/studio?tab=workspace&stage=FDD');
  const selector = page.getByRole('combobox', { name: 'Configured engineering stage' });
  await expect(selector).toHaveValue('FDD');
  await expect(selector.locator('option')).toHaveText([
    'Requirements analysis', 'Functional design', 'Technical design', 'Implementation package',
  ]);
  await expect(page.locator('.stage-strip').getByRole('button', { name: /Requirements.*Pending Review/i })).toBeVisible();
  await expect(page.locator('.stage-strip').getByRole('button', { name: /FDD.*Locked/i })).toBeVisible();
  await expect(page.getByText('This stage is waiting for upstream approval.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate Functional design' })).toBeDisabled();
});

test('Home search filter survives opening a project and returning from Studio', async ({ page }) => {
  await page.goto('/');
  const search = page.getByRole('textbox', { name: 'Search projects or clients' });
  await search.fill('Demo supplier');
  await expect(page.getByRole('button', { name: 'Open Studio for Demo supplier integration' })).toBeVisible();
  await page.getByRole('button', { name: 'Open Studio for Demo supplier integration' }).click();
  await expect(page).toHaveURL(/\/projects\/fixture-project\/studio$/);
  await page.getByRole('button', { name: 'All projects' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('textbox', { name: 'Search projects or clients' })).toHaveValue('Demo supplier');
  await expect(page.getByRole('button', { name: 'Open Studio for Demo supplier integration' })).toBeVisible();
});
