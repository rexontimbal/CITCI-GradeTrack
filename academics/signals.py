from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_student_profile(sender, instance, created, **kwargs):
    """Every STUDENT user automatically gets an (initially empty)
    StudentProfile — admin fills in program/year/section afterwards."""
    if created and instance.role == User.Role.STUDENT:
        from .models import StudentProfile

        StudentProfile.objects.get_or_create(user=instance)
