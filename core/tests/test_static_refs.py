"""Every {% static %} reference in every template must resolve to a real
file. A wrong path fails silently in the browser (a blank chart, a
missing stylesheet) while the page still returns 200 — this test caught
the dashboard loading a Chart.js path that never existed."""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

STATIC_RE = re.compile(r"""{% static ['"]([^'"]+)['"] %}""")


class StaticReferencesTests(SimpleTestCase):
    def test_all_static_references_resolve(self):
        templates_dir = Path(settings.BASE_DIR) / "templates"
        missing = []
        for path in templates_dir.rglob("*.html"):
            for ref in STATIC_RE.findall(path.read_text()):
                if finders.find(ref) is None:
                    missing.append(f"{path.relative_to(settings.BASE_DIR)}: {ref}")
        self.assertEqual(missing, [])
