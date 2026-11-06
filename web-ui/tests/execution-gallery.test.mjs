import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildExecutionGallery,
  captureUrl,
  initialGallerySelection,
} from "../lib/execution-gallery.ts";

const executionId = "b5bb6746-9aa5-45af-aa63-22f5946b1e5e";
function execution(status, evidence = {}) {
  return { id: executionId, status, evidence };
}

test("gallery follows the immutable workflow order while evidence arrives in a different order", () => {
  const rows = buildExecutionGallery(execution("running", { steps: [
    { step_id: "finish", assertion_passed: true },
    { step_id: "open-app", assertion_passed: true },
  ] }), [
    { id: "open-app", action: "open_app", name: "Open browser" },
    { id: "find_result", action: "tap" },
    { id: "finish", action: "screenshot" },
  ]);

  assert.deepEqual(rows.map(({ id, label, state }) => ({ id, label, state })), [
    { id: "open-app", label: "Open browser", state: "succeeded" },
    { id: "find_result", label: "find result", state: "pending" },
    { id: "finish", label: "finish", state: "succeeded" },
  ]);
});

test("failed and skipped evidence take precedence over a passed assertion", () => {
  const rows = buildExecutionGallery(execution("failed", {
    failed_step: "broken",
    steps: [
      { step_id: "broken", assertion_passed: true, skipped: true },
      { step_id: "conditional", assertion_passed: true, skipped: true },
      { step_id: "confirmed", assertion_passed: true },
      { step_id: "unconfirmed", screenshot: "/private/capture.png" },
      { step_id: "wrong-types", assertion_passed: "true", skipped: "true" },
    ],
  }));

  assert.deepEqual(rows.map(({ state }) => state), [
    "failed", "skipped", "succeeded", "unconfirmed", "unconfirmed",
  ]);
});

test("missing evidence stays pending only while the execution can still run", () => {
  const steps = [{ id: "next", action: "tap" }];
  for (const status of ["queued", "leased", "running", "recovering", "verifying_state", "waiting_auth"])
    assert.equal(buildExecutionGallery(execution(status), steps)[0].state, "pending", status);
  for (const status of ["failed", "cancelled", "succeeded", "needs_review", "unknown"])
    assert.equal(buildExecutionGallery(execution(status), steps)[0].state, "unconfirmed", status);
});

test("only workflow steps known to follow the explicit failure are marked not run", () => {
  const rows = buildExecutionGallery(execution("failed", { failed_step: "broken" }), [
    { id: "before", action: "tap" },
    { id: "broken", action: "tap" },
    { id: "after", action: "screenshot" },
  ]);

  assert.deepEqual(rows.map(({ id, state }) => ({ id, state })), [
    { id: "before", state: "unconfirmed" },
    { id: "broken", state: "failed" },
    { id: "after", state: "not-run" },
  ]);
});

test("cancellation after an Android command leaves its uncaptured result unconfirmed", () => {
  const rows = buildExecutionGallery(execution("cancelled", { steps: [
    { step_id: "setup", assertion_passed: true },
  ] }), [
    { id: "setup", action: "tap" },
    { id: "open-app", action: "open_app" },
    { id: "later", action: "screenshot" },
  ]);

  assert.deepEqual(rows.map(({ state }) => state), ["succeeded", "unconfirmed", "unconfirmed"]);
});

test("without a workflow snapshot the gallery shows only recorded steps and the explicit failed step", () => {
  const rows = buildExecutionGallery(execution("failed", {
    steps: [
      null,
      { step_id: 42, assertion_passed: true },
      { step_id: "first", assertion_passed: true },
      { step_id: "first", assertion_passed: true },
      { step_id: "second", skipped: true },
    ],
    failed_step: "failed-last",
  }));

  assert.deepEqual(rows.map(({ id, state }) => ({ id, state })), [
    { id: "first", state: "succeeded" },
    { id: "second", state: "skipped" },
    { id: "failed-last", state: "failed" },
  ]);
  assert.deepEqual(buildExecutionGallery(execution("running")), []);
  assert.deepEqual(buildExecutionGallery(execution("failed", { steps: "invalid", failed_step: 42 })), []);
});

test("captures use only validated private routes and never stored file paths", () => {
  const rows = buildExecutionGallery(execution("succeeded", { steps: [
    { step_id: "capture:one", screenshot: "/srv/private/other-execution/capture.png" },
    { step_id: "no-file", screenshot: false },
  ] }));
  const expected = `/api/control/console/executions/${executionId}/captures/capture%3Aone`;

  assert.equal(rows[0].captureUrl, expected);
  assert.equal(rows[1].captureUrl, null);
  assert.equal(captureUrl(executionId, "capture:one"), expected);
  assert.ok(captureUrl(executionId, "a".repeat(128)));
  for (const stepId of ["", "../capture", "x/y", "a?x=1", "a".repeat(129)])
    assert.equal(captureUrl(executionId, stepId), null, stepId);
  for (const id of ["../private", "bad", `${executionId}/other`])
    assert.equal(captureUrl(id, "safe"), null, id);
});

test("capture metadata accepts only valid dates and finite nonnegative durations", () => {
  const rows = buildExecutionGallery(execution("succeeded", { steps: [
    { step_id: "valid", captured_at: "2026-11-06T18:00:00Z", duration_ms: 1250 },
    { step_id: "zero", captured_at: "not-a-date", duration_ms: 0 },
    { step_id: "wrong", captured_at: 123, duration_ms: "1250" },
    { step_id: "negative", duration_ms: -1 },
    { step_id: "infinite", duration_ms: Infinity },
    { step_id: "non-iso", captured_at: "November 6, 2026" },
  ] }));

  assert.equal(rows[0].capturedAt, "2026-11-06T18:00:00Z");
  assert.equal(rows[0].durationMs, 1250);
  assert.equal(rows[1].capturedAt, null);
  assert.equal(rows[1].durationMs, 0);
  for (const row of rows.slice(2)) {
    assert.equal(row.capturedAt, null);
    assert.equal(row.durationMs, null);
  }
});

test("selection survives a refresh and falls back to the first available capture", () => {
  const rows = buildExecutionGallery(execution("running", { steps: [
    { step_id: "waiting" },
    { step_id: "first-capture", screenshot: "/private/one.png" },
    { step_id: "later-capture", screenshot: "/private/two.png" },
  ] }));

  assert.equal(initialGallerySelection(rows, "waiting"), "waiting");
  assert.equal(initialGallerySelection(rows, "later-capture"), "later-capture");
  assert.equal(initialGallerySelection(rows, "removed"), "first-capture");
  assert.equal(initialGallerySelection(rows), "first-capture");
  assert.equal(initialGallerySelection(rows.slice(0, 1)), "waiting");
  assert.equal(initialGallerySelection([]), null);
});
