import assert from "node:assert/strict";
import { test } from "node:test";
import {
  readScreenFrame,
  screenFrameAge,
  isScreenFrameFresh,
} from "../lib/screen-frame.ts";
function headers(changes = {}) {
  return new Headers({
    "X-Screen-Captured-At": "2026-11-06T17:30:00Z",
    "X-Screen-Age": "0.4",
    "X-Screen-Frame-Id": "b5bb6746-9aa5-45af-aa63-22f5946b1e5e",
    ...changes,
  });
}
test("a stopped screen becomes visibly stale even without another server response", () => {
  const frame = readScreenFrame(headers(), 1000);
  assert.ok(frame);
  assert.equal(isScreenFrameFresh(frame, 1000), true);
  assert.equal(isScreenFrameFresh(frame, 3500), true);
  assert.equal(isScreenFrameFresh(frame, 3700), false);
  assert.equal(isScreenFrameFresh(null, 2000), false);
  assert.equal(screenFrameAge(frame, 2000), 1.4);
});
test("freshness uses measured server age and elapsed monotonic time independently of browser clock", () => {
  const frame = readScreenFrame(
    headers({ "X-Screen-Captured-At": "2099-01-01T01:00:00Z" }),
    80000,
  );
  assert.ok(frame);
  assert.equal(isScreenFrameFresh(frame, 80500), true);
  assert.equal(isScreenFrameFresh(frame, 84000), false);
  assert.equal(
    isScreenFrameFresh(
      readScreenFrame(headers({ "X-Screen-Age": "3.1" }), 1000),
      1000,
    ),
    false,
  );
});
test("unconfirmed or malformed screen metadata never produces a live frame", () => {
  for (const changes of [
    { "X-Screen-Age": "" },
    { "X-Screen-Age": "NaN" },
    { "X-Screen-Age": "-1" },
    { "X-Screen-Captured-At": "invalid" },
    { "X-Screen-Frame-Id": "../../private" },
    { "X-Screen-Frame-Id": "" },
  ])
    assert.equal(readScreenFrame(headers(changes), 1000), null);
  const missing = headers();
  missing.delete("X-Screen-Age");
  assert.equal(readScreenFrame(missing, 1000), null);
});
