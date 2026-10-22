"""Login lockout: 5 failed attempts lock the account for 15 minutes,
per username + IP, honouring X-Forwarded-For behind the proxy."""

from django.test import TestCase, override_settings
from django.urls import reverse

from core.tests.helpers import make_admin


@override_settings(AXES_ENABLED=True)
class AxesLockoutTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.url = reverse("login")

    def _attempt(self, password, ip="10.0.0.1"):
        return self.client.post(
            self.url,
            {"username": "admin", "password": password},
            HTTP_X_FORWARDED_FOR=ip,
        )

    def test_five_failures_lock_the_account(self):
        for _ in range(5):
            self._attempt("wrong-password")
        # Even the right password is refused while locked (429 from axes).
        response = self._attempt("TestPassword123")
        self.assertEqual(response.status_code, 429)

    def test_lockout_is_per_ip(self):
        for _ in range(5):
            self._attempt("wrong-password", ip="10.0.0.1")
        # A different IP is not locked out.
        response = self._attempt("TestPassword123", ip="10.0.0.2")
        self.assertNotEqual(response.status_code, 429)

    def test_success_resets_the_counter(self):
        for _ in range(4):
            self._attempt("wrong-password")
        # A success clears the failure count.
        response = self._attempt("TestPassword123")
        self.assertEqual(response.status_code, 302)
        # Four more failures do not lock (the counter restarted).
        for _ in range(4):
            self._attempt("wrong-password")
        response = self._attempt("TestPassword123")
        self.assertEqual(response.status_code, 302)
