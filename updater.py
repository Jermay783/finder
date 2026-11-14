"""Private GitHub Releases updater using GitHub CLI authentication.

No tokens are stored in Finder. Requires `gh auth login` once on the PC.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

REPO = 'Jermay783/finder'


def latest_release():
    p = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/latest'], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(p.stdout)


def current_version():
    return '3.3.0'


def check_update():
    release = latest_release()
    tag = release['tag_name'].lstrip('v')
    if tag == current_version():
        return None
    asset = next((a for a in release.get('assets', []) if a['name'] == 'Finder.exe'), None)
    if not asset:
        raise RuntimeError('Release has no Finder.exe asset')
    return release, asset


def download_verified(release, asset):
    folder = pathlib.Path(tempfile.mkdtemp(prefix='finder-update-'))
    subprocess.run(['gh', 'release', 'download', release['tag_name'], '-R', REPO, '-p', 'Finder.exe', '-D', str(folder)], check=True, timeout=300)
    binary = folder / 'Finder.exe'
    digest = asset.get('digest')
    if digest:
        algorithm, expected = digest.split(':', 1)
        if algorithm.lower() != 'sha256':
            raise RuntimeError('Unsupported release digest algorithm')
        actual = hashlib.sha256(binary.read_bytes()).hexdigest()
        if actual.lower() != expected.lower():
            raise RuntimeError('Downloaded update checksum mismatch')
    return binary


def install_after_exit(downloaded, target=None):
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('Automatic replacement only works in packaged Finder.exe')
    target = pathlib.Path(target or sys.executable).resolve()
    downloaded = pathlib.Path(downloaded).resolve()
    # A detached PowerShell process waits for Finder to exit, then replaces the executable.
    pid = os.getpid()
    script = downloaded.parent / 'replace.ps1'
    script.write_text('''param([int]$ParentPid,[string]$Source,[string]$Destination)
while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 500 }
$backup = "$Destination.old"
try {
  if (Test-Path $backup) { Remove-Item -LiteralPath $backup -Force }
  if (Test-Path $Destination) { Move-Item -LiteralPath $Destination -Destination $backup -Force }
  Copy-Item -LiteralPath $Source -Destination $Destination -Force
  Start-Process -FilePath $Destination
} catch {
  if ((-not (Test-Path $Destination)) -and (Test-Path $backup)) { Move-Item -LiteralPath $backup -Destination $Destination }
  throw
}
''', encoding='utf-8')
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
    subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-ParentPid', str(pid), '-Source', str(downloaded), '-Destination', str(target)], creationflags=flags, close_fds=True)


def update_async(callback):
    def work():
        try:
            update = check_update()
            if not update:
                callback('up-to-date', None)
                return
            release, asset = update
            callback('available', release['tag_name'])
        except Exception as exc:
            callback('error', str(exc))
    threading.Thread(target=work, daemon=True).start()
