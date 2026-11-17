import assert from "node:assert/strict";
import { test } from "node:test";
import { canAuthorRun, runSourceId, saveRunRecipe } from "../lib/run-authoring.ts";

test("natural cards are replayed exactly with the same draft-creation id", async () => {
  const state = {};
  const body = { name: "Android", instructions: "Read Android version", steps: [], recovery_budget: 0,
    cards: [{ id: "card-1", instruction: "Read Android version", verification: "Version is recorded" }] };
  const sent = [];
  const request = async (endpoint, payload) => {
    sent.push([endpoint, structuredClone(payload)]);
    if (sent.length === 1) throw new Error("Response lost");
    return { id: "recipe", revision: 1 };
  };
  await assert.rejects(saveRunRecipe(body, state, request), /Response lost/);
  await saveRunRecipe(body, state, request);
  assert.deepEqual(sent[0], sent[1]);
  assert.deepEqual(sent[1][1].cards, body.cards);
});

test("creating a run requires authoring, publishing and execution permissions", () => {
  const required = ["runs.execute", "workflows.write", "workflows.publish"];
  assert.equal(canAuthorRun(required), true);
  assert.equal(canAuthorRun(required.slice(0, 2)), false);
  assert.equal(canAuthorRun(["runs.execute"]), false);
  assert.equal(runSourceId("295d6d4d-8627-40bc-9c8e-c02e8d550b12"), "295d6d4d-8627-40bc-9c8e-c02e8d550b12");
  assert.equal(runSourceId("../../runs"), undefined);
  assert.equal(runSourceId(["one", "two"]), undefined);
});

test("retrying a lost create response updates the original recipe when the editor changed", async () => {
  const state = {};
  const body = { name: "First draft", instructions: "", steps: [{ id: "s1", action: "open_app" }], recovery_budget: 0 };
  const calls = [];
  const request = async (path, payload, method) => {
    calls.push({ path, payload, method });
    if (calls.length === 1) throw new Error("Response lost");
    return { id: calls[0].payload.request_id, revision: method === "PATCH" ? 2 : 1 };
  };
  await assert.rejects(saveRunRecipe(body, state, request), /Response lost/);
  const changed = { ...body, name: "Current draft" };
  const saved = await saveRunRecipe(changed, state, request);
  assert.deepEqual(calls[0].payload, calls[1].payload);
  assert.deepEqual(calls[2], { path: `console/recipes/${saved.id}`, payload: { ...changed, revision: 1, accept_replay: true }, method: "PATCH" });
  assert.equal(await saveRunRecipe(changed, state, request), saved);
  assert.equal(calls.length, 3);
});

test("retrying a lost update resolves the exact revision before saving newer edits", async () => {
  const original = { name: "Original", instructions: "", steps: [{ id: "s1", action: "open_app" }], recovery_budget: 0 };
  const state = { saved: { id: "draft", revision: 1 }, snapshot: JSON.stringify(original) };
  const calls = [];
  const request = async (path, payload, method) => {
    calls.push({ path, payload, method });
    if (calls.length === 1) throw new Error("Response lost");
    return { id: "draft", revision: payload.revision + 1 };
  };
  await assert.rejects(saveRunRecipe({ ...original, name: "Second" }, state, request), /Response lost/);
  await saveRunRecipe({ ...original, name: "Third" }, state, request);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(calls[2].payload.name, "Third");
  assert.equal(calls[2].payload.revision, 2);
  assert.equal(calls[2].payload.accept_replay, true);
  assert.equal(state.saved.revision, 3);
});

test("validation failures unlock both create and update for corrections", async () => {
  const state = {};
  const original = { name: "Original", instructions: "", steps: [{ id: "s1", action: "open_app" }], recovery_budget: 0 };
  const rejected = Object.assign(new Error("Invalid step"), { status: 422 });
  await assert.rejects(saveRunRecipe(original, state, async () => { throw rejected; }), /Invalid step/);
  assert.equal(state.initial, undefined);
  const corrected = { ...original, name: "Corrected" };
  await saveRunRecipe(corrected, state, async (_path, payload) => {
    assert.equal(payload.name, corrected.name);
    return { id: "draft", revision: 1 };
  });
  await assert.rejects(saveRunRecipe(original, state, async () => { throw rejected; }), /Invalid step/);
  assert.equal(state.pendingUpdate, undefined);
  await saveRunRecipe({ ...original, name: "Updated" }, state, async (_path, payload) => {
    assert.equal(payload.name, "Updated");
    assert.equal(payload.revision, 1);
    return { id: "draft", revision: 2 };
  });
});
