export const CHATGPT_VERIFICATION_URL = "https://auth.openai.com/codex/device";
export const CHATGPT_HELP_URL = "https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta";
export type ChatgptStatus = "disconnected" | "starting" | "pending" | "connected" | "expired" | "error";
export type ChatgptConnection = {
  provider: "chatgpt"; available: boolean; status: ChatgptStatus;
  account: { email: string | null; plan_type: string | null } | null;
  login: { id: string; user_code: string; verification_url: string; expires_at: string } | null;
  connected_at: string | null; updated_at: string | null; poll_interval_seconds: number; error_code: string | null;
};

function record(value: unknown): Record<string, unknown> | null { return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; }
function text(value: unknown, max: number): value is string { return typeof value === "string" && value.length > 0 && value.length <= max; }
function nullableText(value: unknown, max: number): value is string | null { return value === null || text(value, max); }
function stamp(value: unknown): value is string | null { return value === null || typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value)); }

export function parseChatgptConnection(value: unknown): ChatgptConnection {
  const input = record(value);
  if (!input || input.provider !== "chatgpt" || typeof input.available !== "boolean" ||
      !["disconnected", "starting", "pending", "connected", "expired", "error"].includes(String(input.status)) ||
      !stamp(input.connected_at) || !stamp(input.updated_at) ||
      typeof input.poll_interval_seconds !== "number" || !Number.isFinite(input.poll_interval_seconds) || input.poll_interval_seconds < 1 ||
      !(input.error_code === null || typeof input.error_code === "string" && /^[a-z0-9_]{1,64}$/.test(input.error_code))) throw new Error("Invalid ChatGPT connection");
  let account: ChatgptConnection["account"] = null, login: ChatgptConnection["login"] = null;
  if (input.account !== null) {
    const value = record(input.account);
    if (!value || !nullableText(value.email, 320) || !nullableText(value.plan_type, 64)) throw new Error("Invalid ChatGPT account");
    if (input.status === "connected") account = { email: value.email, plan_type: value.plan_type };
  }
  if (input.status === "pending" || input.status === "starting") {
    if (input.login !== null) {
      const value = record(input.login);
      if (!value || !text(value.id, 128) || !/^[a-zA-Z0-9._:-]+$/.test(value.id) ||
          !text(value.user_code, 128) || !/^[a-zA-Z0-9][a-zA-Z0-9 -]*$/.test(value.user_code) ||
          value.verification_url !== CHATGPT_VERIFICATION_URL || typeof value.expires_at !== "string" || !stamp(value.expires_at)) throw new Error("Invalid ChatGPT login");
      login = { id: value.id, user_code: value.user_code, verification_url: CHATGPT_VERIFICATION_URL, expires_at: value.expires_at };
    } else if (input.status === "pending") throw new Error("Missing ChatGPT login");
  }
  return { provider: "chatgpt", available: input.available, status: input.status as ChatgptStatus, account, login,
    connected_at: input.connected_at, updated_at: input.updated_at,
    poll_interval_seconds: Math.min(60, input.poll_interval_seconds), error_code: input.error_code };
}

export function expireChatgptLogin(connection: ChatgptConnection, now: number): ChatgptConnection {
  return connection.login && (!Number.isFinite(now) || now >= Date.parse(connection.login.expires_at))
    ? { ...connection, status: "expired", login: null } : connection;
}
export function chatgptNeedsPolling(connection: ChatgptConnection | null): boolean {
  return !!connection && (connection.status === "starting" || connection.status === "pending");
}
