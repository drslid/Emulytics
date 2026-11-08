import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { changeEditorAction, duplicateEditorStep, editorActionLabel, editorArgumentField, editorStepTargets, freshEditorStep, parseEditorSteps, patchEditorArgument, patchEditorTarget } from "../lib/workflow-editor.ts";

const step = { id: "launch", action: "open_app", args: { package_name: "com.android.chrome" }, selectors: [], assert: { type: "package", value: "com.android.chrome" } };

test("legacy workflow actions matching prototype keys remain literal labels without editable argument fields", () => {
  for (const action of ["constructor", "toString", "__proto__", "hasOwnProperty", "valueOf", "legacy_action"]) {
    assert.equal(editorActionLabel(action), action);
    assert.equal(editorArgumentField(action), undefined);
    assert.throws(() => parseEditorSteps(JSON.stringify([{...step,action}])));
  }
  assert.equal(editorActionLabel("open_url"), "Ouvrir une page web");
  assert.deepEqual(editorArgumentField("type_text"), { key: "text", label: "Texte à saisir" });
});

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

test("editing the football search preserves every unrelated executable field", () => {
  const workflow = JSON.parse(readFileSync(new URL("../../workflows/chrome-wikipedia-football.v1.json", import.meta.url), "utf8"));
  const original = workflow.steps.find(item => item.id === "enter-football");
  const changed = patchEditorArgument(original, "text", "tennis");
  assert.deepEqual(changed, {...original, args: {...original.args, text: "tennis"}});
  assert.equal(original.args.text, "football");
  assert.deepEqual(parseEditorSteps(JSON.stringify(workflow.steps)), workflow.steps);
});

test("editing a target preserves all its attributes and fallback selectors", () => {
  const original = {...step, action:"tap", selectors:[{resource_id:"search",text:"Rechercher",focused:true},{content_desc:"Search"}], when:{type:"ui",selector:{text:"Ready"}}};
  const changed = patchEditorTarget(original, 0, {...editorStepTargets(original)[0],text:"Search"});
  assert.deepEqual(changed, {...original,selectors:[{resource_id:"search",text:"Search",focused:true},{content_desc:"Search"}]});
  assert.equal(original.selectors[0].text, "Rechercher");
});

test("tap argument selectors keep precedence without changing alternatives or coordinates", () => {
  const original = {...step,action:"tap",args:{selector:{text:"Old",checked:false},x:1,y:2},selectors:[{resource_id:"fallback"}]};
  assert.deepEqual(editorStepTargets(original), [original.args.selector]);
  assert.deepEqual(patchEditorTarget(original,0,{...original.args.selector,text:"New"}),{...original,args:{...original.args,selector:{text:"New",checked:false}}});
});

test("changing action preserves stable identity, assertions, and advanced controls", () => {
  const original = {...step,when:{type:"ui",selector:{text:"Optional"}},timeout_ms:9000,non_idempotent:true,verify_after_crash:{type:"package",value:"com.android.chrome"}};
  const changed = changeEditorAction(original,"type_text");
  assert.deepEqual(changed,{...original,action:"type_text",args:{text:"",clear:true},selectors:[{class:"android.widget.EditText",focused:true}]});
});

test("new and duplicated steps have distinct stable identities and independent nested data", () => {
  const fresh = freshEditorStep("open_url");
  const duplicate = duplicateEditorStep(step);
  assert.notEqual(fresh.id, step.id);
  assert.notEqual(duplicate.id,step.id);
  const {id,...rest} = duplicate;
  const {id: originalId,...originalRest} = step;
  assert.deepEqual(rest,originalRest);
  duplicate.args.package_name = "changed";
  assert.equal(step.args.package_name,"com.android.chrome");
});

test("system information steps use bounded fields and keep their settings assertion", () => {
  for (const action of ["open_settings", "read_device_info"]) {
    const fresh = freshEditorStep(action);
    assert.deepEqual(fresh.args, action === "open_settings" ? {section:"main"} : {field:"android_version"});
    assert.deepEqual(fresh.assert, {type:"package",value:"com.android.settings"});
    assert.deepEqual(parseEditorSteps(JSON.stringify([fresh])), [fresh]);
    assert.notEqual(editorActionLabel(action), action);
    assert.equal(editorArgumentField(action), undefined, "system commands never become free text");
    const original = {...step, when:{type:"ui",selector:{text:"Ready"}}, timeout_ms:9000};
    assert.deepEqual(changeEditorAction(original, action), {...original,action,args:fresh.args,selectors:[],assert:fresh.assert});
    const custom = {...original,assert:{type:"ui",selector:{text:"Android"}}};
    assert.deepEqual(changeEditorAction(custom, action).assert, custom.assert);
  }
});

test("switching into or out of system actions updates only unchanged default assertions", () => {
  for (const systemAction of ["open_settings", "read_device_info"]) {
    for (const otherAction of ["open_app", "open_url", "ensure_package"]) {
      const system = {...freshEditorStep(systemAction),timeout_ms:9000,when:{type:"ui",selector:{text:"Ready"}}};
      const other = freshEditorStep(otherAction);
      const entered = changeEditorAction(other, systemAction);
      assert.deepEqual(entered.assert, system.assert, `entering ${systemAction} from ${otherAction}`);
      const left = changeEditorAction(system, otherAction);
      assert.deepEqual(left, {...system,action:otherAction,args:other.args,selectors:other.selectors,assert:other.assert}, `leaving ${systemAction} for ${otherAction}`);
      for (const [source, target] of [[system, otherAction], [other, systemAction]]) {
        for (const assertion of [{type:"package",value:"com.example.custom"}, {type:"ui",selector:{text:"Custom"}}, {...source.assert,description:"Custom check"}]) {
          assert.deepEqual(changeEditorAction({...source,assert:assertion}, target).assert, assertion, `custom assertion in ${source.action} → ${target}`);
        }
      }
    }
  }
});
