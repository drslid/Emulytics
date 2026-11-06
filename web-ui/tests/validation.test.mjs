import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { readValidation, readValidationImage } from "../lib/validation.ts";

const report = {
  started_at: "2026-11-05T21:41:02Z", finished_at: "2026-11-05T21:42:39Z", status: "passed",
  runs: [{ run_id: "run-1", execution_id: "execution-1", status: "succeeded", action_count: 8,
    event_count: 19, step_count: 11, lease_epoch: 1, url: "https://fr.wikipedia.org/wiki/Football", heading: "Football" }],
  checks: [{ passed: true }, { passed: false }], inference: { llm_calls: 0 },
  bench_cleanup: { stopped_after_validation: true }, secret: "must-never-leave-server"
};

async function archive(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "emulytix-validation-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(path.join(directory, "validation.json"), JSON.stringify(report));
  return directory;
}

test("archive projection counts actual outcomes and omits unrelated fields", async (t) => {
  const directory = await archive(t);
  const result = await readValidation(directory);
  assert.equal(result.checks_passed, 1);
  assert.equal(result.checks_total, 2);
  assert.equal(result.llm_calls, 0);
  assert.equal(result.bench_stopped, true);
  assert.equal(result.runs[0].status, "succeeded");
  assert.equal(JSON.stringify(result).includes(report.secret), false);
});

test("missing and corrupt archives return the unavailable state", async (t) => {
  const directory = await archive(t);
  assert.equal(await readValidation(""), null);
  assert.equal(await readValidation(path.join(directory, "missing")), null);
  await writeFile(path.join(directory, "validation.json"), "{");
  assert.equal(await readValidation(directory), null);
});

test("malformed counts and unexpected result links cannot become evidence", async (t) => {
  const directory = await archive(t);
  for (const patch of [{ action_count: -1 }, { url: "javascript:alert(1)" }]) {
    await writeFile(path.join(directory, "validation.json"), JSON.stringify({ ...report, runs: [{ ...report.runs[0], ...patch }] }));
    assert.equal(await readValidation(directory), null);
  }
});

test("only the four named PNG files can be served", async (t) => {
  const directory = await archive(t);
  const png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  await writeFile(path.join(directory, "run-1-result.png"), png);
  assert.deepEqual(await readValidationImage("run-1-result.png", directory), png);
  for (const name of ["validation.json", "../validation.json", "other.png"]) {
    assert.equal(await readValidationImage(name, directory), null);
  }
  await writeFile(path.join(directory, "run-1-result.png"), "not a PNG");
  assert.equal(await readValidationImage("run-1-result.png", directory), null);
});

test("named evidence symlinks cannot expose files outside the archive", async (t) => {
  const directory = await archive(t);
  const nested = path.join(directory, "archive");
  const { mkdir } = await import("node:fs/promises");
  await mkdir(nested);
  await symlink(path.join(directory, "validation.json"), path.join(nested, "validation.json"));
  assert.equal(await readValidation(nested), null);
});
