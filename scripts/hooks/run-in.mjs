#!/usr/bin/env node
/* global process, console */

// Runs one of a package's own tools on the staged files that belong to it:
//
//   node scripts/hooks/run-in.mjs <package> <tool> [args...] -- <files...>
//
// The tool runs from inside the package, so it picks up that package's config
// (ESLint looks for its config from the working directory, not from the file).
// Only Node built-ins: the hook must work before anything else is installed.

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const separator = process.argv.indexOf('--');
const [pkg, tool, ...args] = process.argv.slice(2, separator === -1 ? undefined : separator);
const files = separator === -1 ? [] : process.argv.slice(separator + 1);

if (!pkg || !tool) {
  console.error('Usage: node scripts/hooks/run-in.mjs <package> <tool> [args...] -- <files...>');
  process.exit(2);
}
if (files.length === 0) process.exit(0);

const cwd = path.join(root, pkg);
const manifest = path.join(cwd, 'node_modules', tool, 'package.json');
if (!existsSync(manifest)) {
  console.error(
    `${pkg}/${tool} is not installed, so the staged ${pkg} files cannot be checked.\n` +
      `Install the dependencies first: npm --prefix ${pkg} ci`,
  );
  process.exit(1);
}

// The tool's own entry point is started with this Node, not through a shell:
// staged paths such as `src/app/(auth)/page.tsx` must reach it unquoted.
const { bin } = JSON.parse(readFileSync(manifest, 'utf8'));
const entry = path.join(path.dirname(manifest), typeof bin === 'string' ? bin : bin[tool]);

// Files arrive relative to the repository root or as absolute paths.
const relative = files.map((file) => path.relative(cwd, path.resolve(root, file)));
const result = spawnSync(process.execPath, [entry, ...args, ...relative], {
  cwd,
  stdio: 'inherit',
});
process.exit(result.status ?? 1);
