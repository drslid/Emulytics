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

test("new administrative and automation routes remain explicitly bounded and CSRF protected", async () => {
  const id = "00000000-0000-4000-8000-000000000001";
  for (const [path, method] of [[`console/users/${id}`, "PATCH"], [`console/schedules/${id}`, "DELETE"], [`console/recipes/${id}/publish`, "POST"]]) {
    let called = false;
    const options = {...post(),method};
    const result = await proxyControl(request(path,options),path.split("/"),async (_url,upstream) => {
      called = true; assert.equal(upstream.method,method); return Response.json({ok:true});
    });
    assert.equal(result.status,200);assert.equal(called,true);
    assert.equal((await proxyControl(request(path,{...options,headers:{...options.headers,Origin:"https://invalid.test"}}),path.split("/"))).status,403);
  }
  for (const [path, method] of [["console/users","DELETE"],[`console/users/${id}/reset-password`,"PATCH"],["console/monitor/stream","POST"]]) {
    assert.equal((await proxyControl(request(path,{...post(),method}),path.split("/"))).status,404);
  }
});

test("monitor stream preserves streaming and aborts with the browser request, without passing credentials", async () => {
  const abort = new AbortController(); let signal;
  const result = await proxyControl(request("console/monitor/stream",{signal:abort.signal}),["console","monitor","stream"], async (_url,options) => {
    signal = options.signal;
    return new Response('data: {"ready":true}\n\n',{headers:{"Content-Type":"text/event-stream"}});
  });
  assert.equal(result.headers.get("content-type"),"text/event-stream");assert.equal(result.headers.get("x-accel-buffering"),"no");
  assert.match(await result.text(),/ready/);abort.abort();assert.equal(signal.aborted,true);
});

test("live device frames stay within the private proxy and preserve observation headers", async () => {
  const response = await proxyControl(request("console/devices/local-emulator/screen"), ["console","devices","local-emulator","screen"], async (url, options) => {
    assert.equal(url,"http://api.internal:8010/console/devices/local-emulator/screen?");
    assert.equal(options.method,"GET");
    return new Response(new Uint8Array([137,80,78,71]),{headers:{"Content-Type":"image/png","X-Screen-Captured-At":"2026-11-06T17:00:00Z","X-Screen-Age":"0.3","X-Screen-Frame-Id":"aabbcc"}});
  });
  assert.equal(response.headers.get("content-type"),"image/png");
  assert.equal(response.headers.get("x-screen-age"),"0.3");assert.equal(response.headers.get("x-screen-frame-id"),"aabbcc");
  assert.equal(response.headers.get("cache-control"),"private, no-store");
  assert.equal((await response.arrayBuffer()).byteLength,4);
  for (const path of ["console/devices/../screen", "console/devices/local-emulator/screen/../private", "console/devices/local-emulator/adb"]) {
    assert.equal((await proxyControl(request(path),path.split("/"))).status,404);
  }
  assert.equal((await proxyControl(request("console/devices/local-emulator/screen",post()),["console","devices","local-emulator","screen"])).status,404);
});
