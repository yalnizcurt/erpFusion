import type { Page } from '@playwright/test';
import { adminIdentity, fixtureClients, fixtureProfiles, onboardingResponse } from '../tests/fixtures';

const stages = [
  { stage: 'CONTEXT_ANALYSIS', label: 'Requirements analysis', depends_on: [], review_role: 'FUNCTIONAL_REVIEWER' },
  { stage: 'FDD', label: 'Functional design', depends_on: ['CONTEXT_ANALYSIS'], review_role: 'FUNCTIONAL_REVIEWER' },
  { stage: 'TDD', label: 'Technical design', depends_on: ['FDD'], review_role: 'TECHNICAL_REVIEWER' },
  { stage: 'SQL', label: 'Implementation package', depends_on: ['TDD'], review_role: 'TECHNICAL_REVIEWER' },
];

const artifactList = stages.map(({ stage }, index) => ({
  id: `artifact-${stage}`, project_id: 'fixture-project', artifact_type: stage,
  gate_status: index === 0 ? 'PENDING_REVIEW' : 'LOCKED', current_version: index === 0 ? 1 : 0,
}));

const version = {
  id: 'fixture-version', version_number: 1, state: 'PENDING_HUMAN_REVIEW',
  generated_at: '2026-10-01T10:00:00Z',
  content: { fixture_marker: 'viewport-regression', long_value: 'x'.repeat(16000),
    rows: Array.from({ length: 120 }, (_, index) => ({ index, description: 'Synthetic row '.repeat(20) })) },
};

function projectResponse(id: string, changes: Record<string, unknown> = {}) {
  return {
    id, name: id === 'fixture-project' ? 'Demo supplier integration' : 'Supplier invoice reconciliation',
    description: 'Synthetic fixture project', business_requirement: 'Map supplier records', erp_schema_context: { tables: [] },
    fdd_template_path: null, tdd_template_path: null, erp_profile_id: 'profile-0', erp_profile_version_id: 'profile-version-0',
    client_id: 'client-a', client_name: 'Alpha Industries', erp_installation_id: 'installation-0', erp_environment_id: 'environment-0',
    created_by_subject_id: 'fixture-admin', project_type: 'CUSTOM', due_date: null, last_activity_at: '2026-10-01T10:00:00Z',
    requirement_version: 1, schema_context_version: 1, workflow_revision: 1, workflow_status: 'PENDING_REVIEW',
    erp_name: 'ERP 0', erp_version: 3, current_stage: 'CONTEXT_ANALYSIS', package_available: false,
    status: 'ACTIVE', created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', ...changes,
  };
}

/** Fully synthetic local responses. Unknown routes fail rather than reach customer APIs. */
export async function installEngineeringFixture(page: Page, identity = adminIdentity): Promise<void> {
  await page.route('**/*', async (route) => {
    const origin = new URL(route.request().url()).origin;
    if (origin !== 'http://127.0.0.1:4173') {
      await route.abort('blockedbyclient');
      return;
    }
    await route.fallback();
  });
  await page.route('**/api/**', async (route) => {
    const { pathname: path } = new URL(route.request().url());
    const method = route.request().method();
    if (path === '/api/identity/me') return route.fulfill({ json: identity });
    if (path === '/api/clients') return route.fulfill({ json: fixtureClients });
    if (path === '/api/erp-profiles') return route.fulfill({ json: fixtureProfiles });
    if (path === '/api/integration-patterns') return route.fulfill({ json: [] });
    if (path === '/api/clients/client-a/installations' || path === '/api/clients/client-b/installations') {
      return route.fulfill({ json: onboardingResponse(path) });
    }
    if (path.endsWith('/environments')) return route.fulfill({ json: onboardingResponse(path) });
    if (path.includes('/memberships')) return route.fulfill({ json: [] });
    if (path === '/api/projects' && method === 'GET') {
      return route.fulfill({ json: {
        projects: [projectResponse('fixture-project')], total: 1, next_offset: null,
        summary: { awaiting_review: 1, ready_for_sandbox: 0, completed: 0 },
      } });
    }
    if (path === '/api/projects' && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({ status: 201, json: projectResponse('new-project', body) });
    }
    const projectMatch = path.match(/^\/api\/projects\/([^/]+)(?:\/(.*))?$/);
    if (projectMatch?.[1]) {
      const projectId = projectMatch[1];
      const suffix = projectMatch[2] || '';
      if (!suffix) return route.fulfill({ json: projectResponse(projectId) });
      if (suffix === 'workflow') return route.fulfill({ json: {
        project_id: projectId, project_name: 'Demo supplier integration', current_stage: 'CONTEXT_ANALYSIS',
        stages: stages.map((item, index) => ({ ...item, gate_status: index === 0 ? 'PENDING_REVIEW' : 'LOCKED',
          current_version: index === 0 ? 1 : 0, artifact_id: `artifact-${item.stage}`, can_generate: false })),
      } });
      if (suffix === 'artifacts') return route.fulfill({ json: artifactList });
      if (suffix === 'generation-jobs') return route.fulfill({ json: [] });
      if (suffix === 'package') return route.fulfill({ json: {
        available: false, kind: 'candidate', blockers: ['approval_required:CONTEXT_ANALYSIS'], files: [], manifest: {},
        candidate_id: null, candidate_checksum: null, release_id: null,
      } });
      if (suffix === 'input-revisions' || suffix === 'requirements') return route.fulfill({ json: [] });
    }
    const artifactMatch = path.match(/^\/api\/artifacts\/([^/]+)\/versions(?:\/(\d+)(\/validations)?)?$/);
    if (artifactMatch) {
      const [, artifactId, revision, tail] = artifactMatch;
      if (tail) return route.fulfill({ json: [] });
      if (revision) return route.fulfill({ json: version });
      return route.fulfill({ json: artifactId === 'artifact-CONTEXT_ANALYSIS' ? [version] : [] });
    }
    if (path.startsWith('/api/clients/')) return route.fulfill({ status: 501, json: { detail: `Unconfigured fixture route: ${path}` } });
    return route.fulfill({ status: 501, json: { detail: `Unconfigured fixture route: ${path}` } });
  });
}
