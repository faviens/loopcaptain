"""Which files of a watched repository the board opens, and which it never shows."""

from __future__ import annotations

import fnmatch
import os
import stat
from pathlib import Path

from fastapi import HTTPException

#: The largest file the board renders. A round's plan or review is a few kilobytes.
MAX_FILE_BYTES = 400_000


#: Never shown, though inside the repository: git's own folder and the folders and files tools keep
#: keys, tokens and passwords in. A part of a path that equals one of these refuses the whole path.
PRIVATE_PARTS = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".azure",
        ".gcloud",
        ".gnupg",
        ".password-store",
        ".docker",
        ".dockercfg",
        ".kube",
        "kubeconfig",
        ".terraform",
        ".vault-token",
        ".netrc",
        "_netrc",
        ".npmrc",
        ".yarnrc",
        ".yarnrc.yml",
        ".pypirc",
        ".git-credentials",
        ".boto",
        ".s3cfg",
        ".pgpass",
        ".my.cnf",
        ".mylogin.cnf",
        ".htpasswd",
        "htpasswd",
        "token.json",
        "token.pickle",
        "auth.json",
        "secret",
        "secrets",
    }
)


#: Name patterns of files that hold keys or credentials, matched against every part of the path.
#: This is a block-list of names: it knows nothing of what a file holds (see SECURITY.md).
PRIVATE_PATTERNS = (
    # environment files
    ".env*",
    "*.env",
    "*.env.*",
    # keys, certificates with keys, key stores, password stores
    "*.pem",
    "*.pem.*",
    "*.key",
    "*.key.*",
    "*.ppk",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "*.keytab",
    "*.kdbx",
    "*.kdb",
    "*.gpg",
    "*.pgp",
    "*.ovpn",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "id_xmss*",
    "*_rsa",
    "*_dsa",
    "*_ecdsa",
    "*_ed25519",
    # infrastructure state and variables
    "*.tfstate",
    "*.tfstate.*",
    "*.tfvars",
    "*.tfvars.json",
    # credentials and secrets by name
    "credentials*",
    "*credentials.*",
    "*-credentials*",
    "*_credentials*",
    "secrets*",
    "secret.*",
    "*.secret",
    "*.secrets",
    "*-secret.*",
    "*_secret.*",
    "*-secrets.*",
    "*_secrets.*",
    "client_secret*",
    "service-account*.json",
    "service_account*.json",
    "serviceaccount*.json",
    "*-sa-key*.json",
    "*_sa_key*.json",
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


def read_bounded(repo: Path, target: Path, limit: int = MAX_FILE_BYTES) -> tuple[int, bytes | None]:
    """The size and the bytes of a file `inside` has passed; no bytes for one larger than `limit`.

    Between the check of a path and the reading, a loop could put a symbolic link in the place of
    a folder or of the file, and the board would read whatever it leads to. So the file is opened
    step by step from the repository's root, each part without following a link, and a part that
    has turned into a link since is refused. Raises `OSError` where the file cannot be opened so.
    """
    root = repo.resolve()
    parts = target.relative_to(root).parts
    if not parts:
        raise IsADirectoryError(str(target))
    folder = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            deeper = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = deeper
        # O_NONBLOCK: a name that has become a pipe must not hold the page.
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    finally:
        os.close(folder)
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode):
            raise OSError(f"{target.name} is not a file")
        return status.st_size, (handle.read(limit) if status.st_size <= limit else None)
