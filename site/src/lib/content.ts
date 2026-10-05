// Derived views over the content collections: deadlines, phases, labels.
import { getCollection, getEntry, type CollectionEntry } from 'astro:content';
import { addDays, daysBetween, endOf, today } from './dates';

export type Program = CollectionEntry<'programs'>['data'];
export type Org = CollectionEntry<'orgs'>['data'];
export type Level = Program['fit'];
export type EventKind = Program['cycles'][number]['events'][number]['kind'];

export interface ProgramEvent {
  program: Program;
  cycle: string;
  sourceUrl: string | null;
  kind: EventKind;
  label: string;
  date: Date;
  end: Date; // last day this event is "current"; differs from date for month precision
  precision: 'day' | 'month';
  confirmed: boolean;
  note: string | null;
}

const KIND_LABEL: Record<EventKind, string> = {
  apply_open: 'Applications open',
  apply_close: 'Applications close',
  orgs_announced: 'Orgs announced',
  contribution_start: 'Contribution period starts',
  contribution_end: 'Contribution period ends',
  results: 'Results',
  start: 'Starts',
  end: 'Ends',
  other: 'Event',
};
// Events a person must act on before they happen.
export const ACTION_KINDS = new Set<EventKind>(['apply_open', 'apply_close', 'orgs_announced', 'contribution_start']);

export const LEVEL_LABEL: Record<Level, string> = {
  low: 'Low',
  'low-medium': 'Low–Medium',
  medium: 'Medium',
  'medium-high': 'Medium–High',
  high: 'High',
};
export const LEVEL_VALUE: Record<Level, number> = { low: 1, 'low-medium': 1.5, medium: 2, 'medium-high': 2.5, high: 3 };

export const TRACK_LABEL: Record<string, string> = {
  backend: 'Backend',
  ml: 'AI / ML',
  data: 'Data',
  cloud: 'Cloud',
  tooling: 'Dev tooling',
  scientific: 'Scientific',
  web: 'Web',
  systems: 'Systems',
  any: 'Any stack',
};

export const STATUS_LABEL: Record<string, string> = {
  not_started: 'Not started',
  exploring: 'Exploring',
  contributing: 'Contributing',
  primary: 'Primary',
  backup: 'Backup',
  dropped: 'Dropped',
};

export async function programs(): Promise<Program[]> {
  return (await getCollection('programs')).map((e) => e.data).sort((a, b) => a.name.localeCompare(b.name));
}

export async function orgs(): Promise<Org[]> {
  return (await getCollection('orgs')).map((e) => e.data).sort((a, b) => a.name.localeCompare(b.name));
}

export async function profile() {
  const entry = await getEntry('profile', 'profile');
  if (!entry) throw new Error('content/profile.yaml is missing');
  return entry.data;
}

export async function playbook() {
  const entry = await getEntry('playbook', 'playbook');
  if (!entry) throw new Error('content/playbook.yaml is missing');
  return entry.data;
}

export async function watchlist() {
  return (await getCollection('watchlist')).map((e) => e.data).sort((a, b) => a.priority - b.priority);
}

export function eventLabel(kind: EventKind, label?: string | null): string {
  return label || KIND_LABEL[kind];
}

export function allEvents(list: Program[]): ProgramEvent[] {
  return list
    .flatMap((program) =>
      program.cycles.flatMap((cycle) =>
        cycle.events.map((e) => ({
          program,
          cycle: cycle.name,
          sourceUrl: cycle.source_url ?? null,
          kind: e.kind,
          label: eventLabel(e.kind, e.label),
          date: e.date,
          end: endOf(e.date, e.precision),
          precision: e.precision,
          confirmed: e.confirmed,
          note: e.note ?? null,
        })),
      ),
    )
    .sort((a, b) => a.date.getTime() - b.date.getTime());
}

/** Events that haven't passed yet (month-precision events stay current for their whole month). */
export function upcoming(list: Program[], withinDays?: number, now = today()): ProgramEvent[] {
  const horizon = withinDays === undefined ? null : addDays(now, withinDays);
  return allEvents(list).filter((e) => e.end >= now && (horizon === null || e.date <= horizon));
}

export function nextEvent(program: Program, now = today()): ProgramEvent | undefined {
  const future = upcoming([program], undefined, now);
  return future.find((e) => ACTION_KINDS.has(e.kind)) ?? future[0];
}

export async function currentPhase(now = today()) {
  const book = await playbook();
  const phases = book.phases;
  const current = phases.find((p) => p.start <= now && now <= p.end);
  if (current) return { phase: current, state: 'current' as const };
  const next = phases.find((p) => p.start > now);
  if (next) return { phase: next, state: 'upcoming' as const, inDays: daysBetween(now, next.start) };
  return { phase: phases[phases.length - 1], state: 'past' as const };
}
