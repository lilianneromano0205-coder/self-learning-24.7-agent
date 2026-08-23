# Local launcher (Windows). Run from this folder:  .\start-agent.ps1
# Sets everything up on first run (agent.env, your first expert, the control
# panel), proves the wiring, then starts the loop. Ctrl+C stops it; state
# survives and resumes on the next start.
#
# NOTE: locally the agent executes commands as YOUR user on THIS machine.
# That is fine for testing; for unattended 24/7 operation use the VPS
# (setup-vps.sh) or set [agent] sandbox = "docker" in settings.toml, where
# commands run isolated with no network.

python bootstrap.py --no-panel
if ($LASTEXITCODE -eq 2) {
    Write-Host "`nDo the numbered steps above, then rerun .\start-agent.ps1" -ForegroundColor Yellow
    exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBootstrap failed - run 'python doctor.py' for the full verdict." -ForegroundColor Red
    exit 1
}

python loop.py check
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nFix the failing providers above (keys go in agent.env), then rerun." -ForegroundColor Yellow
    exit 1
}
Write-Host "`nAll providers OK - starting the panel and the loop." -ForegroundColor Green
Start-Process python -ArgumentList "ui.py"
python loop.py run
