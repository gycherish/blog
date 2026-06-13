#!/usr/bin/env python3
"""Convert a vault note into doocs/md-ready Markdown.

Leaves layout to doocs/md; the script does:
  1. Pick note(s) from the vault (--vault + -f, same selection as sync.py).
  2. ![[x|cap]] -> ![cap](x); upload local images (SVG auto -> PNG) to the
     WeChat material library and rewrite links to the returned WeChat URLs.
  3. [[doc]] / [[doc#h]] / [[doc|alias]] -> absolute blog post link IF the doc
     is published (_posts/); otherwise this is an error (publish it first).
  4. Require the article itself to be published to the blog, and append a
     "view original" link pointing to its blog URL.
  5. Write clean standard Markdown to tools/wechat-out/<name>.md.

Then paste that file into your self-hosted doocs/md to lay out and publish.

Credentials via env or .env: WECHAT_APP_ID, WECHAT_APP_SECRET.
--dry-run: skip image uploads (still resolves links / blog URLs).
"""
import argparse
import json
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blogkit as bk

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

API = "https://api.weixin.qq.com/cgi-bin"
TOKEN_CACHE = Path(__file__).resolve().parent / ".wechat-token.json"


def ensure_raster(path, cache_dir):
    """WeChat rejects SVG; convert it to PNG (cached) before upload."""
    if path.suffix.lower() != ".svg":
        return path
    import cairosvg
    cache_dir.mkdir(exist_ok=True)
    out = cache_dir / (path.stem + ".png")
    if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
        cairosvg.svg2png(url=str(path), write_to=str(out), output_width=1080)
    return out


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
    """media/uploadimg -> a permanent WeChat-hosted URL usable in articles."""
    import requests
    with open(path, "rb") as fh:
        r = requests.post(f"{API}/media/uploadimg", params={"access_token": token},
                          files={"media": (path.name, fh)}, timeout=60).json()
    if "url" not in r:
        raise SystemExit(f"uploadimg failed for {path.name}: {r}")
    return r["url"]


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

    file_args = bk.split_csv(args.file) + bk.split_csv(args.files)
    exclude_dirs = [".obsidian", ".git", "templates"] + bk.split_csv(args.exclude_dir)
    excluded = bk.make_excluded(vault, exclude_dirs)

    targets = bk.collect_targets(vault, file_args, excluded)
    if not targets:
        print(f"No notes matched {file_args or 'vault'}.")
        return 0
    img_source = bk.index_images(vault, excluded)

    blog_root = Path(__file__).resolve().parent.parent
    posts_dir = blog_root / "_posts"
    out_dir = Path(__file__).resolve().parent / "wechat-out"
    cache_dir = Path(__file__).resolve().parent / ".wechat-cache"
    site_url, baseurl = bk.read_site_config(blog_root / "_config.yml")

    def url_of(post_name):  # absolute blog URL (WeChat needs full URLs)
        return bk.blog_url(post_name, site_url, baseurl)

    token = None
    if not args.dry_run:
        bk.load_dotenv(blog_root / ".env")
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
        fm, body = bk.split_frontmatter(f.read_text(encoding="utf-8"))
        tm = bk.TITLE_RE.search(fm)
        title = tm.group(1).strip() if tm else f.stem

        # The article itself must be published to the blog (need an original URL).
        self_post = bk.find_post(posts_dir, f.stem)
        if not self_post:
            failed.append((title, "还没发布到博客，请先 publish.py 发布博客再发公众号"))
            continue

        body = bk.normalize_wikilinks(body)

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

        body = bk.STD_IMG.sub(img_repl, body)

        # [[doc]] -> absolute blog link, or fail if a referenced doc is unpublished.
        body, missing_links = bk.resolve_doc_links(body, posts_dir, url_of)
        if missing_links:
            uniq = "、".join(dict.fromkeys(f"《{d}》" for d in missing_links))
            failed.append((title, f"引用了 {uniq}，但它们还没发布到博客"))
            continue

        body = body.strip() + (
            "\n\n---\n\n"
            f"> 📖 本文同步发布于个人博客，[点此查看原文]({url_of(self_post.name)})。\n"
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
