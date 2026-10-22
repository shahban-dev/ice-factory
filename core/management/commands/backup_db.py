"""Scheduled database backup: dump, compress, encrypt, store, upload
off-server, rotate old backups, and log the result.

Run daily at 02:00 Asia/Karachi from cron (see DEPLOYMENT.md):

    0 2 * * * /path/to/venv/bin/python /path/to/manage.py backup_db

Configuration (environment):
- BACKUP_DIR: where backups are kept (default: <project>/backups).
- BACKUP_ENCRYPTION_PASSPHRASE: encrypts the stored file with
  openssl AES-256-CBC. Without it, the file is stored compressed only
  and the log notes that it is unencrypted. In production (DEBUG off)
  an unencrypted backup is REFUSED unless --allow-unencrypted is
  passed — a database backup contains every customer, sale and salary,
  and must not sit on disk in the clear by accident.
- BACKUP_RCLONE_REMOTE: e.g. "b2:ice-factory-backups". When set, the
  file is also copied off-server with rclone.

Retention: the newest backup of each day for the last 30 days, plus the
newest backup of each of the last 12 calendar months. Everything else
in BACKUP_DIR is deleted.

Restore (see DEPLOYMENT.md for the full procedure):
    openssl enc -d -aes-256-cbc -pbkdf2 -in backup-....gz.enc -out backup.gz
    gunzip backup.gz
    pg_restore --clean --dbname=<db> backup.dump
"""

import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import BackupLog
from reports.backup import encrypt_bytes, make_database_dump

NAME_RE = re.compile(r"backup-(\d{4}-\d{2}-\d{2})-\d{6}\..*")


class Command(BaseCommand):
    help = "Back up the database: dump, compress, encrypt, upload, rotate, log."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-unencrypted", action="store_true",
            help="Store the backup unencrypted even when DEBUG is off. "
                 "Only for a deliberate, one-off decision.",
        )

    def handle(self, *args, **options):
        backup_dir = Path(
            os.environ.get("BACKUP_DIR", settings.BASE_DIR / "backups")
        )
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            passphrase = os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE", "")
            if (not passphrase and not settings.DEBUG
                    and not options["allow_unencrypted"]):
                raise CommandError(
                    "Refusing to store an unencrypted backup outside DEBUG "
                    "mode. Set BACKUP_ENCRYPTION_PASSPHRASE, or pass "
                    "--allow-unencrypted for a deliberate exception."
                )
            data, filename = make_database_dump()
            encrypted = False
            if passphrase:
                data = encrypt_bytes(data, passphrase)
                filename += ".enc"
                encrypted = True
            target = backup_dir / filename
            # Mode 600 from the moment the file is created: backups hold
            # the whole business, and must not be world-readable.
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            message = f"Saved {filename} ({len(data)} bytes)"
            if not encrypted:
                message += " — stored UNENCRYPTED (no passphrase set)"
            remote = os.environ.get("BACKUP_RCLONE_REMOTE", "")
            if remote:
                result = subprocess.run(
                    ["rclone", "copy", str(target), remote],
                    capture_output=True, timeout=900,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "rclone upload failed: "
                        f"{result.stderr.decode(errors='replace')[:300]}"
                    )
                message += f"; uploaded to {remote}"
            self._rotate(backup_dir)
            BackupLog.objects.create(
                kind=BackupLog.KIND_SCHEDULED, status=BackupLog.STATUS_SUCCESS,
                filename=filename, size_bytes=len(data), message=message,
            )
            self.stdout.write(self.style.SUCCESS(message))
        except Exception as exc:
            BackupLog.objects.create(
                kind=BackupLog.KIND_SCHEDULED, status=BackupLog.STATUS_FAILURE,
                message=str(exc),
            )
            raise

    def _rotate(self, backup_dir):
        """Keep the newest backup per day for 30 days, plus the newest
        backup per month for the last 12 months. Delete the rest."""
        now = timezone.localdate()
        files = []
        for path in backup_dir.iterdir():
            match = NAME_RE.match(path.name)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            files.append((path, day))
        keep = set()
        by_day = {}
        for path, day in files:
            by_day.setdefault(day, []).append(path)
        for day, paths in by_day.items():
            if (now - day).days <= 30:
                keep.add(max(paths, key=lambda p: p.stat().st_mtime))
        by_month = {}
        for path, day in files:
            by_month.setdefault((day.year, day.month), []).append(path)
        months = sorted(by_month.keys(), reverse=True)[:12]
        for key in months:
            keep.add(max(by_month[key], key=lambda p: p.stat().st_mtime))
        for path, _ in files:
            if path not in keep:
                path.unlink()
