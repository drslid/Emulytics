import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Keep this boundary test independent of React's locale provider.
const source = readFileSync(new URL("../lib/client-api.ts", import.meta.url), "utf8").replace(/^import \{ browserT \} from .*;\r?\n/, "const browserT = (source: string) => source;\n");
const compiled = ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
const { api, ApiError } = await import("data:text/javascript;base64," + Buffer.from(compiled).toString("base64"));

test("device removal exposes only trusted conflict codes", async t => {
  for (const code of ["device_busy", "stop_emulator_first", "device_scheduled"]) {
    t.mock.method(globalThis, "fetch", async () => Response.json({ detail: { code, hint: "private diagnostics" } }, { status: 409 }));
    await assert.rejects(api("console/devices/phone", undefined, "DELETE"), failure => {
      assert.equal(failure.status, 409);
      assert.equal(failure.code, code);
      assert.doesNotMatch(failure.message, /private diagnostics/);
      return true;
    });
    t.mock.restoreAll();
  }
});

test("deleting a published version sends only the confirmed DELETE and accepts an empty response", async t => {
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/control/workflows/example/versions/2");
    assert.equal(options.method, "DELETE");
    assert.equal(options.body, undefined);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.headers["X-Emulytix-Client"], "console");
    return new Response(null, {status:204});
  });
  assert.equal(await api("workflows/example/versions/2", undefined, "DELETE"), null);
});

test("workflow lifecycle conflicts give actionable trusted errors without exposing server text", async t => {
  for (const [status, code, message] of [
    [409, "workflow_version_has_schedules", "Supprimez d’abord les planifications qui utilisent cette version, même celles en pause."],
    [409, "workflow_version_in_use", "Cette version est utilisée par une exécution en attente ou en cours. Attendez sa fin avant de la supprimer."],
    [410, "workflow_version_deleted", "Cette version a été supprimée. Choisissez une autre version publiée."],
  ]) {
    t.mock.method(globalThis, "fetch", async () => Response.json({detail:{code, message:"private backend diagnostics"}}, {status}));
    await assert.rejects(api("workflows/example/versions/2", undefined, "DELETE"), error => {
      assert(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.equal(error.code, code);
      assert.equal(error.message, message);
      return true;
    });
    t.mock.restoreAll();
  }
});

test("unknown conflict codes and backend text remain outside the UI error contract", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({detail:{code:"unreviewed", message:"private backend diagnostics"}}, {status:409}));
  await assert.rejects(api("workflows/example/versions/2", undefined, "DELETE"), error => {
    assert.equal(error.code, undefined);
    assert.equal(error.message, "L’état a changé ou cet identifiant est déjà utilisé. Actualisez avant de réessayer.");
    return true;
  });
});

test("recipe generation exposes the known configuration error without raw server diagnostics", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({
    detail: { code: "provider_unconfigured", message: "private backend diagnostics" },
  }, { status: 409 }));
  await assert.rejects(api("console/recipes/generate", { instructions: "Draft a journey", provider: "ollama" }), error => {
    assert.equal(error.code, "provider_unconfigured");
    assert.doesNotMatch(error.message, /private backend diagnostics/);
    return true;
  });
});
