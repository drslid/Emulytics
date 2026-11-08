export type PersonalAPIKey = {
  id: string; name: string; token_prefix: string; scopes: string[];
  created_at: string; expires_at: string; last_used_at: string | null; revoked_at: string | null;
};
export type PersonalAPIKeys = { items: PersonalAPIKey[]; total: number; limit: number; offset: number; available_scopes: string[] };
export function initialKeyScopes(permissions: string[]): string[] {
  return ['devices.read', 'workflows.read', 'runs.read'].filter((scope) => permissions.includes(scope));
}
export function keyActive(key: PersonalAPIKey, now = Date.now()): boolean {
  return key.revoked_at === null && Date.parse(key.expires_at) > now;
}
export function selectedKeyScopes(purpose: 'read' | 'run' | 'publish', permissions: string[]): string[] {
  const scopes = initialKeyScopes(permissions);
  if (purpose !== 'read') scopes.push(...['runs.execute', 'runs.cancel'].filter((scope) => permissions.includes(scope)));
  if (purpose === 'publish' && permissions.includes('workflows.publish')) scopes.push('workflows.publish');
  return scopes;
}
