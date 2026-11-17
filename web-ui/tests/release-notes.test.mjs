import assert from "node:assert/strict";
import { test } from "node:test";
import { releaseNoteBlocks, releaseNoteInline } from "../lib/release-notes.ts";

test("release notes keep headings, paragraphs, lists, and code readable", () => {
  const notes = [
    "## Changes", "", "This release updates the console.", "Restart may take a minute.",
    "", "- First fix", "* Second fix", "", "3. First step", "4. Second step", "",
    "```sh", "# not a heading", "emulytics status", "```",
  ].join("\r\n");
  assert.deepEqual(releaseNoteBlocks(notes), [
    { kind: "heading", level: 2, text: "Changes" },
    { kind: "paragraph", text: "This release updates the console. Restart may take a minute." },
    { kind: "list", start: null, items: ["First fix", "Second fix"] },
    { kind: "list", start: 3, items: ["First step", "Second step"] },
    { kind: "code", text: "# not a heading\nemulytics status" },
  ]);
  assert.deepEqual(releaseNoteBlocks(" \n "), []);
});

test("only safe HTTPS Markdown links become links, with HTML and images remaining inert", () => {
  const notes = [
    "<img src=x onerror=alert(1)>",
    "[a fix](https://github.com/drslid/Emulytics/pull/1)",
    "![Badge](https://example.test/pixel.png)",
    "[script](javascript:alert%281%29)",
    "[data](data:text/html,malicious)",
    "[relative](//example.test/path)",
    "[userinfo](https://github.com:private@example.test/)",
    "**important** `emulytics status`",
  ].join(" ");
  const parts = releaseNoteInline(notes);
  assert.deepEqual(parts.filter(part => part.kind === "link"), [
    { kind: "link", text: "a fix", href: "https://github.com/drslid/Emulytics/pull/1" },
  ]);
  assert(parts[0].text.startsWith("<img src=x onerror=alert(1)>"));
  assert(parts.some(part => part.kind === "text" && part.text === "Badge"));
  assert(parts.some(part => part.kind === "strong" && part.text === "important"));
  assert(parts.some(part => part.kind === "code" && part.text === "emulytics status"));
});
