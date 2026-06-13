#!/usr/bin/env python3
"""Publish a draft to _posts/ (Jekyll-native workflow).

Drafts live in _drafts/ (gitignored, visible only in local --drafts preview).
Publishing moves a draft to _posts/ with a date prefix taken from its
frontmatter `date`, which is what Jekyll requires for a real post.
"""
import argparse
import re
import sys
from pathlib import Path

# Emit UTF-8 regardless of the OS console code page (e.g. Windows cp936).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def main():
    p = argparse.ArgumentParser(
        prog="publish.py",
        description="Publish a draft: move it from _drafts/ to _posts/ with a date prefix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  publish.py              List drafts and published posts\n"
            "  publish.py coroutine    Publish the draft whose filename matches \"coroutine\"\n"
        ),
    )
    p.add_argument("-l", "--list", action="store_true",
                   help="List drafts and published posts (default when no KEYWORD).")
    p.add_argument("keyword", nargs="?",
                   help="Filename keyword of the draft to publish.")
    args = p.parse_args()

    blog_root = Path(__file__).resolve().parent.parent
    posts_dir = blog_root / "_posts"
    drafts_dir = blog_root / "_drafts"

    drafts = sorted(drafts_dir.glob("*.md")) if drafts_dir.is_dir() else []
    posts = sorted(posts_dir.glob("*.md")) if posts_dir.is_dir() else []

    if args.list or not args.keyword:
        print(f"\nDrafts ({len(drafts)}, local only):")
        for f in drafts:
            print(f"  {f.name}")
        print(f"\nPublished ({len(posts)}):")
        for f in posts:
            print(f"  {f.name}")
        print("\nPublish with: publish.py <keyword>")
        return 0

    matched = [f for f in drafts if args.keyword.lower() in f.name.lower()]
    if not matched:
        print(f"No draft matched '{args.keyword}'.", file=sys.stderr)
        return 1
    if len(matched) > 1:
        print(f"Multiple drafts matched '{args.keyword}'; be more specific:", file=sys.stderr)
        for f in matched:
            print(f"  {f.name}")
        return 1

    f = matched[0]
    m = DATE_RE.search(f.read_text(encoding="utf-8"))
    if not m:
        print("Draft has no frontmatter 'date'; cannot publish.", file=sys.stderr)
        return 1

    target = posts_dir / f"{m.group(1)}-{f.name}"
    f.rename(target)
    print(f"Published: {target.name}")
    print("Next: git add + commit + push (deploys via CI).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
