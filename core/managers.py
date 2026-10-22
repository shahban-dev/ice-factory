"""Query managers for soft-deletable models.

The default manager hides soft-deleted rows everywhere (lists, reports,
allocations). ``all_objects`` is used by the recycle bin and by restore.
"""

from django.db import models


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)
