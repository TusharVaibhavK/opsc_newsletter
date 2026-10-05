// Content collections for everything under ../content/.
// These schemas mirror collectors/content.py (Pydantic); change both together.
import { defineCollection } from 'astro:content';
import { file, glob } from 'astro/loaders';
import { z } from 'astro/zod';
import { parse } from 'yaml';

const slug = z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
const level = z.enum(['low', 'low-medium', 'medium', 'medium-high', 'high']);
const track = z.enum(['backend', 'ml', 'data', 'cloud', 'tooling', 'scientific', 'web', 'systems', 'any']);
const url = z.url();
const date = z.coerce.date();

const cycleEvent = z.object({
  kind: z.enum([
    'apply_open',
    'apply_close',
    'orgs_announced',
    'contribution_start',
    'contribution_end',
    'results',
    'start',
    'end',
    'other',
  ]),
  date,
  precision: z.enum(['day', 'month']).default('day'),
  confirmed: z.boolean().default(false),
  label: z.string().nullish(),
  note: z.string().nullish(),
});

const programs = defineCollection({
  loader: glob({ pattern: '*.yaml', base: '../content/programs' }),
  schema: z.object({
    slug,
    name: z.string(),
    organizer: z.string(),
    url,
    kind: z.enum(['mentorship', 'fellowship', 'internship', 'event']),
    paid: z.boolean().nullable(),
    pay_note: z.string(),
    beginner_friendly: z.boolean(),
    students_only: z.boolean(),
    worldwide: z.boolean().nullable(),
    regions: z.array(z.string()).default([]),
    min_age: z.number().int().nullish(),
    requires_underrepresented: z.boolean().default(false),
    requires_prior_contribution: z.boolean().default(false),
    who_can_apply: z.string(),
    typical_timing: z.string(),
    tracks: z.array(track).default([]),
    tags: z.array(z.string()).default([]),
    fit: level,
    fit_note: z.string(),
    do_now: z.string(),
    watch_urls: z.array(url).default([]),
    cycles: z
      .array(z.object({ name: z.string(), source_url: url.nullish(), events: z.array(cycleEvent).min(1) }))
      .default([]),
  }),
});

const orgs = defineCollection({
  loader: glob({ pattern: '*.yaml', base: '../content/orgs' }),
  schema: z.object({
    slug,
    name: z.string(),
    gsoc_name: z.string().nullish(),
    tracks: z.array(track).min(1),
    track_label: z.string(),
    stack: z.array(z.string()),
    languages: z.array(z.string()),
    competition_estimate: level,
    estimate_note: z.string().nullish(),
    why: z.string(),
    crowded: z.boolean().default(false),
    crowded_reason: z.string().nullish(),
    advice: z.string().nullish(),
    umbrella: z.boolean().default(false),
    programs: z.array(slug).default(['gsoc']),
    github_owners: z.array(z.string()).default([]),
    repos: z
      .array(z.object({ name: z.string(), gfi_labels: z.array(z.string()).default([]), note: z.string().nullish() }))
      .default([]),
    repos_note: z.string().nullish(),
    links: z
      .object({
        homepage: url.nullish(),
        ideas: url.nullish(),
        ideas_next: url.nullish(),
        guide: url.nullish(),
        chat: url.nullish(),
        ai_policy: url.nullish(),
      })
      .default({}),
    notes: z.string().nullish(),
  }),
});

const guides = defineCollection({
  loader: glob({ pattern: '*.md', base: '../content/guides' }),
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    order: z.number().int(),
    section: z.enum(['start', 'contribute', 'apply', 'program']),
    reading_minutes: z.number().int().optional(),
  }),
});

// Single-file YAML lists and objects. The file() loader needs an id per entry, so each parser
// supplies one.
const listOf = (key: string) => (text: string) =>
  ((parse(text) ?? []) as Record<string, unknown>[]).map((entry, i) => ({
    id: String(entry[key] ?? i),
    ...entry,
  }));
const single = (id: string) => (text: string) => [{ id, ...(parse(text) as Record<string, unknown>) }];

const watchlist = defineCollection({
  loader: file('../content/watchlist.yaml', { parser: listOf('org') }),
  schema: z.object({
    org: slug,
    status: z.enum(['not_started', 'exploring', 'contributing', 'primary', 'backup', 'dropped']),
    priority: z.number().int().min(1).max(3),
    role: z.string().nullish(),
    next_action: z.string(),
  }),
});

const profile = defineCollection({
  loader: file('../content/profile.yaml', { parser: single('profile') }),
  schema: z.object({
    github_username: z.string().nullish(),
    languages: z.array(z.string()),
    interests: z.array(track),
    timezone: z.string(),
    target: z.string(),
  }),
});

const playbook = defineCollection({
  loader: file('../content/playbook.yaml', { parser: single('playbook') }),
  schema: z.object({
    phases: z.array(
      z.object({
        slug,
        title: z.string(),
        window: z.string(),
        start: date,
        end: date,
        goal: z.string(),
        actions: z.array(z.string()),
        done_when: z.string(),
      }),
    ),
    checklist: z.array(
      z.object({ id: slug, text: z.string(), due: date.nullish(), done: z.boolean().default(false) }),
    ),
  }),
});

const applications = defineCollection({
  loader: file('../content/applications.yaml', { parser: listOf('__none') }),
  schema: z.object({
    program: slug,
    cycle: z.string(),
    org: slug.nullish(),
    status: z.enum(['interested', 'drafting', 'applied', 'accepted', 'rejected', 'withdrawn']),
    proposal_url: url.nullish(),
    notes: z.string().nullish(),
  }),
});

const glossary = defineCollection({
  loader: file('../content/glossary.yaml', { parser: listOf('slug') }),
  schema: z.object({ term: z.string(), slug, definition: z.string(), see_also: z.array(slug).default([]) }),
});

const flow = defineCollection({
  loader: file('../content/flow.yaml', { parser: listOf('id') }),
  schema: z.object({
    id: slug,
    title: z.string(),
    when: z.string(),
    branch: z.string().nullish(),
    steps: z
      .array(
        z.object({
          id: slug,
          title: z.string(),
          summary: z.string(),
          guide: slug.nullish(),
          link: z.string().nullish(),
          duration: z.string().nullish(),
        }),
      )
      .min(1),
  }),
});

export const collections = { programs, orgs, guides, watchlist, profile, playbook, applications, glossary, flow };
