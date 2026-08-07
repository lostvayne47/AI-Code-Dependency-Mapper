"""Git transport only. Repository files are not opened or analyzed here."""
from __future__ import annotations
import hashlib, re, subprocess
from pathlib import Path
from fastapi import HTTPException

CACHE_ROOT = Path(__file__).resolve().parents[1] / ".repo-cache"
MAX_REPOSITORY_BYTES = 200 * 1024 * 1024
URL_PATTERN = re.compile(r"^(https://[^\s]+|git@[^\s:]+:[^\s]+)$")

def _validate_url(url: str) -> str:
    url = url.strip().removesuffix("/")
    if not URL_PATTERN.match(url) or "\n" in url or "\r" in url or ("://" in url and "@" in url.removeprefix("https://")):
        raise HTTPException(400, "Enter a clean HTTPS or SSH Git remote URL.")
    return url

def _run(args: list[str], cwd: Path | None = None) -> str:
    try: result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=120)
    except FileNotFoundError as error: raise HTTPException(500, "Git is not installed or available on PATH.") from error
    except subprocess.TimeoutExpired as error: raise HTTPException(504, "Git operation timed out.") from error
    if result.returncode:
        raise HTTPException(400, result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Git operation failed.")
    return result.stdout

def list_branches(url: str) -> tuple[str, list[str]]:
    url = _validate_url(url)
    branches = sorted(line.split("refs/heads/", 1)[1] for line in _run(["git", "ls-remote", "--heads", url]).splitlines() if "refs/heads/" in line)
    if not branches: raise HTTPException(404, "No remote branches were found.")
    return url, branches

def _size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

def checkout_latest(url: str, branch: str) -> tuple[str, str, str]:
    url = _validate_url(url)
    if not branch or branch.startswith("-") or "\x00" in branch: raise HTTPException(400, "Invalid branch name.")
    key = hashlib.sha256(url.encode()).hexdigest()[:16]; repo = CACHE_ROOT / key; CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _run(["git", "clone", "--no-checkout", "--filter=blob:limit=2m", "--single-branch", "--branch", branch, url, str(repo)])
    else:
        _run(["git", "remote", "set-url", "origin", url], repo); _run(["git", "fetch", "origin", branch], repo)
    if _size(repo) > MAX_REPOSITORY_BYTES: raise HTTPException(413, "Repository cache exceeds the 200 MB intake limit.")
    _run(["git", "checkout", "--force", "-B", branch, f"origin/{branch}"], repo)
    return key, branch, _run(["git", "rev-parse", "HEAD"], repo).strip()
