from .models import Notification


def notify(recipient, title, message="", link=""):
    """Create one in-app notification. No-op (returns None) if recipient is
    None — callers may pass e.g. a class's unset instructor."""
    if recipient is None:
        return None
    return Notification.objects.create(recipient=recipient, title=title, message=message, link=link)


def notify_many(recipients, title, message="", link=""):
    return [notify(recipient, title, message, link) for recipient in recipients if recipient is not None]
