"""Which files of a watched repository the board opens, and which it never shows."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from fastapi import HTTPException

#: The largest file the board renders. A round's plan or review is a few kilobytes.
MAX_FILE_BYTES = 400_000


#: Never shown, though inside the repository: git's own folder and files that hold secrets.
PRIVATE_PARTS = frozenset(
    {".git", ".ssh", ".aws", ".gnupg", ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".docker", ".kube"}
)


#: Name patterns of files that hold keys or credentials, matched against every part of the path.
PRIVATE_PATTERNS = (
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "*.tfstate",
    "*.tfstate.*",
    ".htpasswd",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "credentials*.json",
    "service-account*.json",
    "*-sa-key*.json",
    "secrets.*",
)


#: The board shows a file's content only for these; anything else is named, not opened.
TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        ".log",
        ".py",
        ".sh",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".sql",
        ".r",
        ".tex",
        ".bib",
        ".diff",
        ".patch",
    }
)


def is_private(part: str) -> bool:
    """Whether one part of a path names git's folder or a file that holds keys or credentials."""
    lowered = part.lower()
    return lowered in PRIVATE_PARTS or any(
        fnmatch.fnmatchcase(lowered, pattern) for pattern in PRIVATE_PATTERNS
    )


def inside(repo: Path, relative: str) -> Path:
    """A path inside the repository, or 404: no link on the board may lead out of it."""
    root = repo.resolve()
    try:
        target = (root / relative).resolve()
        found = bool(relative) and target.is_relative_to(root) and target.is_file()
    except (ValueError, OSError):  # a null byte, a name too long
        found = False
    if not found:
        raise HTTPException(404, "no such file in this repository")
    parts = target.relative_to(root).parts
    if any(is_private(part) for part in parts):
        raise HTTPException(404, "no such file in this repository")
    return target
