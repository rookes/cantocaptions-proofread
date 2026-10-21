# Set up cantocaptions-proofread. Safe to run again at any time.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# 1. uv (the Python tool manager) and ffmpeg: installed if missing (uv per user; ffmpeg with winget)
# 2. the Python environment (uv sync)
# 3. the skills link Claude Code reads (.claude\skills -> .agents\skills; Antigravity reads
#    .agents\skills directly)
# 4. the dictionary caches (about a minute, the first time)
# 5. a summary: what this machine has, and what to do next (`ccp setup --text`)
#
# -FixConsole also makes every PowerShell session print Chinese correctly (it adds one line to
# your PowerShell profile; see README, "Windows console encoding").

param([switch]$FixConsole)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# Another project's activated environment would make uv warn on every command; this repo has its own.
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

function Step($n, $text) { Write-Host ""; Write-Host "[$n/5] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      ok: $text" }
function Fail($text) { Write-Host ""; Write-Host "Setup stopped: $text" -ForegroundColor Red; exit 1 }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
}

Step 1 "Tools"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "      installing uv (for this user only)..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    Refresh-Path
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fail "uv could not be installed. Install it from https://docs.astral.sh/uv/ and run this again."
    }
}
Ok "uv $((uv --version) -replace '^uv ', '')"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      installing ffmpeg with winget..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --silent | Out-Null
        Refresh-Path
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Fail "ffmpeg is not installed. Install it (winget install Gyan.FFmpeg, or https://ffmpeg.org), open a new terminal, and run this again."
    }
}
Ok "ffmpeg"

Step 2 "Python environment"
uv sync --quiet
if ($LASTEXITCODE -ne 0) { Fail "uv sync failed (see the messages above)." }
Ok "installed"

Step 3 "Skills for Claude Code"
$link = Join-Path $root ".claude\skills"
$target = Join-Path $root ".agents\skills"
New-Item -ItemType Directory -Force (Join-Path $root ".claude") | Out-Null
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -in "Junction", "SymbolicLink") { Ok "already linked" }
    else { Write-Host "      .claude\skills is a real folder, so it was left alone. Delete it and run this again to link it." -ForegroundColor Yellow }
} else {
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
    Ok "linked (.claude\skills -> .agents\skills)"
}

Step 4 "Dictionary caches (about a minute the first time)"
uv run --no-sync python -c "from ccp import dictionary, jyutping, corpus; dictionary.senses(); jyutping._table(); corpus.available() and corpus.lines('strict')"
if ($LASTEXITCODE -ne 0) { Fail "building the caches failed (see the messages above)." }
Ok "built"

if ($FixConsole) {
    $line = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new()  # added by cantocaptions-proofread setup: UTF-8 program output'
    $profilePath = $PROFILE.CurrentUserAllHosts
    New-Item -ItemType Directory -Force (Split-Path $profilePath) | Out-Null
    if (-not ((Test-Path $profilePath) -and (Select-String -Path $profilePath -SimpleMatch '[Console]::OutputEncoding' -Quiet))) {
        Add-Content -Path $profilePath -Value $line -Encoding UTF8
    }
    Ok "PowerShell prints UTF-8 in new sessions ($profilePath)"
}

Step 5 "Summary"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
uv run --no-sync ccp setup --text
