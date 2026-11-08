import assert from "node:assert/strict";
import { test } from "node:test";
import { CHATGPT_VERIFICATION_URL, chatgptNeedsPolling, expireChatgptLogin, parseChatgptConnection } from "../lib/chatgpt.ts";

const connection = { provider: "chatgpt", available: true, status: "disconnected", account: null, login: null,
  connected_at: null, updated_at: "2026-11-06T21:00:00Z", poll_interval_seconds: 5, error_code: null };
const login = { id: "attempt-1", user_code: "ABCD-EFGH", verification_url: CHATGPT_VERIFICATION_URL, expires_at: "2026-11-06T21:15:00Z" };

test("device authorization accepts only the exact OpenAI URL and projects reviewed public fields", () => {
  const parsed = parseChatgptConnection({ ...connection, status: "pending", login: { ...login, device_code: "private-code" }, access_token: "private-token" });
  assert.deepEqual(parsed.login, login);
  assert.equal(Object.hasOwn(parsed, "access_token"), false);
  assert.equal(Object.hasOwn(parsed.login, "device_code"), false);
  for (const verification_url of ["http://auth.openai.com/codex/device", "https://auth.openai.com/codex/device?code=bad", "https://auth.openai.com/codex/device#bad", "https://auth.openai.com.attacker.test/codex/device", "javascript:alert(1)", "https://user:secret@auth.openai.com/codex/device"])
    assert.throws(() => parseChatgptConnection({ ...connection, status: "pending", login: { ...login, verification_url } }));
});
test("an expired code is removed locally even when the server cannot be reached", () => {
  const pending = parseChatgptConnection({ ...connection, status: "pending", login });
  assert.equal(expireChatgptLogin(pending, Date.parse(login.expires_at) - 1), pending);
  const expired = expireChatgptLogin(pending, Date.parse(login.expires_at));
  assert.equal(expired.status, "expired"); assert.equal(expired.login, null); assert.equal(chatgptNeedsPolling(expired), false);
  assert.equal(expireChatgptLogin(pending, NaN).login, null);
  assert.equal(pending.login.user_code, "ABCD-EFGH");
});
test("completed authorization never keeps the old code or polls as if still pending", () => {
  for (const status of ["connected", "expired", "disconnected", "error"]) {
    const parsed = parseChatgptConnection({ ...connection, status, login });
    assert.equal(parsed.login, null); assert.equal(chatgptNeedsPolling(parsed), false);
  }
  assert.equal(chatgptNeedsPolling(parseChatgptConnection({ ...connection, status: "starting" })), true);
  assert.equal(chatgptNeedsPolling(null), false);
});
test("unknown states and malformed payloads do not appear as a disconnected or connected account", () => {
  for (const candidate of [null, {}, { ...connection, provider: "other" }, { ...connection, status: "ready" }, { ...connection, status: "pending" },
    { ...connection, connected_at: "bad-date" }, { ...connection, poll_interval_seconds: 0 }, { ...connection, poll_interval_seconds: Infinity },
    { ...connection, account: { email: 123, plan_type: null } }, { ...connection, error_code: "<script>" },
    { ...connection, status: "pending", login: { ...login, user_code: "<script>" } }]) assert.throws(() => parseChatgptConnection(candidate));
  const account = parseChatgptConnection({ ...connection, status: "connected", account: { email: "person@example.test", plan_type: "plus", refresh_token: "private-token" } });
  assert.deepEqual(account.account, { email: "person@example.test", plan_type: "plus" });
  assert.equal(parseChatgptConnection({ ...connection, poll_interval_seconds: 3600 }).poll_interval_seconds, 60);
});
