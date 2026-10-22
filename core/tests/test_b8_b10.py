"""B8: backup refusal, file mode, stale-backup banner. B10: config safety."""

import os
import stat
import tempfile
from unittest import mock

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import BackupLog
from core.tests.helpers import make_admin


class BackupRefusalTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_patch = mock.patch.dict(os.environ, {
            "BACKUP_DIR": self.tmp.name,
            "BACKUP_ENCRYPTION_PASSPHRASE": "",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_refuses_unencrypted_backup_in_production(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command("backup_db")
        failure = BackupLog.objects.filter(
            status=BackupLog.STATUS_FAILURE).first()
        self.assertIsNotNone(failure)

    def test_allow_flag_writes_mode_600_file(self):
        with override_settings(DEBUG=False):
            with mock.patch(
                "core.management.commands.backup_db.make_database_dump",
                return_value=(b"fake-dump", "backup-2026-10-22-120000.gz"),
            ):
                call_command("backup_db", allow_unencrypted=True)
        files = os.listdir(self.tmp.name)
        self.assertEqual(len(files), 1)
        mode = stat.S_IMODE(os.stat(os.path.join(self.tmp.name, files[0])).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertTrue(BackupLog.objects.filter(
            status=BackupLog.STATUS_SUCCESS).exists())


class DashboardBackupBannerTests(TestCase):
    def setUp(self):
        self.client.force_login(make_admin())

    def test_banner_when_no_backup_at_all(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "No successful backup")

    def test_banner_when_last_backup_is_stale(self):
        log = BackupLog.objects.create(
            kind=BackupLog.KIND_SCHEDULED, status=BackupLog.STATUS_SUCCESS,
            filename="backup-old.gz", size_bytes=10, message="ok")
        BackupLog.objects.filter(pk=log.pk).update(
            created_at=timezone.now() - timezone.timedelta(hours=37))
        response = self.client.get(reverse("home"))
        self.assertContains(response, "No successful backup")

    def test_no_banner_when_backup_is_fresh(self):
        BackupLog.objects.create(
            kind=BackupLog.KIND_SCHEDULED, status=BackupLog.STATUS_SUCCESS,
            filename="backup-new.gz", size_bytes=10, message="ok")
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "No successful backup")


class ConfigSafetyTests(TestCase):
    def test_local_hosts_allowed_with_debug(self):
        from config.settings import _is_local_host

        self.assertTrue(_is_local_host("localhost"))
        self.assertTrue(_is_local_host("127.0.0.1"))
        self.assertTrue(_is_local_host("192.168.1.5"))  # phone on local Wi-Fi
        self.assertFalse(_is_local_host("ice.example.com"))
        self.assertFalse(_is_local_host("8.8.8.8"))
        self.assertFalse(_is_local_host("*"))

    def test_env_example_defaults_to_debug_off(self):
        example = (settings.BASE_DIR / ".env.example").read_text()
        self.assertIn("DEBUG=False", example)
