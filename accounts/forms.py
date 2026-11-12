from django import forms
from django.contrib.auth.forms import SetPasswordForm

from academics.models import Major, Program
from core.forms import StyledModelForm

from .models import User

_INPUT_CLASSES = (
    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
    "focus:border-brand-accent-600 focus:outline-none focus:ring-2 focus:ring-brand-accent-500"
)


class ForcedPasswordChangeForm(SetPasswordForm):
    """Same validation as Django's SetPasswordForm; used on first login."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = _INPUT_CLASSES


class UserForm(StyledModelForm):
    """Create/edit a user of any role. Student-only fields (program,
    major -- stable, account-level data) are shown/hidden client-side by
    the template based on the selected role, and the major choices are
    narrowed via an HTMX cascade (see accounts/views.py user_form) — not
    by this form's __init__, so a GET "just refresh the dependent
    dropdowns" request never runs full validation (which a bound form
    would trigger by rendering `field.errors`). Year level and section
    are NOT here — they're per-semester (academics.SectionMembership),
    managed from the Program Head's Sections page, not the account form.
    """

    program = forms.ModelChoiceField(queryset=Program.objects.filter(is_active=True), required=False)
    major = forms.ModelChoiceField(queryset=Major.objects.none(), required=False)

    class Meta:
        model = User
        fields = ["role", "id_number", "last_name", "first_name", "middle_name", "email", "username"]
        help_texts = {
            "username": "Students: leave blank — it's set to the ID number automatically.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].required = False
        self.fields["email"].required = False

        profile = getattr(self.instance, "student_profile", None) if self.instance.pk else None
        if profile and not self.is_bound:
            self.fields["program"].initial = profile.program
            self.fields["major"].initial = profile.major

        program_id = None
        if self.is_bound:
            program_id = self.data.get("program") or None
        elif profile:
            program_id = profile.program_id

        if program_id:
            self.fields["major"].queryset = Major.objects.filter(program_id=program_id, is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")

        if role == User.Role.STUDENT:
            if not cleaned_data.get("id_number"):
                self.add_error("id_number", "Required for students.")
            if not cleaned_data.get("program"):
                self.add_error("program", "Required for students.")
            cleaned_data["username"] = cleaned_data.get("id_number") or ""
        elif role:
            if not cleaned_data.get("username"):
                self.add_error("username", "Required — suggest one from the surname.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if user.role == User.Role.STUDENT:
            user.username = self.cleaned_data["id_number"]
        if commit:
            user.save()
            self.save_student_profile(user)
        return user

    def save_student_profile(self, user):
        from academics.models import StudentProfile

        if user.role != User.Role.STUDENT:
            return
        StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "program": self.cleaned_data.get("program"),
                "major": self.cleaned_data.get("major"),
            },
        )


class ProfileEmailForm(StyledModelForm):
    """The only thing a user may edit on their own profile — everything
    else (name, ID, role) is admin-only, changed via the Users page."""

    class Meta:
        model = User
        fields = ["email"]
