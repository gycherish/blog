# Tooling

Cross-platform Python scripts that turn Obsidian vault notes into:

- a Jekyll **Chirpy blog** — `sync.py` → `publish.py`, and
- **WeChat Official Account** drafts (via self-hosted [doocs/md](https://github.com/doocs/md)) — `wechat.py`.

Everything is managed by [pixi](https://pixi.sh): run `pixi install` once, then
`pixi run <task>`. No system Python required.

> `run.sh` / `test.sh` belong to the Chirpy theme and are **not** part of this tooling.

## Scripts

### `sync.py` — vault → blog drafts

Copies notes from the Obsidian vault into the blog, translating Obsidian syntax:

- `![[img|cap]]` → `![cap](img)`; referenced images are copied into
  `assets/img/notes/` (incremental — only what's referenced, never deletes others)
- injects `media_subpath` so the theme resolves images
- new notes → `_drafts/` (local `--drafts` preview only, not deployed);
  already-published notes (same basename in `_posts/`) → updated in place

```
pixi run sync --vault <vault> [-f VALUE ...] [-x DIR ...] [--clean]
```

| Option | Meaning |
| --- | --- |
| `--vault PATH` | Obsidian vault root (**required**) |
| `-f, --file VALUE` | Select notes: ends with `.md` = exact filename, otherwise a keyword (case-insensitive substring). Repeatable / comma-separated. Without `-f`, the whole vault is synced. |
| `-x, --exclude-dir DIR` | Directory name to skip anywhere in the tree (default: `.obsidian, .git, templates`) |
| `--clean` | Clear drafts and synced images before syncing |

### `publish.py` — draft → post

Moves a draft from `_drafts/` to `_posts/` with a date prefix taken from its
frontmatter `date` (what Jekyll needs for a real post).

```
pixi run publish              # list drafts and published posts
pixi run publish <keyword>    # publish the draft matching <keyword>
```

### `wechat.py` — vault → doocs/md-ready Markdown

Prepares a note for the WeChat Official Account; layout and the final publish are
done in self-hosted doocs/md. The script:

- uploads in-body images to the WeChat material library (SVG auto-converted to
  PNG) and rewrites links to the returned WeChat URLs
- resolves `[[doc]]` / `[[doc#heading]]` / `[[doc|alias]]` to the **blog post URL**
  if that doc is already published — otherwise **errors out** (publish it first)
- requires the note itself to be published to the blog, and appends a
  "view original" link pointing to its blog URL
- writes clean Markdown to `tools/wechat-out/<name>.md`

```
pixi run wechat --vault <vault> -f <keyword> [--dry-run]
```

| Option | Meaning |
| --- | --- |
| `--vault PATH` | Obsidian vault root (**required**) |
| `-f, --file VALUE` | Select notes (same matching rules as `sync.py`) |
| `--dry-run` | Convert without uploading images (still resolves links / blog URLs) |

Credentials come from `.env` at the repo root (copy `.env.example` → `.env`):

```
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
```

> WeChat requires the caller's public IP to be in the Official Account's IP
> allowlist. Error `40164` means your current IP isn't listed — add it in the
> console (home-broadband IPs change, so this may recur).

Then paste `tools/wechat-out/<name>.md` into doocs/md (e.g. `http://localhost:8080`),
set the title, and publish to the draft box.

## Typical workflow

```
pixi run sync    --vault <vault> -f <kw>   # 1. vault → blog draft
pixi run publish <kw>                       # 2. draft → post (blog)
git add -A && git commit && git push        # 3. deploy blog (CI builds it)
pixi run wechat  --vault <vault> -f <kw>    # 4. → tools/wechat-out/<kw>.md
#    paste into doocs/md → set title → publish to draft box → publish in console
```

**Order matters:** publish to the blog *before* running `wechat.py` — it needs the
blog post to exist to resolve `[[links]]` and build the "view original" URL.

## Notes

- Generated / secret files are gitignored: `.env`, `.wechat-token.json`,
  `.wechat-cache/`, `wechat-out/`.
- The blog-post slug is reproduced with Jekyll's *pretty* slugify rule; it has been
  verified against real `jekyll build` output (`C++`, `&`, full-width `：`, etc.).
