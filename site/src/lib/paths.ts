// Internal links must respect the deploy base (e.g. /<repo>/ on GitHub Pages project sites).
const BASE = import.meta.env.BASE_URL.replace(/\/?$/, '/');

export function href(path: string): string {
  if (/^(?:[a-z]+:|#)/i.test(path)) return path;
  const [beforeHash, hash] = path.split('#', 2);
  const [pathname, query] = beforeHash.split('?', 2);
  let clean = pathname.replace(/^\/+/, '');
  if (clean && !clean.endsWith('/') && !/\.[a-z0-9]+$/i.test(clean)) clean += '/';
  return `${BASE}${clean}${query ? `?${query}` : ''}${hash ? `#${hash}` : ''}`;
}

/** True when `current` (Astro.url.pathname) is `path` or below it. */
export function isActive(current: string, path: string): boolean {
  const target = href(path);
  return target === BASE ? current === BASE : current.startsWith(target);
}
