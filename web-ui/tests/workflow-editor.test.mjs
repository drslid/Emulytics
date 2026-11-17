import assert from "node:assert/strict";
import { test } from "node:test";
import { containsApplicationIdentifier, workflowStepPreview } from "../lib/workflow-editor.ts";

const app = "com.linkedin.android";
const opening = { id: "open", action: "open_app", args: { package_name: app }, assert: { type: "package", value: app } };

test("a prepared app action and its foreground check show a friendly app name", () => {
  const summary = workflowStepPreview(opening, { [app]: "LinkedIn" });
  assert.equal(summary.label, "Ouvrir une application");
  assert.equal(summary.app, "LinkedIn");
  assert.deepEqual(summary.checks, [{ label: "Application au premier plan", app: "LinkedIn" }]);
  assert.ok(!JSON.stringify(summary).includes(app));
});

test("a prepared app with no usable display name never shows a package identifier", () => {
  for (const names of [{}, { [app]: app }, { [app]: `LinkedIn (${app})` }, { [app]: " " }]) {
    const summary = workflowStepPreview(opening, names);
    assert.equal(summary.app, undefined);
    assert.deepEqual(summary.checks, [{ label: "Application au premier plan", app: undefined }]);
    assert.ok(!JSON.stringify(summary).includes(app));
  }
  assert.ok(containsApplicationIdentifier(`Ouvrir ${app}`));
  assert.ok(!containsApplicationIdentifier("Lire la version Android 14.0."));
});

test("prepared settings and nested checks never expose selectors, paths, or technical identifiers", () => {
  const summary = workflowStepPreview({
    id: app,
    action: "open_settings",
    args: { section: "about" },
    assert: { type: "all", checks: [
      { type: "package", value: "com.android.settings" },
      { type: "url", host: "fr.wikipedia.org", path_contains: "/wiki/Android" },
      { type: "ui", selector: { resource_id: app } },
    ] },
  });
  assert.equal(summary.section, "À propos du téléphone");
  assert.deepEqual(summary.checks, [
    { label: "Application au premier plan", app: "Paramètres du téléphone" },
    { label: "Domaine de la page" },
    { label: "Élément visible" },
  ]);
  assert.equal(workflowStepPreview({ ...opening, action: app }).label, "Action Android");
});
