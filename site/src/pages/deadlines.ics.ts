// iCalendar feed of every day-precision program date. Month-only estimates are left out:
// a calendar entry on the 1st would read as a real date.
import type { APIRoute } from 'astro';
import { allEvents, programs as loadPrograms } from '../lib/content';
import { addDays } from '../lib/dates';
import { SITE_NAME } from '../lib/site';

const escape = (s: string) => s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const ymd = (d: Date) => d.toISOString().slice(0, 10).replace(/-/g, '');

// RFC 5545: lines longer than 75 octets fold onto continuation lines starting with a space.
function fold(line: string): string {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return line;
  const out: string[] = [];
  let current = '';
  let size = 0;
  for (const ch of line) {
    const n = new TextEncoder().encode(ch).length;
    if (size + n > (out.length ? 74 : 75)) {
      out.push(current);
      current = '';
      size = 0;
    }
    current += ch;
    size += n;
  }
  out.push(current);
  return out.join('\r\n ');
}

export const GET: APIRoute = async ({ site }) => {
  const events = allEvents(await loadPrograms()).filter((e) => e.precision === 'day');
  const stamp = `${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}Z`;
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    `PRODID:-//${SITE_NAME}//Program deadlines//EN`,
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    `X-WR-CALNAME:${escape(`${SITE_NAME} deadlines`)}`,
    'X-WR-CALDESC:Open source program dates. Entries marked [est.] follow last year\'s pattern.',
  ];
  for (const e of events) {
    const id = `${e.program.slug}-${e.cycle}-${e.kind}-${e.label}`.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const page = site ? new URL(`programs/${e.program.slug}/`, new URL(import.meta.env.BASE_URL, site)).href : '';
    const description = [
      e.confirmed ? 'Confirmed for this cycle.' : `Estimated${e.note ? ` (${e.note})` : ''}. Confirm on the official site.`,
      e.sourceUrl ? `Source: ${e.sourceUrl}` : `Official site: ${e.program.url}`,
      page ? `Details: ${page}` : '',
    ]
      .filter(Boolean)
      .join('\n');
    lines.push(
      'BEGIN:VEVENT',
      `UID:${id}@ossmap`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${ymd(e.date)}`,
      `DTEND;VALUE=DATE:${ymd(addDays(e.date, 1))}`,
      `SUMMARY:${escape(`${e.confirmed ? '' : '[est.] '}${e.cycle}: ${e.label}`)}`,
      `DESCRIPTION:${escape(description)}`,
      `URL:${e.program.url}`,
      'TRANSP:TRANSPARENT',
      'END:VEVENT',
    );
  }
  lines.push('END:VCALENDAR');
  return new Response(lines.map(fold).join('\r\n') + '\r\n', {
    headers: { 'Content-Type': 'text/calendar; charset=utf-8' },
  });
};
