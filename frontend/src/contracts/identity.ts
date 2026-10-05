export interface ClientPermissions {
  manage_environment: boolean;
  create_request: boolean;
  review_functional: boolean;
  review_technical: boolean;
  test: boolean;
}

export interface CurrentIdentity {
  user_id: string;
  provider: string;
  is_fixture: boolean;
  platform_roles: string[];
  capabilities: { manage_clients: boolean; configure_erp: boolean; publish_erp: boolean };
  clients: { id: string; display_name: string; roles: string[]; permissions: ClientPermissions }[];
}

export interface Client {
  id: string;
  client_key: string;
  display_name: string;
  status: string;
}

export type ClientRole = 'CLIENT_ADMIN' | 'CONSULTANT' | 'FUNCTIONAL_REVIEWER' | 'TECHNICAL_REVIEWER' | 'TESTER';

export interface ClientMembership {
  id: string;
  client_id: string;
  subject_id: string;
  role: ClientRole;
  status: string;
}

export interface ERPInstallation {
  id: string;
  client_id: string;
  erp_profile_id: string;
  installation_key: string;
  display_name: string;
  edition?: string | null;
  product_version?: string | null;
  status: string;
}

export interface ERPEnvironment {
  id: string;
  client_id: string;
  installation_id: string;
  display_name: string;
  environment_type: string;
  custody?: string;
  execution_mode?: string;
  endpoint_url?: string | null;
  status: string;
}

export interface PublishedERPProfile {
  id: string;
  profile_version_id: string;
  profile_version: number;
  name: string;
  display_name?: string;
  version_label?: string;
}

export interface IntegrationRequestCreate {
  integration_pattern_version_id?: string;
  project_type: 'STANDARD' | 'CUSTOM';
  due_date: string | null;
  name: string;
  description: string;
  business_requirement: string;
  erp_schema_context: Record<string, unknown>;
  erp_profile_version_id: string;
  client_id: string;
  erp_installation_id: string;
  erp_environment_id: string;
}

export function canManageEnvironment(identity: CurrentIdentity, clientId: string): boolean {
  return identity.capabilities.manage_clients
    || !!identity.clients.find((client) => client.id === clientId)?.permissions.manage_environment;
}

export function canCreateRequest(identity: CurrentIdentity, clientId: string): boolean {
  return identity.capabilities.manage_clients
    || !!identity.clients.find((client) => client.id === clientId)?.permissions.create_request;
}
