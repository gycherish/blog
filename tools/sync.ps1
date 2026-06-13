# Sync notes from an Obsidian vault into the Chirpy blog.
#
#   New notes   -> _drafts/   (local --drafts preview only; not built/committed)
#   Published   -> updated in place under _posts/ (matched by basename)
#   Images      -> only those referenced by synced notes are copied (incremental)
#   ![[x|cap]]  -> ![cap](x), with media_subpath injected into the frontmatter
#   Private files listed in $excludeFiles are never synced (filtered + asserted).
#
# --vault is required. Without -f, every markdown file in the vault is synced;
# with -f, only matching notes are. Non-article files (README, templates, etc.)
# are skipped via --exclude-dir and the frontmatter/date check.
# Run with -h/--help for usage.

$ErrorActionPreference = 'Stop'

# ---- defaults --------------------------------------------------------------
$vault       = $null                                # required: --vault PATH
$fileArgs    = @()                                  # -f/--file or positional; empty => all
$excludeDirs = @('.obsidian', '.git', 'templates')
$clean       = $false
$showHelp    = $false

# ---- argument parsing (GNU-style long/short options) -----------------------
# Normalize "--key=value" into two tokens so both forms work.
$argv = @()
foreach ($a in $args) {
    if ($a -match '^(--[^=]+)=(.*)$') { $argv += $Matches[1], $Matches[2] }
    else { $argv += $a }
}

function Read-Value([int]$idx) {
    if ($idx -ge $argv.Count) {
        Write-Host "Option '$($argv[$idx - 1])' requires a value." -ForegroundColor Red
        exit 2
    }
    $argv[$idx]
}

$i = 0
while ($i -lt $argv.Count) {
    $a = $argv[$i]
    if     ($a -eq '-f' -or $a -eq '--file')        { $i++; $fileArgs    += ((Read-Value $i) -split ',') }
    elseif ($a -eq '-x' -or $a -eq '--exclude-dir') { $i++; $excludeDirs += ((Read-Value $i) -split ',') }
    elseif ($a -eq '-c' -or $a -eq '--clean')       { $clean = $true }
    elseif ($a -eq '--vault')                       { $i++; $vault = (Read-Value $i) }
    elseif ($a -eq '-h' -or $a -eq '--help')        { $showHelp = $true }
    elseif ($a -like '-*')                          { Write-Host "Unknown option: $a (use -h for help)" -ForegroundColor Red; exit 2 }
    else                                            { $fileArgs += ($a -split ',') }
    $i++
}

if ($showHelp) {
    Write-Host @"
Usage: sync.ps1 --vault PATH [OPTIONS] [FILE_OR_KEYWORD...]

Sync notes from an Obsidian vault into the Chirpy blog.

Required:
      --vault PATH       Vault root directory.

Options:
  -f, --file VALUE       Select which notes to sync (repeatable/comma-separated,
                         also accepted as positional arguments).
                           - VALUE ending in .md  -> exact filename match
                           - VALUE otherwise       -> keyword, matches any
                                                      filename containing it
                         Without -f, all markdown files in the vault are synced.
  -x, --exclude-dir DIR  Directory name to skip anywhere in the tree
                         (repeatable). Default: .obsidian, .git, templates.
  -c, --clean            Clear drafts and synced images first (full rebuild).
  -h, --help             Show this help.

Examples:
  sync.ps1 --vault C:\notes                     Sync every note
  sync.ps1 --vault C:\notes -f coroutine        Notes matching "coroutine"
  sync.ps1 --vault C:\notes -f "C++20 协程.md"  One exact file
  sync.ps1 --vault C:\notes -f linux,x11        Several keywords
  sync.ps1 --vault C:\notes --clean             Wipe synced content and rebuild
"@
    exit 0
}

# ---- validate required arguments -------------------------------------------
if (-not $vault) {
    Write-Host "Error: --vault PATH is required (use -h for help)." -ForegroundColor Red
    exit 2
}

# ---- paths -----------------------------------------------------------------
$blogRoot  = Split-Path $PSScriptRoot -Parent
$postsDir  = Join-Path $blogRoot '_posts'
$draftsDir = Join-Path $blogRoot '_drafts'
$imgDir    = Join-Path $blogRoot 'assets\img\notes'

# Private files that must never be published (matched by filename).
# Empty by default; add filenames here to keep specific private notes out.
$excludeFiles = @()

if (-not (Test-Path $vault)) { Write-Host "Vault not found: $vault" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force $draftsDir | Out-Null
New-Item -ItemType Directory -Force $postsDir  | Out-Null
New-Item -ItemType Directory -Force $imgDir    | Out-Null

if ($clean) {
    Get-ChildItem $draftsDir -File | Remove-Item -Force
    Get-ChildItem $imgDir -File -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "Cleared drafts and image cache (full rebuild)." -ForegroundColor Yellow
}

# True if any path segment is an excluded directory name.
$exclSet = [System.Collections.Generic.HashSet[string]]::new(
    [string[]]$excludeDirs, [System.StringComparer]::OrdinalIgnoreCase)
function Test-Excluded([string]$fullPath) {
    $rel = $fullPath.Substring($vault.Length).TrimStart('\', '/')
    foreach ($p in ($rel -split '[\\/]')) { if ($exclSet.Contains($p)) { return $true } }
    return $false
}

# ---- index vault images by filename (any subdir, excluded dirs skipped) ----
$imgExt = @('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg')
$imgSource = @{}
Get-ChildItem $vault -File -Recurse | Where-Object {
    $imgExt -contains $_.Extension.ToLower() -and -not (Test-Excluded $_.FullName)
} | ForEach-Object {
    if (-not $imgSource.ContainsKey($_.Name)) { $imgSource[$_.Name] = $_.FullName }
}

# ---- collect candidate notes (whole vault, then optional -f filter) --------
$allNotes = @(Get-ChildItem $vault -Filter *.md -File -Recurse | Where-Object {
    -not (Test-Excluded $_.FullName) -and ($excludeFiles -notcontains $_.Name)
})

if ($fileArgs.Count) {
    $targets = @($allNotes | Where-Object {
        $name = $_.Name
        $hit = $false
        foreach ($pat in $fileArgs) {
            if ($pat -like '*.md') { if ($name -ieq $pat)      { $hit = $true; break } }   # exact filename
            else                   { if ($name -like "*$pat*") { $hit = $true; break } }   # keyword
        }
        $hit
    })
} else {
    $targets = $allNotes
}

if ($targets.Count -eq 0) {
    $scope = if ($fileArgs.Count) { "file/keyword [$($fileArgs -join ', ')]" } else { "vault $vault" }
    Write-Host "No notes matched $scope." -ForegroundColor Red
    exit 0
}

# ---- transform & write -----------------------------------------------------
# ![[x|cap]] / ![[x]]  ->  ![cap](x)
$wikiImg = [regex]'!\[\[([^\]\|]+?)(?:\|([^\]]*))?\]\]'
$evaluator = [System.Text.RegularExpressions.MatchEvaluator] {
    param($m)
    $img = $m.Groups[1].Value.Trim()
    $cap = if ($m.Groups[2].Success -and $m.Groups[2].Value) { $m.Groups[2].Value }
           else { [System.IO.Path]::GetFileNameWithoutExtension($img) }
    "![$cap]($img)"
}
# Standard image syntax, used to discover which images a note references.
$stdImg = [regex]'!\[[^\]]*\]\(([^)\s]+)\)'

$draftedList = @(); $publishedList = @(); $copiedImgs = @{}; $missingImgs = @()
foreach ($f in $targets) {
    $text = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)

    # Only real articles: must have frontmatter and a concrete date.
    if (-not $text.StartsWith('---')) { continue }   # e.g. README -> skip silently
    if (-not [regex]::IsMatch($text, '(?m)^date:\s*\d{4}-\d{2}-\d{2}')) {
        Write-Host "Skipped (no valid date): $($f.Name)" -ForegroundColor DarkYellow
        continue
    }

    $text = $wikiImg.Replace($text, $evaluator)

    # Inject media_subpath so the theme resolves images under assets/img/notes.
    if ($text -notmatch '(?m)^media_subpath:') {
        $text = "---`r`nmedia_subpath: /assets/img/notes" + $text.Substring(3)
    }

    # Copy only the images this note references (incremental, never deletes).
    foreach ($im in $stdImg.Matches($text)) {
        $u = $im.Groups[1].Value.Trim()
        if ($u -match '^https?://') { continue }
        $imgName = [System.IO.Path]::GetFileName($u)
        if ($copiedImgs.ContainsKey($imgName)) { continue }
        if ($imgSource.ContainsKey($imgName)) {
            Copy-Item $imgSource[$imgName] (Join-Path $imgDir $imgName) -Force
            $copiedImgs[$imgName] = $true
        } else {
            $missingImgs += "$imgName ($($f.Name))"
        }
    }

    # New note -> draft; already published (same basename) -> update in place.
    $name = $f.BaseName
    $existing = Get-ChildItem $postsDir -Filter "????-??-??-$name.md" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($existing) {
        [System.IO.File]::WriteAllText($existing.FullName, $text, (New-Object System.Text.UTF8Encoding $false))
        $publishedList += $name
    } else {
        [System.IO.File]::WriteAllText((Join-Path $draftsDir "$name.md"), $text, (New-Object System.Text.UTF8Encoding $false))
        $draftedList += $name
    }
}

# Safety net: private files must never reach blog content.
foreach ($n in $excludeFiles) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($n)
    if (Get-ChildItem $draftsDir, $postsDir -Filter "*$base*" -ErrorAction SilentlyContinue) {
        throw "Private file '$n' leaked into blog content. Aborting."
    }
}

# ---- summary ---------------------------------------------------------------
Write-Host ""
Write-Host "Sync complete:" -ForegroundColor Green
if ($draftedList)   { Write-Host "  drafts ($($draftedList.Count)): $($draftedList -join ', ')" }
if ($publishedList) { Write-Host "  updated posts ($($publishedList.Count)): $($publishedList -join ', ')" }
Write-Host "  images copied: $($copiedImgs.Count)"
if ($missingImgs)   { Write-Host "  missing images ($($missingImgs.Count)): $($missingImgs -join '; ')" -ForegroundColor Yellow }
