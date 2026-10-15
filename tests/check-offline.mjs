#!/usr/bin/env node
// Checks that every local script and stylesheet the pages load is in sw.js SHELL, so the installed
// app works offline, and that every SHELL entry exists. Exit 1 if not. Node 18+, no dependencies.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PAGES = ['index.html', 'prioritizer/index.html'];

// Evaluate sw.js with stub worker globals to read SHELL.
const sw = fs.readFileSync(path.join(root, 'sw.js'), 'utf8');
const ctx = {self: {addEventListener() {}}, caches: {}, location: {origin: 'https://x'}, fetch() {}, Request: class {}, Response: {}, URL};
vm.runInNewContext(sw + '\nthis.__SHELL = SHELL;', ctx);
const shell = new Set(ctx.__SHELL.map(u => path.normalize(u.replace(/^\.\//, '')).replace(/\/?$/, m => m)));

const errors = [];
for (const u of ctx.__SHELL) {
  const f = path.join(root, u.endsWith('/') ? u + 'index.html' : u);
  if (!fs.existsSync(f)) errors.push(`sw.js lists ${u}, which does not exist.`);
}
for (const page of PAGES) {
  const html = fs.readFileSync(path.join(root, page), 'utf8');
  const refs = [...html.matchAll(/<(?:script[^>]*\ssrc|link[^>]*\shref)="([^"]+)"/g)].map(m => m[1]).filter(u => !/^(https?:)?\/\//.test(u));
  for (const ref of refs) {
    const rel = path.normalize(path.join(path.dirname(page), ref));
    if (!fs.existsSync(path.join(root, rel))) errors.push(`${page} loads ${ref}, which does not exist.`);
    else if (!shell.has(rel)) errors.push(`${page} loads ${ref}; add ./${rel} to SHELL in sw.js.`);
  }
}

if (errors.length) { console.error('Offline cache list is out of date:\n- ' + errors.join('\n- ')); process.exit(1); }
console.log(`offline ok: ${ctx.__SHELL.length} files cached, every page asset covered`);
