# ===========================================================================
# THE DESKTOP INSTALLER (Windows) — the repository to a launchable app,
# one command, your own API keys:
#
#   irm https://raw.githubusercontent.com/reda-baqechame/self-learning-24.7-agent/main/install.ps1 | iex
#
# What you get: the fleet cloned to  %USERPROFILE%\ExpertFleet , an
# "Expert Fleet" shortcut on the Desktop and in the Start Menu, and an
# agent.env ready for your keys. The shortcut runs start-agent.ps1, which
# proves the wiring (bootstrap + provider check) before starting the panel
# and the loop — it will TELL you what is missing rather than half-start.
#
# What this deliberately does not do: it installs no dependencies beyond
# what you already have (the platform is Python stdlib only), it never asks
# for a key (keys go in agent.env, read by the platform, printed by nothing),
# and it starts nothing — first launch is yours, from the shortcut.
#
# NOTE: launched locally the agents execute commands as YOUR user on THIS
# machine. Good for driving it yourself; for unattended 24/7 use the cloud
# path (get-fleet.sh / docker compose) or settings.toml sandbox = "docker".
# ===========================================================================

# Everything lives in one function so that, piped to iex, a failed
# prerequisite RETURNS with its instruction instead of `exit` closing
# the very terminal that was showing it. $ErrorActionPreference is
# scoped to the function, so your session's setting is untouched.
function Install-ExpertFleet {
    $ErrorActionPreference = "Stop"

$Repo = "https://github.com/reda-baqechame/self-learning-24.7-agent.git"
$Dest = Join-Path $env:USERPROFILE "ExpertFleet"

# -- prerequisites: name what is missing and how to get it, then stop -------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python 3.11+ is required.  winget install Python.Python.3.12" -ForegroundColor Yellow
    return
}
$ver = & python -c "import sys;print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.11") {
    Write-Host "Python $ver found; 3.11+ required.  winget install Python.Python.3.12" -ForegroundColor Yellow
    return
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is required.  winget install Git.Git" -ForegroundColor Yellow
    return
}

# -- fetch: clone once, fast-forward thereafter (rerun = update) ------------
if (Test-Path (Join-Path $Dest ".git")) {
    Write-Host "== updating $Dest =="
    git -C $Dest pull --ff-only
} else {
    Write-Host "== cloning to $Dest =="
    git clone --depth 1 $Repo $Dest
}

# -- keys file: created empty, never touched again if it exists -------------
$envFile = Join-Path $Dest "agent.env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Dest "agent.env.example") $envFile
    Write-Host "wrote agent.env - put your API keys there (SET SPEND CAPS AT THE PROVIDER FIRST)" -ForegroundColor Yellow
}

# -- shortcuts: Desktop + Start Menu, both running the proving launcher -----
$launcher = Join-Path $Dest "start-agent.ps1"
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Expert Fleet.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Expert Fleet.lnk")
)
$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in $targets) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = "powershell.exe"
    $s.Arguments = "-NoExit -ExecutionPolicy Bypass -File `"$launcher`""
    $s.WorkingDirectory = $Dest
    $s.Description = "Expert Fleet - the panel and the loop, wiring proven first"
    $s.Save()
}

Write-Host ""
Write-Host "Installed. Next:" -ForegroundColor Green
Write-Host "  1. put a key in $envFile   (any provider; one key is enough)"
Write-Host "     or:  cd $Dest ; python bootstrap.py --key sk-..."
Write-Host "  2. double-click 'Expert Fleet' on the Desktop"
Write-Host "     panel: http://127.0.0.1:7777  - the loop runs in the same window; Ctrl+C stops it, state survives"
}

Install-ExpertFleet
