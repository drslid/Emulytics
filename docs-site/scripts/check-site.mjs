/** Check the actual Pages artifact, including its project-subpath deployment. */
import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const output = fileURLToPath(new URL('../dist/', import.meta.url));
const base = '/Emulytics/';
const origin = 'https://drslid.github.io';
const allowedRoots = new Set(['_astro', 'pagefind', 'brand', 'getting-started', 'guides', 'reference', 'project']);
const allowedRootFiles = new Set(['index.html', '404.html', 'sitemap-index.xml', 'sitemap-0.xml', 'robots.txt', '.nojekyll']);
const files = [];
async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    assert(!entry.isSymbolicLink(), `A public artifact must not contain a symlink: ${target}`);
    if (entry.isDirectory()) await walk(target);
    else files.push(target);
  }
}
await walk(output);
const pages = files.filter(file => file.endsWith('.html'));
assert(pages.length >= 19, 'Expected the landing page and the public guides');
for (const filename of files) {
  const relative = path.relative(output, filename);
  const [first] = relative.split(path.sep);
  assert(relative.includes(path.sep) ? allowedRoots.has(first) : allowedRootFiles.has(first), `Unexpected public artifact: ${relative}`);
  assert(!/(?:^|\/)(?:storage|\.env[^/]*|\.git|node_modules|account\.json|[^/]*-state\.json)(?:\/|$)/i.test(relative), `Private operational artifact: ${relative}`);
}
const errors = [];
for (const filename of pages) {
  const html = await readFile(filename, 'utf8');
  assert(!/\bemk_[A-Za-z0-9_-]{43}\b|otpauth:\/\/|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(html), `Credential material in ${path.relative(output, filename)}`);
  const pageUrl = new URL(base + path.relative(output, filename).split(path.sep).join('/'), origin);
  for (const [, attribute] of html.matchAll(/\b(?:href|src)="([^"]*)"/g)) {
    const raw = attribute.replaceAll('&amp;', '&');
    if (!raw || /^(?:data:|mailto:|tel:|javascript:)/i.test(raw)) continue;
    const url = new URL(raw, pageUrl);
    if (url.origin !== origin) continue;
    if (!url.pathname.startsWith(base)) { errors.push(`${pageUrl.pathname}: missing project base in ${raw}`); continue; }
    // Starlight emits a /404/ canonical URL for GitHub Pages' special 404.html.
    if (filename === path.join(output, '404.html') && url.pathname === base + '404/') continue;
    let decoded;
    try { decoded = decodeURIComponent(url.pathname.slice(base.length)); }
    catch { errors.push(`${pageUrl.pathname}: invalid URL ${raw}`); continue; }
    let target = path.resolve(output, decoded);
    if (target !== path.resolve(output) && !target.startsWith(path.resolve(output) + path.sep)) { errors.push(`Link escapes artifact: ${raw}`); continue; }
    try {
      if ((await stat(target)).isDirectory()) target = path.join(target, 'index.html');
      await stat(target);
    } catch { errors.push(`${pageUrl.pathname}: missing ${raw}`); }
  }
}
assert.deepEqual(errors, [], 'Internal links and assets must resolve in GitHub Pages');
await stat(path.join(output, 'pagefind', 'pagefind.js'));
const sitemap = await readFile(path.join(output, 'sitemap-0.xml'), 'utf8');
assert(sitemap.includes(origin + base), 'Sitemap must include the project base');
console.log(`Checked ${pages.length} HTML pages, internal links, search and the public artifact allowlist.`);
