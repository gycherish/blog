#!/usr/bin/env python3
"""Shared helpers for the Obsidian -> blog / WeChat tooling.

Both sync.py (blog) and wechat.py (WeChat) import this so the link/slug/URL
rules live in exactly one place.
"""
import os
import re
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

WIKI_IMG = re.compile(r"!\[\[([^\]\|]+?)(?:\|([^\]]*))?\]\]")
# [[doc]], [[doc#heading]], [[doc|alias]], [[doc#heading|alias]]  (not ![[...]])
WIKI_LINK = re.compile(r"(?<!!)\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|([^\]]+))?\]\]")
STD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
POST_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def load_dotenv(path):
    """Load KEY=VALUE lines from a .env file into os.environ (no override)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def split_csv(values):
    out = []
    for v in values:
        out.extend(p for p in v.split(",") if p)
    return out


def read_site_config(config_path):
    """Return (url, baseurl) from Jekyll _config.yml."""
    text = config_path.read_text(encoding="utf-8")
    u = re.search(r'(?m)^url:\s*["\']?(.*?)["\']?\s*(?:#.*)?$', text)
    b = re.search(r'(?m)^baseurl:\s*["\']?(.*?)["\']?\s*(?:#.*)?$', text)
    return (u.group(1).rstrip("/") if u else ""), (b.group(1) if b else "")


def jekyll_slug(name):
    """Jekyll "pretty" slugify (what Chirpy permalinks use): keep letters
    (incl. CJK, U+4E00-U+9FFF), digits and ._~!$&'()+,;=@ ; turn everything
    else into hyphens; case is preserved. Verified against real `jekyll build`."""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._~!$&'()+,;=@]+", "-", name).strip("-")


def find_post(posts_dir, doc_stem):
    """Return the _posts/<date>-<doc_stem>.md file, or None if not published."""
    pat = re.compile(r"\d{4}-\d{2}-\d{2}-" + re.escape(doc_stem) + r"\.md$")
    return next((p for p in posts_dir.glob("*.md") if pat.match(p.name)), None)


def blog_url(post_name, site_url="", baseurl=""):
    """Blog post URL. Absolute if site_url is given, else site-relative."""
    stem = POST_DATE_RE.sub("", post_name[:-3])
    return f"{site_url}{baseurl}/posts/{jekyll_slug(stem)}/"


def split_frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    return (m.group(1), text[m.end():]) if m else ("", text)


def normalize_wikilinks(body):
    """![[x|cap]] / ![[x]] -> ![cap](x)."""
    def repl(m):
        img = m.group(1).strip()
        cap = m.group(2) if m.group(2) else Path(img).stem
        return f"![{cap}]({img})"
    return WIKI_IMG.sub(repl, body)


def resolve_doc_links(body, posts_dir, url_of):
    """[[doc]] / [[doc#h]] / [[doc|alias]] -> [text](url_of(post.name)) when the
    doc is published (exists under _posts/); otherwise leave the plain text and
    record the doc as missing.

    Returns (new_body, [missing_doc_names]).  url_of(post_name) -> url string.
    """
    missing = []

    def repl(m):
        doc = m.group(1).strip()
        display = (m.group(2) or doc).strip()
        post = find_post(posts_dir, doc)
        if post:
            return f"[{display}]({url_of(post.name)})"
        missing.append(doc)
        return display

    return WIKI_LINK.sub(repl, body), missing


def make_excluded(vault, exclude_dirs):
    """Return a predicate: True if a path sits under any excluded dir name."""
    excl = {d.lower() for d in exclude_dirs}

    def excluded(path):
        return any(part.lower() in excl for part in path.relative_to(vault).parts)

    return excluded


def collect_targets(vault, file_args, excluded):
    """All *.md under the vault (excluded dirs skipped), optionally filtered by
    file_args: a value ending in .md = exact filename, else a keyword substring."""
    notes = [f for f in vault.rglob("*.md") if not excluded(f)]
    if not file_args:
        return notes

    def matches(name):
        nl = name.lower()
        for pat in file_args:
            pl = pat.lower()
            if (pl.endswith(".md") and nl == pl) or (not pl.endswith(".md") and pl in nl):
                return True
        return False

    return [f for f in notes if matches(f.name)]


def index_images(vault, excluded):
    """Map image filename -> source path (first occurrence wins)."""
    img = {}
    for f in vault.rglob("*"):
        if f.is_file() and f.suffix.lower() in IMG_EXT and not excluded(f):
            img.setdefault(f.name, f)
    return img
