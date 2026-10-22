"""Real client IP for login lockout, behind the single Nginx proxy.

Nginx is configured with ``proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for``, which APPENDS the TCP peer's address to
whatever the client sent. So the LAST entry of the header is the address
Nginx actually saw — the real client — while earlier entries may be
client-spoofed. Without a proxy (local development) there is no header
and REMOTE_ADDR is used directly.

This replaces django-ipware (not installed) so axes honours the header
at all; without a callable, axes silently falls back to REMOTE_ADDR and
every visitor behind Nginx shares one lockout bucket.
"""


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        entries = [part.strip() for part in forwarded.split(",") if part.strip()]
        if entries:
            return entries[-1]
    return request.META.get("REMOTE_ADDR")
