from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base for created_at/updated_at — every new model extends this."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
