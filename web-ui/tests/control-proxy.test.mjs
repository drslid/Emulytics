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

test("personal ChatGPT routes preserve only the session and reject arbitrary provider control", async () => {
  for (const [path, method] of [
    ['console/account/chatgpt', 'GET'], ['console/account/chatgpt/login', 'POST'],
    ['console/account/chatgpt/cancel', 'POST'], ['console/account/chatgpt', 'DELETE']
  ]) {
    const options = method === 'GET' ? {headers:{Cookie:'emulytix_session=personal; other=secret',Authorization:'Bearer forbidden'}}
      : {...post(),method,headers:{...post().headers,Cookie:'emulytix_session=personal; other=secret',Authorization:'Bearer forbidden'}};
    const result = await proxyControl(request(path, options), path.split('/'), async (url, upstream) => {
      assert.equal(url, `http://api.internal:8010/${path}?`);
      assert.equal(upstream.headers.get('cookie'), 'emulytix_session=personal');
      assert.equal(upstream.headers.get('authorization'), null);
      assert.equal(upstream.method, method);
      return Response.json({provider:'chatgpt',status:'disconnected'});
    });
    assert.equal(result.status, 200);
    assert.equal(result.headers.get('cache-control'), 'private, no-store');
  }
  const never = () => assert.fail('Rejected requests must not reach a provider');
  for (const [path, options] of [
    ['console/account/chatgpt/tokens', {}], ['console/account/chatgpt/login', {}],
    ['console/account/chatgpt/rpc', post()], ['console/account/openai/login', post()],
    ['console/account/chatgpt', {...post(),method:'PATCH'}],
    ['console/account/chatgpt/logout', post()], ['console/account/chatgpt/login/extra', post()]
  ]) assert.equal((await proxyControl(request(path,options), path.split('/'), never)).status,404);
  for (const path of ['console/account/chatgpt/login','console/account/chatgpt/cancel']) {
    assert.equal((await proxyControl(request(path,post('{}','https://other.test')),path.split('/'),never)).status,403);
  }
  const path = 'console/account/chatgpt';
  assert.equal((await proxyControl(request(path,{...post('{}','https://other.test'),method:'DELETE'}),path.split('/'),never)).status,403);
});

test("AI provider preferences proxy only scoped reads and CSRF-protected patches", async () => {
  const endpoint = "console/account/ai-providers";
  const path = endpoint.split("/");
  const body = JSON.stringify({ active_provider: "ollama", deepseek_key: null });
  for (const [method, payload] of [["GET", undefined], ["PATCH", body]]) {
    const options = { method, body: payload, headers: { ...post().headers, Cookie: "emulytix_session=account; other=discard", Authorization: "Bearer discard" } };
    const result = await proxyControl(request(endpoint, options), path, async (url, upstream) => {
      assert.equal(url, `http://api.internal:8010/${endpoint}?`);
      assert.equal(upstream.method, method);
      assert.equal(upstream.headers.get("Cookie"), "emulytix_session=account");
      assert.equal(upstream.headers.get("Authorization"), null);
      assert.equal(upstream.body && new TextDecoder().decode(upstream.body), payload);
      return Response.json({ active_provider: "ollama" });
    });
    assert.equal(result.status, 200);
  }
  const reject = () => assert.fail("Rejected request must not reach provider preferences");
  assert.equal((await proxyControl(request(endpoint, { ...post(body, "https://other.test"), method: "PATCH" }), path, reject)).status, 403);
  assert.equal((await proxyControl(request(endpoint, post(body)), path, reject)).status, 404);
  assert.equal((await proxyControl(request(endpoint + "/key"), [...path, "key"], reject)).status, 404);
});

test("managed emulator routes preserve session and refuse arbitrary Docker endpoints", async () => {
  for (const endpoint of ['console/emulators', 'console/emulators/emu-example/start', 'console/emulators/emu-example/prepare', 'console/emulators/emu-example/stop', 'console/emulators/emu-example/configuration']) {
    const result = await proxyControl(request(endpoint, post()), endpoint.split('/'), async (url) => {
      assert.equal(url, `http://api.internal:8010/${endpoint}?`);
      return Response.json({ ok: true });
    });
    assert.equal(result.status, 200);
  }
  for (const endpoint of ['console/emulators/emu-example/exec', 'console/emulators/emu-example/delete', 'console/docker']) {
    const result = await proxyControl(request(endpoint, post()), endpoint.split('/'), () => assert.fail('Unexpected backend call'));
    assert.equal(result.status, 404);
  }
});

test("system updates allow only the scoped session endpoint and same-origin JSON mutations", async () => {
  const path = ["console", "updates"];
  const endpoint = path.join("/");
  const headers = { ...post().headers, Cookie: "emulytix_session=admin; other=secret", Authorization: "Bearer private" };
  for (const [method, body] of [["GET", undefined], ["POST", '{"version":"0.3.0"}']]) {
    const response = await proxyControl(request(endpoint, { method, body, headers }), path, async (url, upstream) => {
      assert.equal(url, "http://api.internal:8010/console/updates?");
      assert.equal(upstream.method, method);
      assert.equal(upstream.headers.get("cookie"), "emulytix_session=admin");
      assert.equal(upstream.headers.get("authorization"), null);
      assert.equal(upstream.body && new TextDecoder().decode(upstream.body), body);
      return Response.json({ state: "queued" }, { status: method === "POST" ? 202 : 200 });
    });
    assert.equal(response.status, method === "POST" ? 202 : 200);
  }
  const reject = () => assert.fail("Rejected requests must not reach the updater");
  assert.equal((await proxyControl(request(endpoint, post("{}", "https://untrusted.example")), path, reject)).status, 403);
  assert.equal((await proxyControl(request(endpoint, { method: "DELETE", headers }), path, reject)).status, 404);
  assert.equal((await proxyControl(request(endpoint + "/exec", post()), [...path, "exec"], reject)).status, 404);
});

test("F-Droid search forwards the query and import requires a same-origin JSON request", async () => {
  const endpoint = "console/applications/fdroid";
  const path = endpoint.split("/");
  const search = await proxyControl(request(`${endpoint}?q=Simple+Notes&url=https%3A%2F%2Fignored.test`), path, async url => {
    assert.equal(url, `http://api.internal:8010/${endpoint}?q=Simple+Notes`);
    return Response.json({ items: [] });
  });
  assert.equal(search.status, 200);
  const choice = { package_name: "org.example.notes", sha256: "a".repeat(64) };
  const imported = await proxyControl(request(endpoint, post(JSON.stringify(choice))), path, async (url, options) => {
    assert.equal(url, `http://api.internal:8010/${endpoint}?`);
    assert.deepEqual(JSON.parse(new TextDecoder().decode(options.body)), choice);
    return Response.json({ id: "release" }, { status: 201 });
  });
  assert.equal(imported.status, 201);
  const rejected = await proxyControl(request(endpoint, post("{}", "https://other.test")), path, () => assert.fail("Unexpected import"));
  assert.equal(rejected.status, 403);
});

test("Aptoide searches and version reads are scoped separately from the protected import", async () => {
  const endpoint = "console/applications/aptoide";
  const versions = endpoint + "/versions";
  for (const [path, query] of [[endpoint, "LinkedIn"], [versions, "com.linkedin.android"]]) {
    const read = await proxyControl(request(`${path}?q=${query}&url=https%3A%2F%2Fignored.test`), path.split("/"), async url => {
      assert.equal(url, `http://api.internal:8010/${path}?q=${query}`);
      return Response.json({});
    });
    assert.equal(read.status, 200);
  }
  const selected = { package_name: "com.linkedin.android", version_id: "160123456" };
  const imported = await proxyControl(request(endpoint, post(JSON.stringify(selected))), endpoint.split("/"), async (url, options) => {
    assert.equal(url, `http://api.internal:8010/${endpoint}?`);
    assert.deepEqual(JSON.parse(new TextDecoder().decode(options.body)), selected);
    return Response.json({ id: "release" }, { status: 201 });
  });
  assert.equal(imported.status, 201);
  const reject = () => assert.fail("Rejected request must not reach the store");
  assert.equal((await proxyControl(request(versions, post()), versions.split("/"), reject)).status, 404);
  assert.equal((await proxyControl(request(endpoint, post("{}", "https://other.test")), endpoint.split("/"), reject)).status, 403);
});

test("APK multipart uploads retain their boundary and use only the exact protected upload route", async () => {
  const body = new FormData();
  body.set('file', new File(['apk-test-bytes'], 'linkedin.apk', { type: 'application/vnd.android.package-archive' }));
  const incoming = request('console/applications', { method: 'POST', body, headers: {
    Origin: 'http://localhost:3100', 'X-Emulytix-Client': 'console', Cookie: 'emulytix_session=valid; another=discard'
  } });
  const boundary = incoming.headers.get('content-type');
  const result = await proxyControl(incoming, ['console', 'applications'], async (url, options) => {
    assert.equal(url, 'http://api.internal:8010/console/applications?');
    assert.equal(options.headers.get('content-type'), boundary);
    assert.equal(options.headers.get('cookie'), 'emulytix_session=valid');
    assert.match(new TextDecoder().decode(options.body), /apk-test-bytes/);
    return Response.json({ ok: true }, { status: 201 });
  });
  assert.equal(result.status, 201);
  const badOrigin = await proxyControl(request('console/applications', { method: 'POST', body: new FormData(), headers: {
    Origin: 'https://other.test', 'X-Emulytix-Client': 'console'
  } }), ['console', 'applications'], () => assert.fail('CSRF must fail'));
  assert.equal(badOrigin.status, 403);
  const wrongRoute = await proxyControl(request('devices', { method: 'POST', body: new FormData(), headers: {
    Origin: 'http://localhost:3100', 'X-Emulytix-Client': 'console'
  } }), ['devices'], () => assert.fail('Multipart must not bypass JSON on other routes'));
  assert.equal(wrongRoute.status, 415);
});

async function withGoBackend(base, run) {
  const previous = process.env.EMULYTIX_GO_API_INTERNAL_URL;
  if (base === undefined) delete process.env.EMULYTIX_GO_API_INTERNAL_URL;
  else process.env.EMULYTIX_GO_API_INTERNAL_URL = base;
  try { await run(); }
  finally {
    if (previous === undefined) delete process.env.EMULYTIX_GO_API_INTERNAL_URL;
    else process.env.EMULYTIX_GO_API_INTERNAL_URL = previous;
  }
}

test("only exact migrated dashboard reads use the optional Go backend with restricted credentials and queries", async () => {
  await withGoBackend("http://go.internal:8020/", async () => {
    for (const endpoint of ["summary", "fleet", "dashboard"]) {
      const result = await proxyControl(request(`console/${endpoint}?limit=10&offset=20&secret=discard`, { headers: {
        Cookie:"other=private; emulytix_session=session_value; emulytix_challenge=challenge_value",
        Authorization:"Bearer must-not-forward", "X-User":"admin", "X-Emulytix-Backend":"go"
      } }), ["console",endpoint], async (url, options) => {
        assert.equal(url, `http://go.internal:8020/console/${endpoint}?limit=10&offset=20`);
        assert.equal(options.method,"GET");
        assert.equal(options.headers.get("cookie"),"emulytix_session=session_value; emulytix_challenge=challenge_value");
        for (const header of ["Authorization","X-User","X-Emulytix-Backend"]) assert.equal(options.headers.get(header),null);
        assert.equal(options.redirect,"error");
        return Response.json({ok:true},{headers:{"X-Emulytix-Backend":"go"}});
      });
      assert.equal(result.status,200);
      assert.equal(result.headers.get("X-Emulytix-Backend"),"go");
      assert.equal(result.headers.get("cache-control"),"private, no-store");
    }
  });
});

test("migrated dashboard reads retain the Python backend when Go is not configured", async () => {
  await withGoBackend(undefined, async () => {
    for (const endpoint of ["summary","fleet","dashboard"]) {
      const result=await proxyControl(request(`console/${endpoint}`),["console",endpoint],async(url)=>{
        assert.equal(url,`http://api.internal:8010/console/${endpoint}?`);
        return Response.json({ok:true},{headers:{"X-Emulytix-Backend":"go"}});
      });
      assert.equal(result.status,200);
      assert.equal(result.headers.get("X-Emulytix-Backend"),null);
    }
  });
});

test("a configured Go failure returns the existing sanitized error without falling back to Python", async () => {
  await withGoBackend("http://go.internal:8020", async () => {
    for (const path of ["console/fleet","console/summary","console/dashboard"]) {
      for(const fail of [()=>new Response("private database configuration",{status:503,headers:{"X-Emulytix-Backend":"go"}}),()=>{throw new Error("private internal address");}]) {
        const calls=[];
        const result=await proxyControl(request(path),path.split("/"),async(url)=>{calls.push(url);return fail();});
        assert.deepEqual(calls,[`http://go.internal:8020/${path}?`]);
        assert.equal(result.status,503);
        assert.equal(result.headers.get("X-Emulytix-Backend"),null);
        assert.doesNotMatch(await result.text(),/private|database|internal/);
      }
    }
  });
});

test("all other reads and authorized mutations stay on Python and cannot claim the Go response marker", async () => {
  await withGoBackend("http://go.internal:8020", async () => {
    for(const [path,options] of [["auth/me",{}],["devices",{}],["console/monitor",{}],["console/recipes",{}],["console/recipes/from-workflow",post()],["devices",post()]]) {
      const result=await proxyControl(request(path,options),path.split("/"),async(url,upstream)=>{
        assert.equal(url,`http://api.internal:8010/${path}?`);
        assert.equal(upstream.method,options.method??"GET");
        return Response.json({ok:true},{headers:{"X-Emulytix-Backend":"go"}});
      });
      assert.equal(result.status,200);
      assert.equal(result.headers.get("X-Emulytix-Backend"),null);
    }
  });
});

test("Go routing cannot widen the method, segment or mutation-origin allowlists", async () => {
  await withGoBackend("http://go.internal:8020", async () => {
    const never=async()=>{assert.fail("Rejected requests must not contact any backend");};
    for(const [path,options,segments] of [
      ["console/fleet/extra",{},["console","fleet","extra"]],
      ["console/summary",{},["console/summary"]],
      ["console/summary",post(),["console","summary"]],
      ["console/fleet",{method:"HEAD"},["console","fleet"]],
      ["console/fleet",{...post(),method:"PATCH"},["console","fleet"]],
      ["console/dashboard/extra",{},["console","dashboard","extra"]],
      ["console/dashboard",post(),["console","dashboard"]]
    ]) assert.equal((await proxyControl(request(path,options),segments,never)).status,404);
    assert.equal((await proxyControl(request("devices",post("{}","https://invalid.test")),["devices"],never)).status,403);
  });
});

test("the dashboard timezone is forwarded only on its exact read route", async () => {
  await withGoBackend("http://go.internal:8020",async()=>{
    for(const path of ["console/dashboard","console/summary","console/fleet","console/monitor"]){
      const result=await proxyControl(request(path+"?timezone=Europe%2FParis&window=7d&secret=discard"),path.split("/"),async(url)=>{
        const upstream=new URL(url);
        assert.equal(upstream.origin,path==="console/monitor"?"http://api.internal:8010":"http://go.internal:8020");
        assert.equal(upstream.searchParams.get("timezone"),path==="console/dashboard"?"Europe/Paris":null);
        assert.equal(upstream.searchParams.get("window"),"7d");
        assert.equal(upstream.searchParams.has("secret"),false);
        return Response.json({ok:true});
      });assert.equal(result.status,200);
    }
  });
});

test("the Go response marker is accepted only as the exact upstream value on a migrated route", async () => {
  await withGoBackend("http://go.internal:8020", async () => {
    for(const marker of [null,"Go","go, python","python"]) {
      const result=await proxyControl(request("console/fleet"),["console","fleet"],async()=>Response.json({}, {headers:marker?{"X-Emulytix-Backend":marker}:{}}));
      assert.equal(result.headers.get("X-Emulytix-Backend"),null);
    }
    const unauthorized=await proxyControl(request("console/summary"),["console","summary"],async()=>Response.json({detail:"Authentication required"},{status:401,headers:{"X-Emulytix-Backend":"go"}}));
    assert.equal(unauthorized.status,401);
    assert.equal(unauthorized.headers.get("X-Emulytix-Backend"),"go");
  });
});

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
  const result = await proxyControl(request("console/monitor/stream?window=7d&secret=discard",{signal:abort.signal}),["console","monitor","stream"], async (url,options) => {
    assert.match(url,/window=7d/);assert.doesNotMatch(url,/secret/);
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

test("execution-bound live frames stay on the existing authenticated backend and preserve observation metadata", async () => {
  const path = "console/executions/12345678-1234-4234-9234-123456789abc/screen";
  process.env.EMULYTIX_GO_API_INTERNAL_URL = "http://go.internal:8020";
  try {
    const response = await proxyControl(request(path, {headers:{Cookie:"emulytix_session=ready",Authorization:"Bearer ignored"}}), path.split("/"), async (url, options) => {
      assert.equal(url,`http://api.internal:8010/${path}?`);
      assert.equal(options.headers.get("cookie"),"emulytix_session=ready");
      assert.equal(options.headers.get("authorization"),null);
      return new Response("png", {headers:{"Content-Type":"image/png","X-Screen-Captured-At":"2026-11-06T19:00:00Z","X-Screen-Age":"0.2","X-Screen-Frame-Id":"bound-frame"}});
    });
    assert.equal(response.headers.get("x-screen-frame-id"),"bound-frame");
    assert.equal(response.headers.get("x-screen-age"),"0.2");
    assert.equal(response.headers.get("x-emulytix-backend"),null);
    assert.equal((await proxyControl(request(path,post()),path.split("/"))).status,404);
    assert.equal((await proxyControl(request(path.replace("screen","adb")),path.replace("screen","adb").split("/"))).status,404);
  } finally {delete process.env.EMULYTIX_GO_API_INTERNAL_URL;}
});

test("personal security routes are explicit, CSRF protected and forward rotated cookies", async () => {
  for (const path of ["console/account/security","console/account/two-factor/enrollment","console/account/two-factor/enrollment/qr"]) {
    const response=await proxyControl(request(path),path.split("/"),async()=>Response.json({ok:true}));
    assert.equal(response.status,200,path);
  }
  for (const path of ["console/account/password","console/account/recovery-codes","console/account/two-factor/start","console/account/two-factor/confirm"]) {
    let sent=false;
    const response=await proxyControl(request(path,post()),path.split("/"),async(_url,options)=>{sent=true;assert.equal(options.headers.get("authorization"),null);return Response.json({ok:true},{headers:{"Set-Cookie":"emulytix_session=rotated; HttpOnly; SameSite=Strict; Path=/"}});});
    assert.equal(sent,true,path);assert.equal(response.headers.getSetCookie().length,1);
    assert.equal((await proxyControl(request(path,post("{}","https://invalid.test")),path.split("/"))).status,403);
  }
  assert.equal((await proxyControl(request("console/account/two-factor/enrollment",{...post(),method:"DELETE"}),["console","account","two-factor","enrollment"],async()=>Response.json({ok:true}))).status,200);
  for (const path of ["console/account/users/admin/password","console/account/two-factor/disable","console/account/security/reset"]) {
    assert.equal((await proxyControl(request(path,post()),path.split("/"))).status,404,path);
  }
});

test("user administration detail, filters and security actions use only bounded routes", async () => {
  const id="00000000-0000-4000-8000-000000000001";
  const response=await proxyControl(request(`console/users/${id}?role=viewer&active=active&two_factor=pending&onboarding=required&secret=discard`),["console","users",id],async(url)=>{
    assert.match(url,/role=viewer/);assert.match(url,/two_factor=pending/);assert.match(url,/onboarding=required/);assert.doesNotMatch(url,/secret/);return Response.json({id});
  });assert.equal(response.status,200);
  for(const action of ["revoke-sessions","force-password-change"]){
    const path=`console/users/${id}/${action}`;
    assert.equal((await proxyControl(request(path,post()),path.split("/"),async()=>Response.json({ok:true}))).status,200);
    assert.equal((await proxyControl(request(path,post("{}","https://invalid.test")),path.split("/"))).status,403);
  }
  assert.equal((await proxyControl(request("console/account/profile",{...post(),method:"PATCH"}),["console","account","profile"],async()=>Response.json({user:{id}}))).status,200);
  assert.equal((await proxyControl(request("console/users/invalid/user"),["console","users","invalid","user"])).status,404);
});

test("published workflow editing creates only a protected draft through the exact console route", async () => {
  const path="console/recipes/from-workflow";
  let sent=false;
  const result=await proxyControl(request(path,post()),path.split("/"),async(url,options)=>{
    sent=true;assert.match(url,/\/console\/recipes\/from-workflow\?/);assert.equal(options.method,"POST");assert.equal(options.headers.get("authorization"),null);return Response.json({id:"draft"});
  });
  assert.equal(result.status,200);assert.equal(sent,true);
  assert.equal((await proxyControl(request(path,post("{}","https://invalid.test")),path.split("/"))).status,403);
  assert.equal((await proxyControl(request(path),path.split("/"))).status,404);
  assert.equal((await proxyControl(request(path+"/publish",post()),["console","recipes","from-workflow","publish"])).status,404);
});

test("published-version deletion forwards only the exact protected version route", async () => {
  const path = 'workflows/android-version/versions/2';
  const options = {...post(),method:'DELETE',headers:{...post().headers,Cookie:'other=discard; emulytix_session=builder',Authorization:'Bearer forbidden'}};
  const response = await proxyControl(request(path,options),path.split('/'),async (url,upstream)=>{
    assert.equal(url,'http://api.internal:8010/'+path+'?');
    assert.equal(upstream.method,'DELETE');
    assert.equal(upstream.headers.get('cookie'),'emulytix_session=builder');
    assert.equal(upstream.headers.get('authorization'),null);
    return new Response(null,{status:204});
  });
  assert.equal(response.status,204);
  const denied=()=>assert.fail('Invalid deletion must not reach the backend');
  for(const endpoint of ['workflows','workflows/android-version','workflows/android-version/versions','workflows/android-version/versions/2/extra','workflows/android-version/versions/-1']) {
    assert.equal((await proxyControl(request(endpoint,options),endpoint.split('/'),denied)).status,404);
  }
  assert.equal((await proxyControl(request(path,{...options,headers:{...options.headers,Origin:'https://other.test'}}),path.split('/'),denied)).status,403);
  const conflict=await proxyControl(request(path,options),path.split('/'),async()=>Response.json({detail:{code:'workflow_version_has_schedules'}},{status:409}));
  assert.equal(conflict.status,409);
  assert.deepEqual(await conflict.json(),{detail:{code:'workflow_version_has_schedules'}});
});
