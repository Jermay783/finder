# Finder private updates

The repository remains private. Finder uses the official GitHub CLI (`gh`) for authentication, not a token embedded in Finder.exe.

1. Install GitHub CLI on Windows: https://cli.github.com/
2. Run `gh auth login` once and sign into the GitHub account that has access to `Jermay783/finder`.
3. Build Finder.exe from the workflow, or download it from a private release.
4. Click **Проверить обновления**. Finder checks the latest private release and offers to download and replace its own EXE after exit.

The release must have a `Finder.exe` asset and a `vX.Y.Z` tag. The updater verifies the SHA-256 digest if GitHub supplies one. Do not install from unknown releases. This flow needs end-to-end Windows testing before being considered production-ready.

User search data stays in `%LOCALAPPDATA%\\USStoreFinder3` and is not overwritten by EXE replacement.
