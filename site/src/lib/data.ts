// Typed access to the JSON the collectors export into src/data/. Every file always exists
// (possibly empty), so pages render even before the first scheduled run.
import activityRaw from '../data/activity.json';
import eventsRaw from '../data/events.json';
import gsocRaw from '../data/gsoc.json';
import ideasRaw from '../data/ideas.json';
import issuesRaw from '../data/issues.json';
import jobsRaw from '../data/jobs.json';
import metaRaw from '../data/meta.json';
import metricsRaw from '../data/metrics.json';
import pagesRaw from '../data/pages.json';
import projectsRaw from '../data/projects.json';
import scoresRaw from '../data/scores.json';

export type Band = 'low' | 'medium' | 'high' | 'unknown';

export interface Links {
  homepage: string | null;
  ideas: string | null;
  guide: string | null;
  chat: string | null;
  ai_policy: string | null;
  ideas_next: string | null;
}

export interface GsocOrg {
  slug: string;
  name: string;
  curated: boolean;
  category: string | null;
  description: string | null;
  technologies: string[];
  topics: string[];
  links: Links;
  years: Record<string, number>;
  streak: number;
  first_year: number | null;
  in_latest: boolean;
  total_projects: number;
}

export interface RepoMetrics {
  name: string;
  gfi_labels: string[];
  date: string | null;
  stars: number | null;
  issues_enabled: boolean | null;
  open_gfi_count: number | null;
  open_gfi_unclaimed: number | null;
  gfi_median_claim_hours: number | null;
  new_contributors_30d: number | null;
  open_newcomer_prs: number | null;
  median_first_response_hours: number | null;
  unanswered_pr_share: number | null;
  prs_sampled: number | null;
}

export interface WeeklyMetrics {
  week: string;
  new_contributors_30d: number | null;
  open_gfi_count: number | null;
  open_newcomer_prs: number | null;
  gfi_median_claim_hours: number | null;
  median_first_response_hours: number | null;
  stars: number | null;
}

export interface OrgMetrics {
  repos: RepoMetrics[];
  weekly: WeeklyMetrics[];
  last_refreshed: string | null;
  history_days: number;
}

export interface OrgScore {
  bands: { week: string; band: Band }[];
  band?: Band;
  confidence?: number;
  inputs_present?: string[];
  fit?: number;
  fit_parts?: Record<string, number>;
}

export interface Issue {
  repo: string;
  number: number;
  title: string;
  url: string;
  created_at: string;
  age_days: number;
  comments: number;
  labels: string[];
  status: 'unclaimed' | 'discussed' | 'assigned' | 'pr-linked';
}

export interface ActivityItem {
  url: string;
  repo: string;
  org: string | null;
  title: string;
  state: 'open' | 'merged' | 'closed';
  opened_at: string;
  merged_at: string | null;
}

export interface FeedEvent {
  id: string;
  kind: string;
  title: string;
  url: string | null;
  entity_type: string | null;
  entity_slug: string | null;
  occurred_at: string;
  detail: Record<string, unknown>;
}

export interface IdeasInfo {
  url?: string;
  checked_at?: string | null;
  changed_at?: string | null;
  status?: number | null;
  note?: string | null;
  count?: number;
  titles?: string[];
  added_this_week?: string[];
  removed_this_week?: string[];
  next?: { url: string; published: boolean; checked_at: string | null };
}

export interface WatchedPage {
  url: string;
  kind: string;
  entity_type: string;
  entity_slug: string;
  last_status: number | null;
  last_checked_at: string | null;
  last_changed_at: string | null;
  consecutive_errors: number;
  needs_confirmation: boolean;
  note: string | null;
}

export interface JobRunInfo {
  job: string;
  started_at: string;
  finished_at: string | null;
  status: 'ok' | 'error' | 'skipped' | 'running';
  api_calls: number;
  summary: string | null;
}

export const meta = metaRaw as unknown as {
  generated_at: string;
  today: string;
  data_mode: 'history' | 'postgres';
  latest_gsoc_year: number | null;
  last_ok: Record<string, string | null>;
  counts: Record<string, number>;
};
export const gsoc = gsocRaw as unknown as { latest_year: number | null; years: number[]; orgs: GsocOrg[] };
export const projects = projectsRaw as unknown as Record<string, { year: number; title: string; url: string | null }[]>;
export const metrics = metricsRaw as unknown as { orgs: Record<string, OrgMetrics> };
export const scores = scoresRaw as unknown as {
  week: string;
  weights: Record<string, number>;
  orgs: Record<string, OrgScore>;
};
export const issues = issuesRaw as unknown as {
  date: string;
  per_org: number;
  orgs: Record<string, { total_open: number; open_to_newcomers: number; shown: Issue[] }>;
};
export const activity = activityRaw as unknown as {
  username: string | null;
  totals: { prs: number; merged: number; open: number; reviews: number };
  streak_weeks: number;
  by_org: Record<string, { merged: number; open: number; closed: number; reviews: number }>;
  weekly: { week: string; merged: number; opened: number; reviews: number }[];
  prs: ActivityItem[];
  reviews: ActivityItem[];
  log: { date: string; kind: string; org: string | null; note: string; url: string | null }[];
};
export const events = eventsRaw as unknown as FeedEvent[];
export const ideas = ideasRaw as unknown as Record<string, IdeasInfo>;
export const pages = pagesRaw as unknown as WatchedPage[];
export const jobs = jobsRaw as unknown as JobRunInfo[];

const gsocBySlug = new Map(gsoc.orgs.map((o) => [o.slug, o]));
export const gsocOrg = (slug: string): GsocOrg | undefined => gsocBySlug.get(slug);

/** Latest GSoC years, newest first, with project counts (0 when the org sat a year out). */
export function recentYears(org: GsocOrg | undefined, n = 3): { year: number; count: number }[] {
  const latest = gsoc.latest_year;
  if (!latest) return [];
  return Array.from({ length: n }, (_, i) => latest - i).map((year) => ({
    year,
    count: org?.years[String(year)] ?? 0,
  }));
}

export function orgTotals(slug: string) {
  const m = metrics.orgs[slug];
  if (!m) return null;
  const sum = (k: keyof RepoMetrics) => {
    const vals = m.repos.map((r) => r[k]).filter((v): v is number => typeof v === 'number');
    return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
  };
  const median = (k: keyof RepoMetrics) => {
    const vals = m.repos
      .map((r) => r[k])
      .filter((v): v is number => typeof v === 'number')
      .sort((a, b) => a - b);
    if (!vals.length) return null;
    const mid = Math.floor(vals.length / 2);
    return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
  };
  return {
    openGfi: sum('open_gfi_count'),
    unclaimed: sum('open_gfi_unclaimed'),
    newContributors: sum('new_contributors_30d'),
    newcomerBacklog: sum('open_newcomer_prs'),
    claimHours: median('gfi_median_claim_hours'),
    responseHours: median('median_first_response_hours'),
    stars: Math.max(0, ...m.repos.map((r) => r.stars ?? 0)) || null,
    lastRefreshed: m.last_refreshed,
    historyDays: m.history_days,
  };
}

export function lastRun(job: string): JobRunInfo | undefined {
  return jobs.find((j) => j.job === job);
}
