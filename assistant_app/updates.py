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


def changes(revision="HEAD", since=None, limit=8):
    """Return commit dates and subjects from the installed checkout or fetched update."""
    ref = f"{since}..{revision}" if since else revision
    return [
        {"revision": short, "date": date, "summary": summary}
        for line in git("log", f"-{limit}", "--format=%h%x09%cs%x09%s", ref).splitlines()
        for short, date, summary in [line.split("\t", 2)]
    ]


def installed():
    try:
        return git("rev-parse", "HEAD", timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None


def installed_changes(revision, since):
    if not revision:
        return []
    try:
        if since and since != revision:
            git("merge-base", "--is-ancestor", since, revision, timeout=3)
            return changes(revision, since)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return changes(revision)
    except (OSError, subprocess.SubprocessError):
        return []


def available_changes(revision, installed_revision):
    if not revision or not installed_revision:
        return []
    try:
        try:
            git("cat-file", "-e", revision + "^{commit}")
        except subprocess.CalledProcessError:
            git("fetch", "--no-tags", "--no-write-fetch-head", REPOSITORY, BRANCH)
        git("merge-base", "--is-ancestor", installed_revision, revision)
        return changes(revision, installed_revision)
    except (OSError, subprocess.SubprocessError):
        return []
