import rss from '@astrojs/rss';
import type { APIRoute } from 'astro';
import { events } from '../lib/data';
import { SITE_NAME } from '../lib/site';

export const GET: APIRoute = async (context) => {
  const base = new URL(import.meta.env.BASE_URL, context.site);
  const page = (e: (typeof events)[number]) =>
    e.entity_type === 'org' && e.entity_slug
      ? new URL(`orgs/${e.entity_slug}/`, base).href
      : e.entity_type === 'program' && e.entity_slug
        ? new URL(`programs/${e.entity_slug}/`, base).href
        : new URL(`changes/#e-${e.id}`, base).href;
  return rss({
    title: `${SITE_NAME}: changes`,
    description: 'Orgs announced, ideas pages changed, program updates and upcoming deadlines.',
    site: base.href,
    items: events.map((e) => ({
      title: e.title,
      link: page(e),
      pubDate: new Date(e.occurred_at),
      description: e.url ? `Source: ${e.url}` : undefined,
      customData: `<guid isPermaLink="false">${e.id}</guid>`,
    })),
  });
};
