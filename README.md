# Finder

Private Windows application for finding online stores in the USA.

## Build
GitHub Actions → Build Finder for Windows → Run workflow. Requires app.py, core.py and requirements.txt in repository root. Once the build succeeds, download the Finder-Windows artifact containing Finder.exe.

## Releases
Pushing a version tag such as v3.3.0 triggers a Windows build and creates a private release with Finder.exe.

## Security
Never commit API keys, GitHub tokens, local databases or personal settings. Private GitHub Releases require authenticated access. Do not embed a GitHub token in the EXE.

## Current setup status
Build workflow configured; application source upload and first build still pending.
