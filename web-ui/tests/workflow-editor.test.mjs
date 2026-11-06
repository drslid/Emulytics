import assert from "node:assert/strict";
import { test } from "node:test";
import { parseEditorSteps } from "../lib/workflow-editor.ts";

const step = { id: "launch", action: "open_app", args: { package_name: "com.android.chrome" }, selectors: [], assert: { type: "package", value: "com.android.chrome" } };

test("malformed advanced JSON cannot crash the visual workflow editor", () => {
  for (const value of [null, {}, [], [null], [1], ["step"], [{...step,id:null}], [{...step,action:"unknown"}], [{...step,args:[]}], [{...step,selectors:{}}], [{...step,selectors:[null]}], [{...step,assert:null}], [step,step], Array.from({length:15},(_,index)=>({...step,id:`step-${index}`}))]) {
    assert.throws(() => parseEditorSteps(JSON.stringify(value)), JSON.stringify(value));
  }
  assert.throws(() => parseEditorSteps("[invalid JSON"));
});

test("valid advanced edits preserve conditions and crash checks when returning to visual mode", () => {
  const detailed = {...step, when:{type:"ui",selector:{text:"Continue"}}, non_idempotent:true, verify_after_crash:{type:"ui",selector:{text:"Done"}}, recovery_budget:0};
  assert.deepEqual(parseEditorSteps(JSON.stringify([detailed])),[detailed]);
  assert.equal(parseEditorSteps(JSON.stringify(Array.from({length:14},(_,index)=>({...step,id:`step-${index}`})))).length,14);
});
