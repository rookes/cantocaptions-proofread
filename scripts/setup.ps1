# One-time (and safe to re-run) setup for cantocaptions-proofread.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# 1. Installs the light environment (uv sync --group dev).
# 2. Links .claude\skills -> .agents\skills (a directory junction; no admin rights needed), so
#    Claude Code and Google Antigravity read the same skill files.
# 3. Builds the dictionary, readings and strict-corpus caches under cache\.
# 4. Checks the sibling repositories and tools the GPU commands rely on.

param(
    # Also add a UTF-8 console line to your PowerShell profile (see README, "Windows console encoding").
    [switch]$FixConsole
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== uv sync"
uv sync --group dev
if (-not $?) { throw "uv sync failed" }

Write-Host "== skills junction"
$link = Join-Path $root ".claude\skills"
$target = Join-Path $root ".agents\skills"
New-Item -ItemType Directory -Force (Join-Path $root ".claude") | Out-Null
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction" -or $item.LinkType -eq "SymbolicLink") {
        Write-Host "  .claude\skills already links to $($item.Target)"
    } else {
        Write-Warning ".claude\skills exists and is a real directory; leaving it alone. Remove it and re-run to link."
    }
} else {
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    Write-Host "  linked .claude\skills -> .agents\skills"
}

Write-Host "== caches (first run takes about a minute)"
uv run --no-sync python -c "from ccp import dictionary, jyutping, corpus; print('  dictionary senses:', len(dictionary.senses())); print('  characters with readings:', len(jyutping._table())); print('  strict corpus lines:', len(corpus.lines('strict')))"

Write-Host "== checks"
foreach ($tool in "ffmpeg", "ffprobe", "uv") {
    if (Get-Command $tool -ErrorAction SilentlyContinue) { Write-Host "  ok   $tool" } else { Write-Warning "missing $tool on PATH" }
}
uv run --no-sync python -c @"
from ccp import paths
checks = [
    ('CantoCaptions subtitles', paths.get('subtitles')),
    ('dataset manifest', paths.get('dataset') / 'data' / 'manifest.json'),
    ('dataset quality tiers', paths.get('dataset') / 'data' / 'std' / 'episodes.json'),
    ('dataset standardization rules', paths.get('dataset') / 'rules' / 'standardization.toml'),
    ('cantocaptions-ai venv', paths.get('cantocaptions_ai') / '.venv'),
    ('sub-convert venv (OCR)', paths.get('sub_convert') / '.venv'),
    ('media root', paths.get('media_root')),
]
for name, p in checks:
    print(('  ok   ' if p.exists() else '  MISSING ') + f'{name}: {p}')
"@
if ($FixConsole) {
    Write-Host "== console encoding"
    $line = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new()  # added by cantocaptions-proofread setup: UTF-8 program output'
    $profilePath = $PROFILE.CurrentUserAllHosts
    New-Item -ItemType Directory -Force (Split-Path $profilePath) | Out-Null
    if ((Test-Path $profilePath) -and (Select-String -Path $profilePath -SimpleMatch '[Console]::OutputEncoding' -Quiet)) {
        Write-Host "  $profilePath already sets [Console]::OutputEncoding; left as is"
    } else {
        Add-Content -Path $profilePath -Value $line -Encoding UTF8
        Write-Host "  added to $profilePath (applies to new PowerShell sessions)"
    }
} else {
    Write-Host "Tip: run with -FixConsole to make PowerShell decode UTF-8 in every session (README: Windows console encoding)."
}

Write-Host "Done. Run 'uv run ccp -h' to see the tools."
