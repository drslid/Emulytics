import assert from "node:assert/strict";
import { test } from "node:test";
import { parseScheduleDraft, scheduleDraftKey } from "../lib/schedule-draft.ts";

const request = { request_id: "295d6d4d-8627-40bc-9c8e-c02e8d550b12", name: "Contrôle du matin",
  workflow_id: "chrome-wikipedia-football", workflow_version: 2, device_ids: ["phone-1", "phone-2"],
  max_concurrency: 2, cron: "0 9 * * 1-5", timezone: "Europe/Paris", enabled: true };

test("a pending schedule keeps the exact accepted request across closing or reloading the editor", () => {
  const stored = JSON.stringify(request);
  assert.deepEqual(parseScheduleDraft(JSON.parse(stored)), request);
  assert.notEqual(scheduleDraftKey("user-1"), scheduleDraftKey("user-2"));
});

test("pending schedules reject credentials, extra fields, invalid batches and non-creation payloads", () => {
  for (const changed of [null, [], {}, { ...request, access_token: "secret" }, { ...request, enabled: false },
    { ...request, device_ids: ["phone-1", "phone-1"] }, { ...request, device_ids: [] },
    { ...request, max_concurrency: 3 }, { ...request, max_concurrency: 1.5 },
    { ...request, request_id: "not-a-uuid" }, { ...request, workflow_version: 0 },
    { ...request, name: " " }, { ...request, cron: " " }, { ...request, timezone: "" },
    { ...request, name: "a".repeat(121) }, { ...request, cron: "a".repeat(121) }, { ...request, timezone: "a".repeat(101) }])
    assert.equal(parseScheduleDraft(changed), null);
});
