"""Middleware: HTMX requests must never receive an HTML login page
inside a fragment. When Django redirects an HTMX request to login (session
expired), convert it to a full-page redirect via the HX-Redirect header.
"""

from django.http import HttpResponse
from django.shortcuts import resolve_url

from config import settings


class HtmxLoginRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx and response.status_code == 302:
            login_url = resolve_url(settings.LOGIN_URL)
            target = response.url
            if target.startswith(login_url):
                redirect_response = HttpResponse(status=200)
                redirect_response["HX-Redirect"] = target
                return redirect_response
        return response
