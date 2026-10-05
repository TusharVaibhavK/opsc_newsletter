// Candid notes about orgs, from the gitignored content/notes.private.yaml. Only `astro dev`
// reads them: in a production build import.meta.env.DEV is false, so this returns nothing and
// the notes can never reach the published HTML. CI double-checks with scripts/check_privacy.py.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

export function privateNote(slug: string): string | null {
  if (!import.meta.env.DEV) return null;
  const file = resolve(process.cwd(), '../content/notes.private.yaml');
  if (!existsSync(file)) return null;
  const notes = parse(readFileSync(file, 'utf8')) as Record<string, unknown> | null;
  const note = notes?.[slug];
  return typeof note === 'string' ? note : null;
}
