"""Shared services: soft delete, restore and optimistic concurrency.

Every soft delete in the system goes through :func:`soft_delete_objects`
so who/when/batch are always recorded. Restore brings back exactly the
records that shared one delete_batch.
"""

import uuid

from django.db import transaction
from django.utils import timezone


class ConcurrentEditError(Exception):
    """Raised when the stored version differs from the form's version."""

    def __init__(self, changed_by_name, changed_at):
        self.changed_by_name = changed_by_name
        self.changed_at = changed_at
        super().__init__(
            f"This record was changed by {changed_by_name} at {changed_at}. "
            "Reload and try again."
        )


def soft_delete_objects(objs, user, reason=""):
    """Soft-delete a list of objects in one transaction, sharing one batch
    UUID. Returns the batch UUID. History records who made the change."""
    batch = uuid.uuid4()
    now = timezone.now()
    with transaction.atomic():
        for obj in objs:
            obj.is_deleted = True
            obj.deleted_at = now
            obj.deleted_by = user
            obj.delete_batch = batch
            obj._change_reason = reason
            obj.save()
    return batch


def restore_delete_batch(batch, user, models):
    """Restore every soft-deleted row sharing ``batch`` across ``models``.
    Returns the list of restored objects."""
    restored = []
    with transaction.atomic():
        for model in models:
            for obj in model.all_objects.filter(delete_batch=batch, is_deleted=True):
                obj.is_deleted = False
                obj.deleted_at = None
                obj.deleted_by = None
                obj.delete_batch = None
                obj._change_reason = "Restored from recycle bin"
                obj.save()
                restored.append(obj)
    return restored


def check_version(obj, form_version):
    """Compare a form's version against the locked row's version.

    Call inside a transaction after locking the row with
    select_for_update. Raises ConcurrentEditError on mismatch; the caller
    turns it into the friendly message:
    "This record was changed by NAME at TIME. Reload and try again."
    """
    if obj.version != form_version:
        changed_by = obj.updated_by
        name = (
            changed_by.get_full_name() or changed_by.username
            if changed_by
            else "another user"
        )
        when = timezone.localtime(obj.updated_at).strftime("%d-%m-%Y %H:%M")
        raise ConcurrentEditError(name, when)


def save_form_with_version(form, user, reason):
    """Save a bound ModelForm for an existing BaseModel row with
    optimistic concurrency: lock the row, compare versions, copy the
    form's fields onto the locked row, and save with the change reason.
    Raises ConcurrentEditError on a stale version. Edit-only (not for
    creates)."""
    instance = form.instance
    form_version = form.cleaned_data.get("version")
    with transaction.atomic():
        locked = instance.__class__.all_objects.select_for_update().get(
            pk=instance.pk
        )
        check_version(locked, form_version)
        updated = form.save(commit=False)
        for field in form.Meta.fields:
            setattr(locked, field, getattr(updated, field))
        locked.updated_by = user
        locked._change_reason = reason
        locked.save()
        return locked


def claim_form_token(user, token):
    """Atomically claim a create-form token. Call inside
    transaction.atomic, BEFORE creating the record: get_or_create
    blocks a concurrent twin on the unique token until the first
    transaction commits, then returns the existing row.

    Returns (record, is_new). An empty or malformed token means no
    protection (old forms, non-browser clients): (None, True) — the
    caller creates normally and records nothing."""
    if not token:
        return None, True
    try:
        uuid.UUID(str(token))
    except (ValueError, AttributeError):
        return None, True
    from core.models import SubmittedForm

    record, created = SubmittedForm.objects.get_or_create(
        token=str(token), user=user, defaults={"success_url": ""})
    return record, created


def finish_form_token(record, success_url):
    """Point a claimed token at the record it created, so a replay
    redirects to the original instead of creating a second one."""
    if record is not None:
        record.success_url = success_url
        record.save()
