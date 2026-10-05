// All dates are handled as UTC midnights so a build in any time zone renders the same day.
import { TIMEZONE } from './site';

const DAY = 86_400_000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Today's date in the profile's time zone, as a UTC midnight. */
export function today(): Date {
  const ymd = new Intl.DateTimeFormat('en-CA', { timeZone: TIMEZONE }).format(new Date());
  return new Date(`${ymd}T00:00:00Z`);
}

export function utcDay(value: Date | string): Date {
  const d = typeof value === 'string' ? new Date(value) : value;
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
}

export function daysBetween(from: Date, to: Date): number {
  return Math.round((utcDay(to).getTime() - utcDay(from).getTime()) / DAY);
}

export function addDays(d: Date, days: number): Date {
  return new Date(utcDay(d).getTime() + days * DAY);
}

export function iso(d: Date): string {
  return utcDay(d).toISOString().slice(0, 10);
}

export function formatDate(d: Date | string, precision: 'day' | 'month' = 'day', withYear = true): string {
  const x = utcDay(d);
  const month = MONTHS[x.getUTCMonth()];
  if (precision === 'month') return `${month} ${x.getUTCFullYear()}`;
  return withYear ? `${month} ${x.getUTCDate()}, ${x.getUTCFullYear()}` : `${month} ${x.getUTCDate()}`;
}

/** Last day of the month for month-precision dates, so "Feb 2027" counts as upcoming all February. */
export function endOf(d: Date, precision: 'day' | 'month'): Date {
  if (precision === 'day') return utcDay(d);
  const x = utcDay(d);
  return new Date(Date.UTC(x.getUTCFullYear(), x.getUTCMonth() + 1, 0));
}

export function relativeDays(days: number): string {
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days === -1) return 'yesterday';
  if (days > 0) return days < 60 ? `in ${days} days` : `in ${Math.round(days / 30)} months`;
  const ago = -days;
  return ago < 60 ? `${ago} days ago` : `${Math.round(ago / 30)} months ago`;
}

export function ageLabel(isoString: string | null | undefined, now = today()): string {
  if (!isoString) return 'never';
  return relativeDays(daysBetween(now, new Date(isoString)));
}

export function monthKey(d: Date): string {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

export function monthLabel(key: string): string {
  const [y, m] = key.split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}
