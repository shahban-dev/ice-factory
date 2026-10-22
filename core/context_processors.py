"""Template context: factory settings available in every template."""

from django.db import OperationalError, ProgrammingError

from core.models import get_settings


def factory_settings(request):
    try:
        factory = get_settings()
    except (OperationalError, ProgrammingError):
        # Database not migrated yet (e.g. first deploy before migrate):
        # pages must still render instead of crashing.
        factory = None
    return {"factory": factory}
