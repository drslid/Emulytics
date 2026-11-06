import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRunDraft, draftKey } from "../lib/run-draft.ts";
const request = { workflow_id: "wikipedia", workflow_version: 1, device_ids: ["phone-1"], max_concurrency: 1, parameters: {}, idempotency_key: "295d6d4d-8627-40bc-9c8e-c02e8d550b12" };
test("pending request preserves the exact batch and idempotency key", () => {
  assert.deepEqual(parseRunDraft(JSON.parse(JSON.stringify(request))), request);
  assert.notEqual(draftKey("user-1"), draftKey("user-2"));
});
test("browser draft cannot contain credentials, arbitrary parameters, or invalid batches", () => {
  for (const changed of [null, [], {}, { ...request, password: "private" }, { ...request, parameters: { secret: "private" } }, { ...request, device_ids: ["phone-1", "phone-1"] }, { ...request, max_concurrency: 2 }, { ...request, idempotency_key: "" }]) assert.equal(parseRunDraft(changed), null);
});
