"""Ensures the demo `student` account (Phase 5 — Student Portal) shows
every state the spec calls for, on top of whatever seed_grading_demo
already did:

    - RELEASED and in-progress-with-partial-scores subjects already come
      for free from seed_grading_demo's GE 6/GE 2 (both serve BSED-ENG 1,
      the demo student's section). "No scores yet" comes for free too —
      any of the demo student's other active-semester classes
      seed_grading_demo never touched has zero assessment items.
    - A SUBMITTED subject is NOT reliably free: seed_grading_demo's own
      SUBMITTED target can end up carried further (APPROVED/RELEASED/
      LOCKED) once a program head has actually used the approvals queue in
      this environment, since grade-sheet status only ever moves forward.
      `_seed_submitted_subject` below guarantees one exists regardless.
    - Also not free: a subject with a running grade > 3.00 (the
      dashboard's "Warnings" stat), and a past semester with released+
      locked grades so GWA history has at least two points — both added
      below.

Idempotent — safe to re-run (get_or_create throughout; the submitted/
warning steps no-op once a qualifying subject already exists, and the
past-semester step no-ops once that semester's roster entries already
exist).
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from academics.models import AcademicYear, ClassOffering, ClassRosterEntry, Section, Semester, Subject, Term
from accounts.models import User
from approvals.models import GradeSheet, GradeSheetStatus
from approvals.services import approve_grade_sheet, lock_term, release_grade_sheet, submit_grade_sheet
from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme
from grading.services import save_score

PAST_ACADEMIC_YEAR_START = 2025


class Command(BaseCommand):
    help = "Fills in the Phase 5 demo states the real seed data doesn't already cover for the `student` account. Idempotent."

    def handle(self, *args, **options):
        student = User.objects.filter(username="student").first()
        if student is None:
            self.stdout.write(self.style.WARNING("No demo `student` account — run seed_demo_users first."))
            return

        self._seed_submitted_subject(student)
        self._seed_warning_subject(student)
        self._seed_past_semester(student)
        self.stdout.write(self.style.SUCCESS("Student portal demo data ready."))

    def _seed_submitted_subject(self, student):
        """Guarantees at least one of the student's active-semester classes
        sits at exactly SUBMITTED ("shows as in progress") — fully scores
        every active student in a spare (untouched) class and submits it,
        but never approves/releases it."""
        active = Semester.objects.filter(is_active=True).first()
        if active is None:
            return

        already_submitted = GradeSheet.objects.filter(
            class_offering__roster_entries__student=student,
            class_offering__semester=active,
            status=GradeSheetStatus.SUBMITTED,
        ).exists()
        if already_submitted:
            return

        roster_entries = ClassRosterEntry.objects.filter(
            student=student, class_offering__semester=active, status=ClassRosterEntry.Status.ACTIVE
        ).select_related("class_offering__instructor")

        target_class = None
        for entry in roster_entries:
            class_offering = entry.class_offering
            if class_offering.assessment_items.exists() or GradeSheet.objects.filter(class_offering=class_offering).exists():
                continue  # already used by another demo state, or has a sheet already
            target_class = class_offering
            break
        if target_class is None:
            self.stdout.write(self.style.WARNING("No spare class available to seed a SUBMITTED subject."))
            return

        scheme = ClassGradingScheme.get_or_create_default(target_class)
        active_entries = list(target_class.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE))
        for component in scheme.components.all():
            item = AssessmentItem.objects.create(
                class_offering=target_class, component=component, title=f"{component.name} 1",
                max_score=10, term=AssessmentTerm.FINAL, order=0,
            )
            for roster_entry in active_entries:
                save_score(roster_entry, item, 8, target_class.instructor)  # 8/10 -> comfortably passing

        submit_grade_sheet(target_class, target_class.instructor)
        self.stdout.write(self.style.SUCCESS(f"Submitted subject ready: {target_class} (shows as in progress)."))

    def _seed_warning_subject(self, student):
        active = Semester.objects.filter(is_active=True).first()
        if active is None:
            return

        roster_entries = ClassRosterEntry.objects.filter(
            student=student, class_offering__semester=active, status=ClassRosterEntry.Status.ACTIVE
        ).select_related("class_offering__instructor")

        # Already have a warning subject from a previous run? Nothing to do.
        from grading.services import compute_student

        for entry in roster_entries:
            if entry.class_offering.assessment_items.exists():
                running = compute_student(entry).running_grade
                if running is not None and running > Decimal("3.00"):
                    return

        # First class with zero items at all — give it one badly-scored item
        # for this student only (nobody else needs to be touched).
        target = next((e for e in roster_entries if not e.class_offering.assessment_items.exists()), None)
        if target is None:
            return

        class_offering = target.class_offering
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
        component = scheme.components.filter(category="QUIZ").first() or scheme.components.first()
        if component is None:
            return

        item, _ = AssessmentItem.objects.get_or_create(
            class_offering=class_offering,
            component=component,
            title="Quiz 1",
            defaults={"max_score": 20, "term": AssessmentTerm.PRELIM, "order": 0},
        )
        save_score(target, item, 2, class_offering.instructor)  # 2/20 -> grade 4.60, well over 3.00
        self.stdout.write(self.style.SUCCESS(f"Warning subject ready: {class_offering} (running grade > 3.00)."))

    def _seed_past_semester(self, student):
        if ClassRosterEntry.objects.filter(
            student=student, class_offering__semester__academic_year__start_year=PAST_ACADEMIC_YEAR_START
        ).exists():
            return  # already seeded on a previous run

        profile = getattr(student, "student_profile", None)
        if profile is None or profile.program is None:
            self.stdout.write(self.style.WARNING("Demo student has no program set — skipping past semester."))
            return

        past_year, _ = AcademicYear.objects.get_or_create(start_year=PAST_ACADEMIC_YEAR_START)
        past_semester, _ = Semester.objects.get_or_create(
            academic_year=past_year, term=Term.SECOND, defaults={"is_active": False}
        )

        section, _ = Section.objects.get_or_create(
            program=profile.program,
            major=profile.major,
            academic_year=past_year,
            year_level=profile.year_level,
            name=profile.section.name if profile.section else "",
        )

        # Avoid reusing a subject code the student is already carrying this
        # (current) semester — same Subject row, different ClassOffering,
        # would make the dashboard/notifications read as if the SAME class
        # were in two semesters at once, which is confusing for a demo.
        current_codes = set(
            ClassRosterEntry.objects.filter(student=student, class_offering__semester__is_active=True).values_list(
                "class_offering__subject__code", flat=True
            )
        )
        subjects = list(Subject.objects.filter(program=profile.program).exclude(code__in=current_codes)[:2])
        if len(subjects) < 2:
            subjects = list(Subject.objects.exclude(code__in=current_codes)[:2])
        if not subjects:
            self.stdout.write(self.style.WARNING("No subjects exist yet — skipping past semester."))
            return

        instructor = User.objects.filter(role=User.Role.INSTRUCTOR).first()
        program_head = profile.program.program_head

        # One clearly-passing, one clearly-failing subject, so the GWA
        # history table's passed/failed/INC columns have something to show.
        performance = [Decimal("8"), Decimal("2")]  # out of 10 -> grades 1.80 and 4.20

        for subject, earned in zip(subjects, performance):
            class_offering = ClassOffering.objects.create(subject=subject, semester=past_semester, instructor=instructor)
            class_offering.sections.set([section])
            roster_entry = ClassRosterEntry.objects.create(student=student, class_offering=class_offering)

            scheme = ClassGradingScheme.get_or_create_default(class_offering)
            for component in scheme.components.all():
                item = AssessmentItem.objects.create(
                    class_offering=class_offering, component=component, title=f"{component.name} 1",
                    max_score=10, term=AssessmentTerm.FINAL, order=0,
                )
                save_score(roster_entry, item, int(earned), instructor)

            sheet = submit_grade_sheet(class_offering, instructor)
            if program_head:
                approve_grade_sheet(sheet, program_head)
                release_grade_sheet(sheet, program_head)

        if program_head:
            lock_term(past_semester, program_head)

        self.stdout.write(self.style.SUCCESS(f"Past semester ready: {past_semester} (released + locked)."))
