#!/usr/bin/env python3
"""Sync notes from an Obsidian vault into the Chirpy blog.

  New notes   -> _drafts/   (local --drafts preview only; not built/committed)
  Published   -> updated in place under _posts/ (matched by basename)
  Images      -> only those referenced by synced notes are copied (incremental)
  ![[x|cap]]  -> ![cap](x), with media_subpath injected into the frontmatter
  Private files in EXCLUDE_FILES are never synced (filtered + asserted).

--vault is required. Without -f, every markdown file in the vault is synced;
with -f, only matching notes are. Non-article files (README, templates, etc.)
are skipped via --exclude-dir and the frontmatter/date check.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

# Emit UTF-8 regardless of the OS console code page (e.g. Windows cp936),
# so Chinese filenames/output aren't mangled.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

# Private files that must never be published (matched by filename).
# Empty by default; add filenames here to keep specific private notes out.
EXCLUDE_FILES = []

WIKI_IMG = re.compile(r"!\[\[([^\]\|]+?)(?:\|([^\]]*))?\]\]")
STD_IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
DATE_RE = re.compile(r"^date:\s*\d{4}-\d{2}-\d{2}", re.MULTILINE)


def split_csv(values):
    """Flatten a list of possibly comma-separated values."""
    out = []
    for v in values:
        out.extend(p for p in v.split(",") if p)
    return out


def parse_args():
    p = argparse.ArgumentParser(
        prog="sync.py",
        description="Sync notes from an Obsidian vault into the Chirpy blog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "-f VALUE: ends with .md -> exact filename match; "
            "otherwise -> keyword (substring, case-insensitive).\n"
            "Without -f, all markdown files in the vault are synced.\n\n"
            "Examples:\n"
            "  sync.py --vault ~/notes                     Sync every note\n"
            "  sync.py --vault ~/notes -f coroutine        Notes matching \"coroutine\"\n"
            "  sync.py --vault ~/notes -f \"C++20 协程.md\"  One exact file\n"
            "  sync.py --vault ~/notes -f linux,x11        Several keywords\n"
            "  sync.py --vault ~/notes --clean             Wipe synced content and rebuild\n"
        ),
    )
    p.add_argument("--vault", required=True, help="Vault root directory (required).")
    p.add_argument("-f", "--file", action="append", default=[], metavar="VALUE",
                   help="Select notes to sync (repeatable / comma-separated). "
                        "Also accepted as positional arguments.")
    p.add_argument("-x", "--exclude-dir", action="append", default=[], metavar="DIR",
                   help="Directory name to skip anywhere in the tree (repeatable). "
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

    file_args = split_csv(args.file) + split_csv(args.files)
    exclude_dirs = {d.lower() for d in
                    [".obsidian", ".git", "templates"] + split_csv(args.exclude_dir)}

    blog_root = Path(__file__).resolve().parent.parent
    posts_dir = blog_root / "_posts"
    drafts_dir = blog_root / "_drafts"
    img_dir = blog_root / "assets" / "img" / "notes"
    for d in (posts_dir, drafts_dir, img_dir):
        d.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for f in list(drafts_dir.glob("*")) + list(img_dir.glob("*")):
            if f.is_file():
                f.unlink()
        print("Cleared drafts and image cache (full rebuild).")

    def excluded(path):
        return any(part.lower() in exclude_dirs
                   for part in path.relative_to(vault).parts)

    # Index vault images by filename (first occurrence wins).
    img_source = {}
    for f in vault.rglob("*"):
        if f.is_file() and f.suffix.lower() in IMG_EXT and not excluded(f):
            img_source.setdefault(f.name, f)

    # Collect candidate notes (whole vault), then optional -f filter.
    all_notes = [f for f in vault.rglob("*.md")
                 if not excluded(f) and f.name not in EXCLUDE_FILES]

    if file_args:
        def matches(name):
            nl = name.lower()
            for pat in file_args:
                pl = pat.lower()
                if pl.endswith(".md"):
                    if nl == pl:           # exact filename
                        return True
                elif pl in nl:             # keyword (substring)
                    return True
            return False
        targets = [f for f in all_notes if matches(f.name)]
    else:
        targets = all_notes

    if not targets:
        scope = f"file/keyword {file_args}" if file_args else f"vault {vault}"
        print(f"No notes matched {scope}.")
        return 0

    def wiki_repl(m):
        img = m.group(1).strip()
        cap = m.group(2) if m.group(2) else Path(img).stem
        return f"![{cap}]({img})"

    drafted, published, copied, missing = [], [], {}, []
    for f in targets:
        text = f.read_text(encoding="utf-8")

        # Only real articles: must have frontmatter and a concrete date.
        if not text.startswith("---"):
            continue                       # e.g. README -> skip silently
        if not DATE_RE.search(text):
            print(f"Skipped (no valid date): {f.name}")
            continue

        text = WIKI_IMG.sub(wiki_repl, text)

        # Inject media_subpath so the theme resolves images under assets/img/notes.
        if not re.search(r"^media_subpath:", text, re.MULTILINE):
            text = "---\nmedia_subpath: /assets/img/notes" + text[3:]

        # Copy only the images this note references (incremental, never deletes).
        for m in STD_IMG.finditer(text):
            u = m.group(1).strip()
            if u.startswith(("http://", "https://")):
                continue
            name = Path(u).name
            if name in copied:
                continue
            if name in img_source:
                shutil.copyfile(img_source[name], img_dir / name)
                copied[name] = True
            else:
                missing.append(f"{name} ({f.name})")

        # New note -> draft; already published (same basename) -> update in place.
        stem = f.stem
        pat = re.compile(r"\d{4}-\d{2}-\d{2}-" + re.escape(stem) + r"\.md$")
        existing = next((p for p in posts_dir.glob("*.md") if pat.match(p.name)), None)
        if existing:
            existing.write_text(text, encoding="utf-8")
            published.append(stem)
        else:
            (drafts_dir / f"{stem}.md").write_text(text, encoding="utf-8")
            drafted.append(stem)

    # Safety net: private files must never reach blog content.
    for n in EXCLUDE_FILES:
        base = Path(n).stem
        for d in (drafts_dir, posts_dir):
            if any(base in p.name for p in d.glob("*.md")):
                raise SystemExit(f"Private file '{n}' leaked into blog content. Aborting.")

    print()
    print("Sync complete:")
    if drafted:
        print(f"  drafts ({len(drafted)}): {', '.join(drafted)}")
    if published:
        print(f"  updated posts ({len(published)}): {', '.join(published)}")
    print(f"  images copied: {len(copied)}")
    if missing:
        print(f"  missing images ({len(missing)}): {'; '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
