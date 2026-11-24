"""Check the official Git repository and install only fast-forward updates."""
import os
from pathlib import Path
import subprocess


REPOSITORY = "https://github.com/PixelDrennen/GPTLinuxAssistant.git"
BRANCH = "refs/heads/main"
ROOT = Path(__file__).resolve().parents[1]
RESTART = 42


def git(*args, timeout=20):
    result = subprocess.run(["git", "-C", str(ROOT), *args], text=True, capture_output=True,
                            timeout=timeout, check=True,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return result.stdout.strip()


def check():
    if not (ROOT / ".git").exists():
        return None
    local = git("rev-parse", "HEAD")
    remote = git("ls-remote", "--exit-code", REPOSITORY, BRANCH).split()[0]
    if remote == local:
        return None
    try:
        git("merge-base", "--is-ancestor", remote, local)
    except subprocess.CalledProcessError:
        return remote
    return None


def install(expected):
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("This checkout has local changes. Commit or stash them before updating.")
    git("fetch", "--no-tags", REPOSITORY, BRANCH, timeout=90)
    fetched = git("rev-parse", "FETCH_HEAD")
    if fetched != expected:
        raise ValueError("The available update changed. Check for updates again.")
    git("merge", "--ff-only", fetched)
