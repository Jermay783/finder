"""Public GitHub Releases updater for Finder (no GitHub CLI required)."""
import hashlib
import datetime
import time
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading

import requests

REPO = "Jermay783/finder"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "Finder-Updater/3.3"}
VERSION = "3.5.0"


def current_version():
    return VERSION


def version_tuple(tag):
    """Compare numeric release versions; ignore an optional leading v."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(tag).strip())
    if not match:
        raise ValueError("Unsupported version tag: " + str(tag))
    return tuple(map(int, match.groups()))


def latest_release():
    response = requests.get(API, headers=HEADERS, timeout=25)
    if response.status_code == 404:
        raise RuntimeError("Пока нет опубликованных GitHub Releases")
    response.raise_for_status()
    return response.json()


def check_update():
    release = latest_release()
    tag = release.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current_version()):
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == "Finder.exe"), None)
    if not asset:
        raise RuntimeError("В новом релизе отсутствует Finder.exe")
    return release, asset


def download_verified(release, asset):
    url = asset.get("browser_download_url", "")
    if not url.startswith(f"https://github.com/{REPO}/releases/download/"):
        raise RuntimeError("Unexpected release download URL")
    folder = pathlib.Path(tempfile.mkdtemp(prefix="finder-update-"))
    binary = folder / "Finder.exe"
    sha = hashlib.sha256()
    try:
        with requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            with binary.open("wb") as out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
                        sha.update(chunk)
        if binary.stat().st_size == 0:
            raise RuntimeError("Downloaded file is empty")
        expected_size = asset.get("size")
        if expected_size is not None and binary.stat().st_size != expected_size:
            raise RuntimeError("Downloaded update size mismatch")
        digest = asset.get("digest")
        if digest:
            algorithm, separator, expected = digest.partition(":")
            if not separator or algorithm.lower() != "sha256":
                raise RuntimeError("Unsupported release checksum")
            if sha.hexdigest().lower() != expected.lower():
                raise RuntimeError("Downloaded update checksum mismatch")
        if binary.open("rb").read(2) != b"MZ":
            raise RuntimeError("Downloaded file is not a Windows executable")
        return binary
    except Exception:
        binary.unlink(missing_ok=True)
        raise


def install_after_exit(downloaded, target=None):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic replacement only works in Finder.exe")
    target = pathlib.Path(target or sys.executable).resolve()
    downloaded = pathlib.Path(downloaded).resolve()
    if not downloaded.is_file():
        raise FileNotFoundError(str(downloaded))
    pid = os.getpid()
    script = downloaded.parent / "replace.ps1"
    script.write_text(r"""param([int]$FinderProcessId,[string]$Source,[string]$Destination,[string]$ExpectedHash)
$ErrorActionPreference = 'Stop'
$log = Join-Path $env:LOCALAPPDATA 'Finder/updater.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
function Log([string]$message) { Add-Content -LiteralPath $log -Value ("$(Get-Date -Format o) " + $message) }
try {
  Log "Started update: $Source -> $Destination"
  $deadline = (Get-Date).AddSeconds(90)
  while (Get-Process -Id $FinderProcessId -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $deadline) { throw "Finder did not exit within 90 seconds" }
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path -LiteralPath $Source)) { throw "Downloaded EXE missing" }
  $actual = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $ExpectedHash.ToLowerInvariant()) { throw "Downloaded EXE checksum mismatch" }
  $backup = "$Destination.old"
  if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
  if (Test-Path -LiteralPath $Destination) { Move-Item -LiteralPath $Destination -Destination $backup -Force }
  try {
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    $installed = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($installed -ne $ExpectedHash.ToLowerInvariant()) { throw "Installed EXE checksum mismatch" }
  } catch {
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Force }
    if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $Destination -Force }
    throw
  }
  Log "Update installed successfully"
  $marker = Join-Path $env:LOCALAPPDATA 'Finder/update-success.txt'
  Set-Content -LiteralPath $marker -Value $ExpectedHash -Encoding ascii
  Start-Process -FilePath $Destination -WorkingDirectory (Split-Path $Destination)
  Log "Restart requested"
} catch {
  Log ("FAILED: " + $_.Exception.ToString())
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show("Не удалось установить обновление Finder. Журнал: $log" + [Environment]::NewLine + $_.Exception.Message, "Finder - ошибка обновления") | Out-Null
  exit 1
}
""", encoding="utf-8-sig")
    expected_hash = hashlib.sha256(downloaded.read_bytes()).hexdigest()
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    # Persist diagnostics before starting the helper, so even startup failures are visible.
    log_dir = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "Finder"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "updater.log"
    def log(message):
        with log_path.open("a", encoding="utf-8") as out:
            out.write(f"{datetime.datetime.now().isoformat()} [launcher] {message}\n")
    log(f"Prepared update: pid={pid} source={downloaded} destination={target}")
    try:
        proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-FinderProcessId", str(pid), "-Source", str(downloaded), "-Destination", str(target),
         "-ExpectedHash", expected_hash],
        creationflags=flags, close_fds=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log(f"PowerShell helper launched: pid={proc.pid}")
        time.sleep(1.0)
        code = proc.poll()
        if code is not None:
            log(f"PowerShell helper exited prematurely: code={code}")
            raise RuntimeError(f"Установщик завершился до закрытия Finder (код {code}). Журнал: {log_path}")
    except Exception as exc:
        log(f"Failed to launch helper: {exc}")
        raise


def update_async(callback):
    def work():
        try:
            update = check_update()
            callback("available", update[0]["tag_name"]) if update else callback("up-to-date", None)
        except Exception as exc:
            callback("error", str(exc))
    threading.Thread(target=work, daemon=True).start()
