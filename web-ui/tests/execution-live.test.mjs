import assert from "node:assert/strict";
import { test } from "node:test";
import { isExecutionLive, reconcileExecutionLive, toggleExecutionLive } from "../lib/execution-live.ts";

const initial = { executionId: null, hidden: false };
const phone = (id, status) => ({ id, status });

test("the first actually active phone opens automatically, excluding queued and terminal executions", () => {
  for (const status of ["leased", "running", "recovering", "verifying_state", "waiting_auth"]) {
    assert.equal(isExecutionLive(phone("active", status)), true);
    assert.deepEqual(reconcileExecutionLive([phone("queued", "queued"), phone("done", "succeeded"), phone("active", status)], initial), { executionId: "active", hidden: false });
  }
  for (const status of ["queued", "succeeded", "failed", "cancelled", "needs_review", "unknown"])
    assert.equal(isExecutionLive(phone("inactive", status)), false);
  assert.deepEqual(reconcileExecutionLive([phone("done", "succeeded")], initial), initial);
});

test("selection stays on the chosen active phone and switches only after it finishes", () => {
  const selected = { executionId: "second", hidden: false };
  assert.deepEqual(reconcileExecutionLive([phone("first", "running"), phone("second", "running")], selected), selected);
  assert.deepEqual(reconcileExecutionLive([phone("first", "running"), phone("second", "succeeded")], selected), { executionId: "first", hidden: false });
  assert.deepEqual(reconcileExecutionLive([phone("second", "cancelled")], selected), initial);
});

test("hiding a live screen persists through refresh, device reordering and later active phones", () => {
  const executions = [phone("first", "running"), phone("second", "running")];
  const hidden = toggleExecutionLive(executions, initial, "first");
  assert.deepEqual(hidden, { executionId: "first", hidden: true });
  assert.deepEqual(reconcileExecutionLive([...executions].reverse(), hidden), hidden);
  assert.deepEqual(reconcileExecutionLive([phone("first", "succeeded"), phone("second", "running")], hidden), { executionId: "second", hidden: true });
  const ended = reconcileExecutionLive([], hidden);
  assert.deepEqual(reconcileExecutionLive([phone("third", "running")], ended), { executionId: "third", hidden: true });
});

test("choosing another active phone opens only that screen, and historical rows cannot open a live stream", () => {
  const executions = [phone("first", "running"), phone("second", "running"), phone("history", "succeeded")];
  const hidden = { executionId: "first", hidden: true };
  assert.deepEqual(toggleExecutionLive(executions, hidden, "second"), { executionId: "second", hidden: false });
  assert.deepEqual(toggleExecutionLive(executions, hidden, "first"), { executionId: "first", hidden: false });
  assert.deepEqual(toggleExecutionLive(executions, hidden, "history"), hidden);
  assert.deepEqual(toggleExecutionLive(executions, hidden, "missing"), hidden);
});
