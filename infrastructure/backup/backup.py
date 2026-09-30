"""Consistent backup / restore of the HOP metadata database and object store.

    python infrastructure/backup/backup.py backup  [--out backups/]
    python infrastructure/backup/backup.py restore BACKUP_DIR [--force]
    python infrastructure/backup/backup.py verify  BACKUP_DIR

SQLite is copied with the online backup API (safe while the app runs). Postgres uses pg_dump / pg_restore,
which must be on PATH. The object store is archived as a tarball; every file is listed in a SHA-256
manifest so a restore can prove that raw evidence payloads are byte-identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from hop.platform.settings import Settings  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_path(url: str) -> Path:
    return Path(url.replace("sqlite:///", "", 1))


def backup(settings: Settings, out_root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = out_root / f"hop-backup-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    url = settings.database_url
    if url.startswith("sqlite"):
        src = sqlite3.connect(_sqlite_path(url))
        dst = sqlite3.connect(out / "hop.db")
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        db_file = "hop.db"
    elif url.startswith("postgresql"):
        dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
        subprocess.run(["pg_dump", "--format=custom", f"--file={out / 'hop.pgdump'}", dsn], check=True)
        db_file = "hop.pgdump"
    else:
        raise SystemExit(f"unsupported DATABASE_URL scheme: {url.split('://')[0]}")

    objects = settings.object_store_dir
    files = sorted(p for p in objects.rglob("*") if p.is_file()) if objects.exists() else []
    with tarfile.open(out / "objects.tar.gz", "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=str(p.relative_to(objects)))
    manifest = {
        "created_at": stamp,
        "database": {"scheme": url.split("://")[0], "file": db_file, "sha256": _sha256(out / db_file)},
        "objects": {str(p.relative_to(objects)): _sha256(p) for p in files},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out


def verify(backup_dir: Path) -> list[str]:
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    problems = []
    db = manifest["database"]
    if _sha256(backup_dir / db["file"]) != db["sha256"]:
        problems.append(f"database dump {db['file']} hash mismatch")
    with tarfile.open(backup_dir / "objects.tar.gz", "r:gz") as tar:
        seen = {}
        for member in tar.getmembers():
            fh = tar.extractfile(member)
            if fh is not None:
                seen[member.name] = hashlib.sha256(fh.read()).hexdigest()
    for name, digest in manifest["objects"].items():
        if seen.get(name) != digest:
            problems.append(f"object {name} missing or altered")
    return problems


def restore(settings: Settings, backup_dir: Path, force: bool) -> None:
    problems = verify(backup_dir)
    if problems:
        raise SystemExit("refusing to restore a damaged backup:\n  " + "\n  ".join(problems))
    url = settings.database_url
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    if url.startswith("sqlite"):
        target = _sqlite_path(url)
        if target.exists() and not force:
            raise SystemExit(f"{target} exists; pass --force to overwrite")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backup_dir / manifest["database"]["file"], target)
    else:
        dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
        cmd = ["pg_restore", "--clean", "--if-exists", "--no-owner", f"--dbname={dsn}"]
        subprocess.run([*cmd, str(backup_dir / manifest["database"]["file"])], check=True)
    objects = settings.object_store_dir
    if objects.exists() and any(objects.iterdir()) and not force:
        raise SystemExit(f"{objects} is not empty; pass --force to overwrite")
    objects.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup_dir / "objects.tar.gz", "r:gz") as tar:
        tar.extractall(objects, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--out", type=Path, default=Path("backups"))
    r = sub.add_parser("restore")
    r.add_argument("backup_dir", type=Path)
    r.add_argument("--force", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("backup_dir", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "backup":
        print(backup(settings, args.out))
    elif args.command == "verify":
        problems = verify(args.backup_dir)
        print("backup OK" if not problems else "\n".join(problems))
        raise SystemExit(1 if problems else 0)
    else:
        restore(settings, args.backup_dir, args.force)
        print(f"restored {args.backup_dir}; run `hop audit verify` to confirm the audit chain")


if __name__ == "__main__":
    main()
