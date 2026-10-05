import type { CurrentIdentity, Client, ERPInstallation, ERPEnvironment, PublishedERPProfile } from '../src/contracts/identity';

export const adminIdentity: CurrentIdentity = {
  user_id: 'fixture-admin', provider: 'fixture', is_fixture: true, platform_roles: ['PLATFORM_ADMIN'],
  capabilities: { manage_clients: true, configure_erp: true, publish_erp: true }, clients: [],
};
export const fixtureClients: Client[] = [
  { id: 'client-a', client_key: 'alpha', display_name: 'Alpha Industries', status: 'ACTIVE' },
  { id: 'client-b', client_key: 'beta', display_name: 'Beta Industries', status: 'ACTIVE' },
];
export const fixtureInstallations: ERPInstallation[] = fixtureClients.map((client, index) => ({
  id: `installation-${index}`, client_id: client.id, erp_profile_id: `profile-${index}`,
  installation_key: `finance-${index}`, display_name: `${client.display_name} finance`, status: 'ACTIVE',
}));
export const fixtureEnvironments: ERPEnvironment[] = fixtureInstallations.map((installation, index) => ({
  id: `environment-${index}`, client_id: installation.client_id, installation_id: installation.id,
  display_name: `${installation.display_name} sandbox`, environment_type: 'SANDBOX', status: 'ACTIVE',
}));
export const fixtureProfiles: PublishedERPProfile[] = fixtureInstallations.map((installation, index) => ({
  id: installation.erp_profile_id, profile_version_id: `profile-version-${index}`, profile_version: 3,
  name: `ERP ${index}`, display_name: `ERP ${index}`,
}));

export function onboardingResponse(path: string): unknown {
  if (path === '/api/clients') return fixtureClients;
  if (path.endsWith('/installations')) return fixtureInstallations;
  if (path.endsWith('/environments')) return fixtureEnvironments;
  if (path.endsWith('/memberships')) return [];
  throw new Error(`Unexpected fixture path: ${path}`);
}
