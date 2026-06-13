#!/usr/bin/env python3
"""Sync notes from an Obsidian vault into the Chirpy blog.

  New notes   -> _drafts/   (local --drafts preview only; not built/committed)
  Published   -> updated in place under _posts/ (matched by basename)
  Images      -> only those referenced by synced notes are copied (incremental)
  ![[x|cap]]  -> ![cap](x), with media_subpath injected into the frontmatter
  [[doc]]     -> [text](<baseurl>/posts/<slug>/) when the doc is published;
                 if it isn't, the note is reported as an error and skipped
                 (publish the referenced doc to the blog first).
  Private files in EXCLUDE_FILES are never synced.

--vault is required. Without -f, every markdown file in the vault is synced.
Non-article files (README, templates, etc.) are skipped via --exclude-dir and
the frontmatter/date check.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blogkit as bk

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DATE_RE = re.compile(r"^date:\s*\d{4}-\d{2}-\d{2}", re.MULTILINE)
MEDIA_SUBPATH = "/assets/img/notes"
# Private files that must never be published (matched by filename). Empty by
# default; add filenames here to keep specific private notes out of the blog.
EXCLUDE_FILES = []


def parse_args():
    p = argparse.ArgumentParser(
        prog="sync.py",
        description="Sync notes from an Obsidian vault into the Chirpy blog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "-f VALUE: ends with .md -> exact filename; otherwise a keyword "
            "(case-insensitive substring). Without -f, the whole vault is synced.\n"
            "[[doc]] links require the referenced doc to be published (_posts/);\n"
            "otherwise the citing note is reported and skipped.\n\n"
            "Examples:\n"
            "  sync.py --vault ~/notes                 Sync every note\n"
            "  sync.py --vault ~/notes -f coroutine    Notes matching \"coroutine\"\n"
            "  sync.py --vault ~/notes --clean         Wipe synced content and rebuild\n"
        ),
    )
    p.add_argument("--vault", required=True, help="Vault root directory (required).")
    p.add_argument("-f", "--file", action="append", default=[], metavar="VALUE",
                   help="Select notes (repeatable / comma-separated).")
    p.add_argument("-x", "--exclude-dir", action="append", default=[], metavar="DIR",
                   help="Directory name to skip (repeatable). "
                        "Default: .obsidian, .git, templates.")
    p.add_argument("-c", "--clean", action="store_true",
                   help="Clear drafts and synced images first (full rebuild).")
    p.add_argument("files", nargs="*", help="Same as -f, given positionally.")
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

    blog_root = Path(__file__).resolve().parent.parent
    posts_dir = blog_root / "_posts"
    drafts_dir = blog_root / "_drafts"
    img_dir = blog_root / "assets" / "img" / "notes"
    for d in (posts_dir, drafts_dir, img_dir):
        d.mkdir(parents=True, exist_ok=True)
    _, baseurl = bk.read_site_config(blog_root / "_config.yml")

    if args.clean:
        for f in list(drafts_dir.glob("*")) + list(img_dir.glob("*")):
            if f.is_file():
                f.unlink()
        print("Cleared drafts and image cache (full rebuild).")

    img_source = bk.index_images(vault, excluded)
    targets = [t for t in bk.collect_targets(vault, file_args, excluded)
               if t.name not in EXCLUDE_FILES]
    if not targets:
        print(f"No notes matched {file_args or 'vault'}.")
        return 0

    def url_of(post_name):  # site-relative blog URL for in-blog links
        return bk.blog_url(post_name, "", baseurl)

    drafted, published, copied, missing_imgs, failed = [], [], {}, [], []
    for f in targets:
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue  # e.g. README -> skip silently
        if not DATE_RE.search(text):
            print(f"Skipped (no valid date): {f.name}")
            continue

        text = bk.normalize_wikilinks(text)

        # [[doc]] -> blog link, or fail this note if a referenced doc is unpublished.
        text, missing_links = bk.resolve_doc_links(text, posts_dir, url_of)
        if missing_links:
            uniq = "、".join(dict.fromkeys(f"《{d}》" for d in missing_links))
            failed.append((f.stem, f"引用了 {uniq}，但它们还没发布到博客"))
            continue

        # Inject media_subpath so the theme resolves images.
        if not re.search(r"^media_subpath:", text, re.MULTILINE):
            text = f"---\nmedia_subpath: {MEDIA_SUBPATH}" + text[3:]

        # Copy referenced local images (incremental, never deletes).
        for m in bk.STD_IMG.finditer(text):
            u = m.group(2).strip()
            if u.startswith(("http://", "https://")):
                continue
            name = Path(u).name
            if name in copied:
                continue
            if name in img_source:
                shutil.copyfile(img_source[name], img_dir / name)
                copied[name] = True
            else:
                missing_imgs.append(f"{name} ({f.name})")

        # New note -> draft; already published (same basename) -> update in place.
        existing = bk.find_post(posts_dir, f.stem)
        if existing:
            existing.write_text(text, encoding="utf-8")
            published.append(f.stem)
        else:
            (drafts_dir / f"{f.stem}.md").write_text(text, encoding="utf-8")
            drafted.append(f.stem)

    print()
    print("Sync complete:")
    if drafted:
        print(f"  drafts ({len(drafted)}): {', '.join(drafted)}")
    if published:
        print(f"  updated posts ({len(published)}): {', '.join(published)}")
    print(f"  images copied: {len(copied)}")
    if missing_imgs:
        print(f"  missing images ({len(missing_imgs)}): {'; '.join(missing_imgs)}")
    if failed:
        print("\n以下文章未同步（先把被引用的文章发布到博客）：", file=sys.stderr)
        for stem, why in failed:
            print(f"  ✗ 《{stem}》：{why}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
