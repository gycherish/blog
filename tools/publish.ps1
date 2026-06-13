# Publish a draft to _posts/ (Jekyll-native workflow).
#
#   Drafts live in _drafts/ (gitignored, visible only in local --drafts preview).
#   Publishing moves a draft to _posts/ with a date prefix taken from its
#   frontmatter `date`, which is what Jekyll requires for a real post.
#
# Run with -h/--help for usage.

$ErrorActionPreference = 'Stop'

$keyword  = $null
$list     = $false
$showHelp = $false

# GNU-style argument parsing (supports --key=value and --key value).
$argv = @()
foreach ($a in $args) {
    if ($a -match '^(--[^=]+)=(.*)$') { $argv += $Matches[1], $Matches[2] }
    else { $argv += $a }
}
foreach ($a in $argv) {
    if     ($a -eq '-l' -or $a -eq '--list') { $list = $true }
    elseif ($a -eq '-h' -or $a -eq '--help') { $showHelp = $true }
    elseif ($a -like '-*') { Write-Host "Unknown option: $a (use -h for help)" -ForegroundColor Red; exit 2 }
    elseif (-not $keyword) { $keyword = $a }
    else { Write-Host "Only one keyword is allowed." -ForegroundColor Red; exit 2 }
}

if ($showHelp) {
    Write-Host @"
Usage: publish.ps1 [OPTIONS] [KEYWORD]

Publish a draft: move it from _drafts/ to _posts/ with a date prefix.

Options:
  -l, --list    List drafts and published posts (default when no KEYWORD).
  -h, --help    Show this help.

Examples:
  publish.ps1              List drafts and published posts
  publish.ps1 coroutine    Publish the draft whose filename matches "coroutine"
"@
    exit 0
}

$blogRoot  = Split-Path $PSScriptRoot -Parent
$postsDir  = Join-Path $blogRoot '_posts'
$draftsDir = Join-Path $blogRoot '_drafts'

$drafts = @(Get-ChildItem $draftsDir -Filter *.md -ErrorAction SilentlyContinue)
$posts  = @(Get-ChildItem $postsDir  -Filter *.md -ErrorAction SilentlyContinue)

if ($list -or -not $keyword) {
    Write-Host "`nDrafts ($($drafts.Count), local only):" -ForegroundColor Yellow
    $drafts | ForEach-Object { Write-Host "  $($_.Name)" }
    Write-Host "`nPublished ($($posts.Count)):" -ForegroundColor Green
    $posts | ForEach-Object { Write-Host "  $($_.Name)" }
    Write-Host "`nPublish with: publish.ps1 <keyword>"
    exit 0
}

$matched = @($drafts | Where-Object { $_.Name -like "*$keyword*" })
if ($matched.Count -eq 0) {
    Write-Host "No draft matched '$keyword'." -ForegroundColor Red
    exit 1
}
if ($matched.Count -gt 1) {
    Write-Host "Multiple drafts matched '$keyword'; be more specific:" -ForegroundColor Yellow
    $matched | ForEach-Object { Write-Host "  $($_.Name)" }
    exit 1
}

$f = $matched[0]
$text = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
$dateMatch = [regex]::Match($text, '(?m)^date:\s*(\d{4}-\d{2}-\d{2})')
if (-not $dateMatch.Success) {
    Write-Host "Draft has no frontmatter 'date'; cannot publish." -ForegroundColor Red
    exit 1
}

$target = Join-Path $postsDir "$($dateMatch.Groups[1].Value)-$($f.BaseName).md"
Move-Item $f.FullName $target
Write-Host "Published: $(Split-Path $target -Leaf)" -ForegroundColor Green
Write-Host "Next: git add + commit + push (GitHub Actions will deploy)."
