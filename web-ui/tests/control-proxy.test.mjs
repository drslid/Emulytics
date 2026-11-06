import assert from "node:assert/strict";
import { test } from "node:test";
import { proxyControl, sessionCookies } from "../lib/control-proxy.ts";

process.env.EMULYTIX_API_INTERNAL_URL = "http://api.internal:8010";
process.env.EMULYTIX_PUBLIC_ORIGIN = "http://localhost:3100";

function request(path, options = {}) {
  return new Request(`http://localhost:3100/api/control/${path}`, options);
}

function post(body = "{}", origin = "http://localhost:3100") {
  return { method: "POST", body, headers: { Origin: origin, "Content-Type": "application/json", "X-Emulytix-Client": "console" } };
}

test("browser proxy cannot become a general backend or URL proxy", async () => {
  for (const path of ["sessions", "auth/admin", "../health", "https://evil.test", "runs/no-such-run", "devices/anything"]) {
    const response = await proxyControl(request(path), path.split("/"), () => { throw new Error("must not send"); });
    assert.equal(response.status, 404, path);
  }
});

test("cross-origin and non-console mutations stop before contacting backend", async () => {
  assert.equal((await proxyControl(request("runs", post("{}", "https://evil.test")), ["runs"])).status, 403);
  const options = post();
  delete options.headers["X-Emulytix-Client"];
  assert.equal((await proxyControl(request("runs", options), ["runs"])).status, 403);
});

test("proxy forwards only operator cookies, never browser bearer credentials", async () => {
  let called = false;
  const response = await proxyControl(request("devices?limit=10&secret=do-not-forward", { headers: {
    Cookie: "other=private; emulytix_session=session_value; emulytix_challenge=challenge_value", Authorization: "Bearer must-not-forward"
  } }), ["devices"], async (url, options) => {
    called = true;
    assert.equal(url, "http://api.internal:8010/devices?limit=10");
    assert.equal(options.headers.get("authorization"), null);
    assert.equal(options.headers.get("cookie"), "emulytix_session=session_value; emulytix_challenge=challenge_value");
    return Response.json({ items: [] }, { headers: { "Set-Cookie": "emulytix_session=new; HttpOnly; SameSite=Strict; Path=/" } });
  });
  assert.equal(called, true);
  assert.equal(response.headers.getSetCookie().length, 1);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(sessionCookies("emulytix_session=bad value; other=x"), "");
});

test("upstream errors and network failures do not disclose configuration", async () => {
  for (const fetcher of [async () => new Response("postgres://secret", { status: 500 }), async () => { throw new Error("internal host password"); }]) {
    const response = await proxyControl(request("devices"), ["devices"], fetcher);
    assert.equal(response.status, 503);
    assert.doesNotMatch(await response.text(), /postgres|password|secret/);
  }
});

test("large and non-JSON bodies cannot reach the backend", async () => {
  const large = await proxyControl(request("runs", post("x".repeat(65_537))), ["runs"]);
  assert.equal(large.status, 413);
  const options = post();
  options.headers["Content-Type"] = "text/plain";
  assert.equal((await proxyControl(request("runs", options), ["runs"])).status, 415);
});

test("password replacement uses the restricted challenge route and rotates its cookie", async () => {
  const credentials = { password: "test-new-password-only", confirm_password: "test-new-password-only" };
  const response = await proxyControl(request("auth/change-password", post(JSON.stringify(credentials))), ["auth", "change-password"], async (url, options) => {
    assert.equal(url, "http://api.internal:8010/auth/change-password?");
    assert.deepEqual(JSON.parse(new TextDecoder().decode(options.body)), credentials);
    return Response.json({ step: "enroll" }, { headers: { "Set-Cookie": "emulytix_challenge=rotated; HttpOnly; SameSite=Strict; Path=/" } });
  });
  assert.deepEqual(await response.json(), { step: "enroll" });
  assert.match(response.headers.get("set-cookie"), /emulytix_challenge=rotated/);
});
