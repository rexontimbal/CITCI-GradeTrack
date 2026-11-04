"""Logs an AuditLog row whenever django-axes locks an account out (Phase 8
part A). No admin `actor` for this event — it's system-originated."""

from axes.signals import user_locked_out
from django.dispatch import receiver

from .audit import log_audit
from .models import AuditLog, User


@receiver(user_locked_out)
def on_user_locked_out(sender, request, username, ip_address, **kwargs):
    target_user = User.objects.filter(username=username).first()
    log_audit(None, AuditLog.Action.ACCOUNT_LOCKED_OUT, target_user, username=username, ip_address=ip_address)
