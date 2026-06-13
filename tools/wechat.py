#!/usr/bin/env python3
"""Convert a vault note into doocs/md-ready Markdown.

This script does the parts a script does best and leaves layout to doocs/md:
  1. Pick note(s) from the vault (--vault + -f, same selection as sync.py).
  2. ![[x|cap]] -> ![cap](x); upload local images (SVG auto -> PNG) to the
     WeChat material library and rewrite links to the returned WeChat URLs.
  3. [[doc]] / [[doc#heading]] / [[doc|alias]] -> a link to the blog post,
     IF that doc is already published (exists under _posts/). If it isn't,
     this is reported as an error (publish it to the blog first).
  4. Require the article itself to be published to the blog, and append a
     "查看原文" (read original) link pointing to its blog URL.
  5. Write clean standard Markdown to tools/wechat-out/<name>.md.

Then paste that file into your self-hosted doocs/md to lay out and publish.

Credentials via env or .env: WECHAT_APP_ID, WECHAT_APP_SECRET.
--dry-run: skip image uploads (still checks links / blog URLs).
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

API = "https://api.weixin.qq.com/cgi-bin"
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

WIKI_IMG = re.compile(r"!\[\[([^\]\|]+?)(?:\|([^\]]*))?\]\]")
MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
# [[doc]], [[doc#heading]], [[doc|alias]], [[doc#heading|alias]]  (not ![[...]])
WIKI_LINK = re.compile(r"(?<!!)\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|([^\]]+))?\]\]")
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
POST_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")

TOKEN_CACHE = Path(__file__).resolve().parent / ".wechat-token.json"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_dotenv(path):
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
    """Read url + baseurl from Jekyll _config.yml."""
    text = config_path.read_text(encoding="utf-8")
    u = re.search(r'(?m)^url:\s*["\']?(.*?)["\']?\s*(?:#.*)?$', text)
    b = re.search(r'(?m)^baseurl:\s*["\']?(.*?)["\']?\s*(?:#.*)?$', text)
    return (u.group(1).rstrip("/") if u else ""), (b.group(1) if b else "")


def jekyll_slug(name):
    """Reproduce Jekyll's "pretty" slugify (what Chirpy permalinks use):
    keep letters (incl. CJK), digits and ._~!$&'()+,;=@ ; turn everything
    else into hyphens; case is preserved. Verified against jekyll build."""
    return re.sub(r"[^0-9A-Za-z一-鿿._~!$&'()+,;=@]+", "-", name).strip("-")


def blog_url(site_url, baseurl, post_name):
    stem = POST_DATE_RE.sub("", post_name[:-3])  # strip date prefix and .md
    return f"{site_url}{baseurl}/posts/{jekyll_slug(stem)}/"


def find_post(posts_dir, doc_stem):
    """Return the _posts/*.md whose name is <date>-<doc_stem>.md, or None."""
    pat = re.compile(r"\d{4}-\d{2}-\d{2}-" + re.escape(doc_stem) + r"\.md$")
    return next((p for p in posts_dir.glob("*.md") if pat.match(p.name)), None)


def collect_targets(vault, file_args, exclude_dirs):
    def excluded(path):
        return any(part.lower() in exclude_dirs
                   for part in path.relative_to(vault).parts)

    notes = [f for f in vault.rglob("*.md") if not excluded(f)]
    if not file_args:
        return notes, excluded

    def matches(name):
        nl = name.lower()
        for pat in file_args:
            pl = pat.lower()
            if (pl.endswith(".md") and nl == pl) or (not pl.endswith(".md") and pl in nl):
                return True
        return False

    return [f for f in notes if matches(f.name)], excluded


def index_images(vault, excluded):
    img = {}
    for f in vault.rglob("*"):
        if f.is_file() and f.suffix.lower() in IMG_EXT and not excluded(f):
            img.setdefault(f.name, f)
    return img


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


def ensure_raster(path, cache_dir):
    if path.suffix.lower() != ".svg":
        return path
    import cairosvg
    cache_dir.mkdir(exist_ok=True)
    out = cache_dir / (path.stem + ".png")
    if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
        cairosvg.svg2png(url=str(path), write_to=str(out), output_width=1080)
    return out


# --------------------------------------------------------------------------- #
# WeChat API (only image upload is needed; doocs/md handles layout & publish)
# --------------------------------------------------------------------------- #
def get_token(appid, secret):
    import requests
    if TOKEN_CACHE.exists():
        cached = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        if cached.get("appid") == appid and cached.get("expire", 0) > time.time() + 120:
            return cached["token"]
    r = requests.get(f"{API}/token", params={
        "grant_type": "client_credential", "appid": appid, "secret": secret,
    }, timeout=30).json()
    if "access_token" not in r:
        raise SystemExit(f"Failed to get access_token: {r}")
    TOKEN_CACHE.write_text(json.dumps({
        "appid": appid, "token": r["access_token"],
        "expire": time.time() + r.get("expires_in", 7200),
    }), encoding="utf-8")
    return r["access_token"]


def upload_image(token, path):
    import requests
    with open(path, "rb") as fh:
        r = requests.post(f"{API}/media/uploadimg", params={"access_token": token},
                          files={"media": (path.name, fh)}, timeout=60).json()
    if "url" not in r:
        raise SystemExit(f"uploadimg failed for {path.name}: {r}")
    return r["url"]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(
        prog="wechat.py",
        description="Convert a vault note into doocs/md-ready Markdown "
                    "(images -> WeChat material library; [[links]] -> blog URLs).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Workflow: sync -> publish (to blog) -> wechat. The note and every\n"
            "[[doc]] it references must already be published to the blog (_posts/),\n"
            "otherwise wechat.py reports an error and skips that note.\n\n"
            "Credentials via env or .env: WECHAT_APP_ID, WECHAT_APP_SECRET.\n"
            "Output: tools/wechat-out/<name>.md  (paste into doocs/md).\n"
        ),
    )
    p.add_argument("--vault", required=True, help="Vault root directory (required).")
    p.add_argument("-f", "--file", action="append", default=[], metavar="VALUE",
                   help="Select note(s): .md => exact filename, else keyword.")
    p.add_argument("-x", "--exclude-dir", action="append", default=[], metavar="DIR",
                   help="Directory name to skip (repeatable).")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip image uploads (still resolves links / blog URLs).")
    p.add_argument("files", nargs="*", help="Same as -f, positional.")
    return p.parse_args()


def main():
    args = parse_args()
    vault = Path(args.vault).expanduser()
    if not vault.is_dir():
        print(f"Vault not found: {vault}", file=sys.stderr)
        return 1

    file_args = split_csv(args.file) + split_csv(args.files)
    exclude_dirs = {d.lower() for d in
                    [".obsidian", ".git", "templates"] + split_csv(args.exclude_dir)}

    targets, excluded = collect_targets(vault, file_args, exclude_dirs)
    if not targets:
        print(f"No notes matched {file_args or 'vault'}.")
        return 0
    img_source = index_images(vault, excluded)

    blog_root = Path(__file__).resolve().parent.parent
    posts_dir = blog_root / "_posts"
    out_dir = Path(__file__).resolve().parent / "wechat-out"
    cache_dir = Path(__file__).resolve().parent / ".wechat-cache"
    site_url, baseurl = read_site_config(blog_root / "_config.yml")

    token = None
    if not args.dry_run:
        load_dotenv(blog_root / ".env")
        appid, secret = os.environ.get("WECHAT_APP_ID"), os.environ.get("WECHAT_APP_SECRET")
        if not (appid and secret):
            print("WECHAT_APP_ID / WECHAT_APP_SECRET not set "
                  "(use --dry-run to convert without uploading).", file=sys.stderr)
            return 2
        token = get_token(appid, secret)

    uploaded = {}
    out_dir.mkdir(exist_ok=True)
    done, failed = [], []

    for f in targets:
        fm, body = split_frontmatter(f.read_text(encoding="utf-8"))
        tm = TITLE_RE.search(fm)
        title = tm.group(1).strip() if tm else f.stem

        # The article itself must be published to the blog (need an "original" URL).
        self_post = find_post(posts_dir, f.stem)
        if not self_post:
            failed.append((title, f"还没发布到博客，请先 publish.py 发布博客再发公众号"))
            continue

        body = normalize_wikilinks(body)

        # Images -> WeChat URLs (or source files in dry-run).
        def img_repl(m):
            alt, url = m.group(1), m.group(2)
            if url.startswith(("http://", "https://")):
                return m.group(0)
            name = Path(url).name
            if name not in img_source:
                print(f"  ! missing image: {name} ({f.name})")
                return m.group(0)
            if args.dry_run:
                return f"![{alt}]({img_source[name].as_uri()})"
            if name not in uploaded:
                uploaded[name] = upload_image(token, ensure_raster(img_source[name], cache_dir))
            return f"![{alt}]({uploaded[name]})"

        body = MD_IMG.sub(img_repl, body)

        # [[doc]] links -> blog URLs (error if the doc isn't published).
        link_errors = []

        def link_repl(m):
            doc = m.group(1).strip()
            display = (m.group(2) or doc).strip()
            post = find_post(posts_dir, doc)
            if post:
                return f"[{display}]({blog_url(site_url, baseurl, post.name)})"
            link_errors.append(doc)
            return display

        body = WIKI_LINK.sub(link_repl, body)
        if link_errors:
            uniq = "、".join(dict.fromkeys(f"《{d}》" for d in link_errors))
            failed.append((title, f"引用了 {uniq}，但它们还没发布到博客"))
            continue

        # Append "read original" link to the blog post.
        body = body.strip() + (
            "\n\n---\n\n"
            f"> 📖 本文同步发布于个人博客，[点此查看原文]({blog_url(site_url, baseurl, self_post.name)})。\n"
        )

        out = out_dir / f"{f.stem}.md"
        out.write_text(body, encoding="utf-8")
        done.append((title, out))

    if done:
        print("\nConverted (paste into doocs/md, set the title, then publish):")
        for title, out in done:
            print(f"  《{title}》 -> {out}")
    if failed:
        print("\n以下文章未处理（先把它们/被引用的文章发布到博客）：", file=sys.stderr)
        for title, why in failed:
            print(f"  ✗ 《{title}》：{why}", file=sys.stderr)
    if args.dry_run and done:
        print("\n[dry-run] images point at source files; no uploads were made.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
