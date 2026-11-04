from django.db import models

from core.models import TimeStampedModel


class InstitutionSettings(TimeStampedModel):
    """Singleton (always pk=1) — the header/signatory info every report
    (PDF or Excel) pulls from, instead of hardcoding it in templates."""

    school_name = models.CharField(max_length=200, default="CANDELARIA INSTITUTE OF TECHNOLOGY OF CABADBARAN, INC.")
    sub_line = models.CharField(
        max_length=200, blank=True, default="(FORMERLY CANDELARIA INSTITUTE OF CABADBARAN, INC.)"
    )
    address = models.CharField(max_length=200, blank=True, default="8605 Funcion Street, Cabadbaran City")
    department = models.CharField(max_length=150, blank=True, default="College Department")
    logo = models.ImageField(
        upload_to="institution/",
        blank=True,
        help_text="Leave blank to use the default CITCI seal (static/img/citci-seal-256.png).",
    )

    dean_name = models.CharField(max_length=150, blank=True, default="MERLY P. ABIVA, PhD.")
    dean_title = models.CharField(max_length=100, blank=True, default="Dean")
    academic_head_name = models.CharField(max_length=150, blank=True, default="MARIA LAVELLA J. TORREGOSA, MAEM")
    academic_head_title = models.CharField(max_length=100, blank=True, default="Academic Head")
    registrar_name = models.CharField(max_length=150, blank=True, help_text="Signatory on a student's own Report of Grades PDF.")
    registrar_title = models.CharField(max_length=100, blank=True, default="Registrar")

    show_unofficial_scores_to_students = models.BooleanField(
        default=True,
        help_text="When off, a student's in-progress (not yet released) subjects show only "
        '"Grades not yet released" — no running score/grade at all.',
    )
    show_forecasts_to_students = models.BooleanField(
        default=False,
        help_text="Off by default while active forecast models are trained on synthetic data — "
        "turn on once a real, masked-historical model is active. When off, students see no "
        "forecast card/section at all (never probability or the words \"at risk\" either way).",
    )

    class Meta:
        verbose_name = "Institution Settings"
        verbose_name_plural = "Institution Settings"

    def __str__(self):
        return self.school_name

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # the singleton is never deleted

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
