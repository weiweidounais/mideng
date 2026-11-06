"""Check Git's index or tracked tree without printing credential values (stdlib only).

This is a small local guard, complemented by Gitleaks in CI and release audits.
It never scans ignored runtime folders or uploads file contents.
"""
import argparse
from pathlib import PurePosixPath
import re
import subprocess
import sys

PATTERNS = [
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("provider key", re.compile(rb"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{24,}\b")),
    ("AWS key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Feishu credential", re.compile(rb"\b(?:u|t|a)-[A-Za-z0-9]{32,}\b")),
]
PLACEHOLDERS = ("replace-", "your-", "example", "placeholder", "test-", "fixture", "dummy", "<", "${")
ASSIGNMENT = re.compile(r'''(?ix)(?:api[_-]?key|access[_-]?secret|client[_-]?secret|secret[_-]?key|(?:admin|manager|postgres)[_-]?password)\s*["']?\s*[:=]\s*["']([^"'\r\n]{16,})["']''')


def git(*args):
    return subprocess.check_output(["git", *args])


def forbidden_path(name):
    p = PurePosixPath(name)
    if p.name in (".env.example", ".env.compose.example"):
        return False
    return (p.name == ".env" or p.name.startswith(".env.") or
            p.name in ("bootstrap-passwords.json", "credentials.json", ".state.json", ".登录信息.txt") or
            p.suffix.lower() in (".pem", ".key", ".p12", ".pfx", ".log", ".sqlite", ".sqlite3", ".db") or
            any(part in (".runtime", "backups", "private") for part in p.parts))


def findings(name, data):
    if forbidden_path(name):
        yield "private runtime/credential filename"
    if b"\0" in data[:8000]:
        return  # Binary screenshots are checked separately in release review.
    for label, pattern in PATTERNS:
        if pattern.search(data):
            yield label
    # Test suites intentionally contain synthetic credential values, not live tokens.
    if not name.startswith(("backend/tests/", "frontend/scripts/")):
        for match in ASSIGNMENT.finditer(data.decode("utf-8", errors="replace")):
            value = match.group(1)
            if not any(p in value.lower() for p in PLACEHOLDERS) and not any(x in value for x in (" ", "(", ")")):
                yield "possible hardcoded credential assignment"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="inspect all files in the index, including unchanged tracked files")
    args = parser.parse_args()
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
    problems = []
    for name in filter(None, names):
        try:
            data = git("show", ":" + name) if args.staged else open(name, "rb").read()
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        problems.extend((name, label) for label in findings(name, data))
    for name, label in problems:
        print(f"BLOCKED: {name}: {label}")
    print(f"Credential guard: {len(problems)} findings; values are never printed.")
    return bool(problems)


if __name__ == "__main__":
    sys.exit(main())
