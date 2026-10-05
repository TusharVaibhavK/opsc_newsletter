// @ts-check
import { defineConfig } from 'astro/config';

// GitHub Pages project sites live under /<repo>/; the deploy workflow sets SITE_BASE for that.
const base = process.env.SITE_BASE || '/';

export default defineConfig({
  site: process.env.SITE_URL || 'https://localhost',
  base,
  output: 'static',
  trailingSlash: 'always',
  // Astro 7 defaults to JSX-style whitespace stripping, which can glue inline words together
  // in prose. HTML-aware compression keeps text spacing exactly as written.
  compressHTML: true,
  build: { format: 'directory' },
  vite: {
    server: { fs: { allow: ['..'] } },
  },
});
