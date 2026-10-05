"""Fail the build if any internal link or asset in site/dist points at nothing.

Usage: python scripts/check_links.py [site/dist] [base path, default "/"]
Astro doesn't check links itself; this catches broken guide links, renamed slugs, and base-path
mistakes (GitHub Pages project sites are served from /<repo>/).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

LINK = re.compile(r'(?:href|src)="([^"]+)"')


def target_exists(dist: Path, base: str, path: str) -> bool:
    if not path.startswith(base):
        return False
    rel = unquote(path[len(base) :])
    candidate = dist / rel
    if rel == "" or rel.endswith("/"):
        return (candidate / "index.html").is_file()
    return candidate.is_file() or (candidate / "index.html").is_file()


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "site/dist")
    base = sys.argv[2] if len(sys.argv) > 2 else "/"
    base = "/" + base.strip("/") + "/" if base.strip("/") else "/"
    broken: dict[str, list[str]] = {}
    checked = 0
    for page in sorted(dist.rglob("*.html")):
        rel = page.relative_to(dist).as_posix()
        page_url = base + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
        for raw in LINK.findall(page.read_text(encoding="utf-8")):
            if raw.startswith(("http:", "https:", "mailto:", "data:", "#", "javascript:")):
                continue
            path = urlsplit(urljoin(page_url, raw.replace("&amp;", "&"))).path
            checked += 1
            if not target_exists(dist, base, path):
                broken.setdefault(path, []).append(rel)
    for path, sources in sorted(broken.items()):
        print(f"BROKEN {path}  (from {', '.join(sorted(set(sources))[:3])})")
    print(f"{checked} internal links checked, {len(broken)} broken targets")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
