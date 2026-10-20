#!/usr/bin/env python3
"""Scan this draft's release files for accidental private content."""

from pathlib import Path
import hashlib
import ipaddress
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "__pycache__"}
TEXT_SUFFIXES = {".md", ".py", ".json", ".xcstrings", ".html", ".svg", ".yaml", ".yml", ".txt", ""}
PATTERNS = {
    "personal absolute path": re.compile(r"/(?:Users|home)/[^/\s]+/|[A-Z]:\\Users\\[^\\\s]+\\"),
    "email address": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "credential literal": re.compile(r'''(?i)(?:api[_-]?key|secret|password|bearer)["']?\s*[=:]\s*["'][^\s"']{8,}["']'''),
    "access token": re.compile(r"(?:hf_|ghp_|github_pat_|sk-)[A-Za-z0-9_\-]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def main():
    errors = []
    manifest = json.loads((ROOT / "release-files.json").read_text())
    allowed = set(manifest["files"])
    reviewed_media = manifest["reviewedMedia"]
    paths = [p for p in ROOT.rglob("*") if (p.is_file() or p.is_symlink()) and not (set(p.relative_to(ROOT).parts) & EXCLUDED)]
    actual = {p.relative_to(ROOT).as_posix() for p in paths}
    for relative in sorted(actual - allowed):
        errors.append((relative, "file is outside the reviewed release list"))
    for relative in sorted(allowed - actual):
        errors.append((relative, "reviewed release file is missing"))
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            errors.append((relative, "symbolic link requires explicit review"))
            continue
        if "work" in path.relative_to(ROOT).parts:
            errors.append((relative, "runtime cache must be excluded from the public copy"))
            continue
        if path.name == ".DS_Store" or path.name.startswith(".env") or path.suffix in {".log", ".db", ".sqlite", ".pem", ".key"}:
            errors.append((relative, "private or runtime file"))
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".mp4"} and relative not in reviewed_media:
            errors.append((relative, "unreviewed media"))
        if relative in reviewed_media and hashlib.sha256(path.read_bytes()).hexdigest() != reviewed_media[relative]["sha256"]:
            errors.append((relative, "media changed since review; inspect and update the manifest"))
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    errors.append((relative, label))
            for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
                try:
                    address = ipaddress.ip_address(candidate)
                    if address.is_private and not address.is_loopback:
                        errors.append((relative, "private network address"))
                        break
                except ValueError:
                    pass
    for path, reason in errors:
        print(f"REVIEW: {path}: {reason}")
    if errors:
        return 1
    print(f"PASS: {len(paths)} files scanned. Review image pixels and repository history before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
