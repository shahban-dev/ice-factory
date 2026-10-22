"""Database dump helper, shared by the backup command and the manual
download. PostgreSQL: pg_dump custom format. SQLite (local dev only):
a copy of the database file. The result is always gzip-compressed."""

import gzip
import io
import os
import subprocess
from datetime import datetime

from django.conf import settings
from django.utils import timezone


def _postgres_params():
    """Connection pieces for pg_dump, from DATABASE_URL or PG* env vars."""
    db = settings.DATABASES["default"]
    if db["ENGINE"] != "django.db.backends.postgresql":
        return None
    return {
        "host": db.get("HOST") or os.environ.get("PGHOST", ""),
        "port": str(db.get("PORT") or os.environ.get("PGPORT", "")),
        "user": db.get("USER") or os.environ.get("PGUSER", ""),
        "password": db.get("PASSWORD") or os.environ.get("PGPASSWORD", ""),
        "name": db.get("NAME") or os.environ.get("PGDATABASE", ""),
    }


def make_database_dump():
    """Return (gzip bytes, filename) for a fresh dump of the live database."""
    stamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d-%H%M%S")
    pg = _postgres_params()
    if pg is not None:
        env = dict(os.environ)
        if pg["password"]:
            env["PGPASSWORD"] = pg["password"]
        cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges"]
        if pg["host"]:
            cmd += ["--host", pg["host"]]
        if pg["port"]:
            cmd += ["--port", pg["port"]]
        if pg["user"]:
            cmd += ["--username", pg["user"]]
        cmd.append(pg["name"])
        result = subprocess.run(cmd, capture_output=True, env=env, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed: {result.stderr.decode(errors='replace')[:500]}"
            )
        raw = result.stdout
        filename = f"backup-{stamp}.dump.gz"
    else:
        db_path = settings.DATABASES["default"]["NAME"]
        with open(db_path, "rb") as fh:
            raw = fh.read()
        filename = f"backup-{stamp}.sqlite3.gz"
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer) as gz:
        gz.write(raw)
    return buffer.getvalue(), filename


def encrypt_bytes(data, passphrase):
    """AES-256-CBC encryption via openssl (pbkdf2). Returns encrypted bytes."""
    result = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-pass", f"pass:{passphrase}"],
        input=data, capture_output=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"openssl failed: {result.stderr.decode(errors='replace')[:300]}"
        )
    return result.stdout
