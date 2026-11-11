"""Phase 8 part B — builds a large, clearly-synthetic dataset for load/
performance testing (tools/perf_check.py): 1 admin, 2 program heads, 15
instructors, 450 students, the current semester + 2 past semesters, with
realistic scores, a submit/approve/release workflow on the past semesters,
and computed forecasts.

Deliberately separate from the real CITCI data: every username/id_number/
program/subject code below is prefixed "LOAD" so it's unmistakable in the
admin UI and never collides with `seed_citci_academics`'s real BSED/TCP
data. Run this against a dedicated dev/load-test database, never a shared
one you also use for demos — see the warning printed at the end about the
global active-semester flag.

Refuses under the production settings module unless --force-demo is passed
(core.management.guards, same rule as every other seed_* command).

Not optimized for idempotent re-runs the way the smaller demo seeders are —
building 450 students' worth of scores twice over is expensive for no
benefit. Re-running is safe (nothing breaks), but a second run adds load-test
score volume on top of the first rather than resetting it; drop the LOAD*
rows yourself (or restore from a backup) before re-seeding from scratch.
"""

import random
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from academics.models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
    Term,
)
from accounts.models import User
from approvals.services import approve_grade_sheet, release_grade_sheet, submit_grade_sheet
from core.management.guards import add_force_demo_argument, ensure_demo_allowed
from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme, Score
from grading.services import ensure_default_grading_template

LOAD_PASSWORD = "LoadTest@1234"
RANDOM_SEED = 20261104

N_PROGRAM_HEADS = 2
N_INSTRUCTORS = 15
N_STUDENTS = 450
SECTIONS_PER_PROGRAM = 3
SUBJECT_CODES = [f"LOADSUB{i}" for i in range(1, 7)]

# (component name, max scores per item) — a small, fixed set per class so
# seeding 450 students x many classes x 3 semesters stays fast; "realistic"
# here means varied scores, not the full demo item richness.
ITEM_PLAN = [
    ("Attendance", [10]),
    ("Quizzes", [20, 20]),
    ("Recitation", [10]),
    ("Project", [50]),
    ("Examination", [20, 30, 30, 50]),  # Prelim / Midterm / Semi-Final / Final
]
EXAM_TERM_CYCLE = [AssessmentTerm.PRELIM, AssessmentTerm.MIDTERM, AssessmentTerm.SEMIFINAL, AssessmentTerm.FINAL]


class Command(BaseCommand):
    help = (
        "Seeds a large (450-student) clearly-synthetic dataset for load/performance "
        "testing (tools/perf_check.py). Dev-only — see core.management.guards."
    )

    def add_arguments(self, parser):
        add_force_demo_argument(parser)

    def handle(self, *args, **options):
        ensure_demo_allowed(options.get("force_demo"))
        rng = random.Random(RANDOM_SEED)
        password_hash = make_password(LOAD_PASSWORD)

        with transaction.atomic():
            ensure_default_grading_template()
            admin = self._seed_admin(password_hash)
            program_heads = self._seed_program_heads(password_hash)
            instructors = self._seed_instructors(password_hash)
            programs = self._seed_programs(program_heads)
            past_year, current_year = self._seed_academic_years()
            sem_past_1, sem_past_2, sem_current = self._seed_semesters(past_year, current_year)
            sections_past = self._seed_sections(programs, past_year)
            sections_current = self._seed_sections(programs, current_year)
            subjects = self._seed_subjects()
            students = self._seed_students(password_hash, programs, sections_current)

            for semester, sections, is_past in (
                (sem_past_1, sections_past, True),
                (sem_past_2, sections_past, True),
                (sem_current, sections_current, False),
            ):
                classes = self._seed_classes(semester, subjects, instructors, sections, rng)
                for class_offering in classes:
                    self._seed_roster(class_offering, students)
                    self._seed_scores(class_offering, rng)
                    if is_past:
                        self._progress_to_released(class_offering, program_heads)

        self.stdout.write(self.style.SUCCESS(f"Admin: {admin.username}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(program_heads)} program head(s), {len(instructors)} instructor(s), "
                f"{len(students)} student(s), all password: {LOAD_PASSWORD}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"'{sem_current}' is now the app-wide ACTIVE semester (Semester.save() "
                "deactivates every other one) — run this only on a dedicated dev/load-test "
                "database, not one you also use for demos."
            )
        )
        self.stdout.write(self.style.SUCCESS("Load-test data ready. Run `python manage.py run_forecasts` to compute predictions."))

    # -- accounts -----------------------------------------------------

    def _seed_admin(self, password_hash):
        admin, _ = User.objects.update_or_create(
            username="load_admin",
            defaults={
                "first_name": "Load",
                "last_name": "Admin",
                "role": User.Role.ADMIN,
                "id_number": "LOAD-ADMIN-0001",
                "email": "load_admin@example.test",
                "is_staff": True,
                "is_superuser": True,
                "password": password_hash,
                "is_active": True,
                # Unlike the human-facing demo accounts (seed_demo_users),
                # these are driven by an automated script — skip the forced
                # password-change/privacy-consent onboarding gates entirely
                # so a login lands straight on a dashboard.
                "must_change_password": False,
                "privacy_consent_at": timezone.now(),
            },
        )
        return admin

    def _seed_program_heads(self, password_hash):
        heads = []
        for i in range(1, N_PROGRAM_HEADS + 1):
            head, _ = User.objects.update_or_create(
                username=f"load_head_{i}",
                defaults={
                    "first_name": "Load",
                    "last_name": f"Head{i}",
                    "role": User.Role.PROGRAM_HEAD,
                    "id_number": f"LOAD-HEAD-{i:04d}",
                    "email": f"load_head_{i}@example.test",
                    "password": password_hash,
                    "is_active": True,
                    "must_change_password": False,
                    "privacy_consent_at": timezone.now(),
                },
            )
            heads.append(head)
        return heads

    def _seed_instructors(self, password_hash):
        instructors = []
        for i in range(1, N_INSTRUCTORS + 1):
            instructor, _ = User.objects.update_or_create(
                username=f"load_instructor_{i}",
                defaults={
                    "first_name": "Load",
                    "last_name": f"Instructor{i}",
                    "role": User.Role.INSTRUCTOR,
                    "id_number": f"LOAD-INS-{i:04d}",
                    "email": f"load_instructor_{i}@example.test",
                    "password": password_hash,
                    "is_active": True,
                    "must_change_password": False,
                    "privacy_consent_at": timezone.now(),
                },
            )
            instructors.append(instructor)
        return instructors

    def _seed_students(self, password_hash, programs, sections_current):
        """bulk_create (bypassing the StudentProfile auto-create signal,
        which only fires on save()) is deliberate here — 450 individual
        .create() calls plus 450 signal-fired profile creations would be
        needlessly slow for a one-time fixture; we build both tables
        ourselves in two bulk_create calls instead."""
        existing = {u.username: u for u in User.objects.filter(username__startswith="load_student_")}
        new_users = []
        for i in range(1, N_STUDENTS + 1):
            username = f"load_student_{i:04d}"
            if username in existing:
                continue
            new_users.append(
                User(
                    username=username,
                    first_name="Load",
                    last_name=f"Student{i:04d}",
                    role=User.Role.STUDENT,
                    id_number=f"LOAD-STU-{i:04d}",
                    email=f"{username}@example.test",
                    password=password_hash,
                    is_active=True,
                    must_change_password=False,
                    privacy_consent_at=timezone.now(),
                )
            )
        if new_users:
            User.objects.bulk_create(new_users)

        students = list(User.objects.filter(username__startswith="load_student_").order_by("username"))

        sections_by_program = {}
        for section in sections_current:
            sections_by_program.setdefault(section.program_id, []).append(section)

        profiles_by_user = {p.user_id: p for p in StudentProfile.objects.filter(user__in=students)}
        new_profiles = []
        for index, student in enumerate(students):
            program = programs[index % len(programs)]
            program_sections = sections_by_program[program.id]
            section = program_sections[index % len(program_sections)]
            if student.id in profiles_by_user:
                continue
            new_profiles.append(StudentProfile(user=student, program=program, major=None, year_level=1, section=section))
        if new_profiles:
            StudentProfile.objects.bulk_create(new_profiles)

        return students

    # -- academic structure --------------------------------------------

    def _seed_programs(self, program_heads):
        programs = []
        for i in range(1, N_PROGRAM_HEADS + 1):
            program, _ = Program.objects.update_or_create(
                code=f"LOAD{i}",
                defaults={"name": f"Load Test Program {i}", "program_head": program_heads[i - 1], "is_active": True},
            )
            programs.append(program)
        return programs

    def _seed_academic_years(self):
        past_year, _ = AcademicYear.objects.get_or_create(start_year=2019)
        current_year, _ = AcademicYear.objects.get_or_create(start_year=2020)
        return past_year, current_year

    def _seed_semesters(self, past_year, current_year):
        sem_past_1, _ = Semester.objects.update_or_create(
            academic_year=past_year, term=Term.FIRST, defaults={"is_active": False}
        )
        sem_past_2, _ = Semester.objects.update_or_create(
            academic_year=past_year, term=Term.SECOND, defaults={"is_active": False}
        )
        sem_current, _ = Semester.objects.update_or_create(
            academic_year=current_year, term=Term.FIRST, defaults={"is_active": True}
        )
        return sem_past_1, sem_past_2, sem_current

    def _seed_sections(self, programs, academic_year):
        sections = []
        for program in programs:
            for letter in "ABC"[:SECTIONS_PER_PROGRAM]:
                section, _ = Section.objects.get_or_create(
                    program=program, major=None, academic_year=academic_year, year_level=1, name=letter
                )
                sections.append(section)
        return sections

    def _seed_subjects(self):
        subjects = []
        for code in SUBJECT_CODES:
            subject, _ = Subject.objects.update_or_create(
                code=code,
                defaults={"title": f"Load Test Subject {code[-1]}", "units": Decimal("3.0")},
            )
            subjects.append(subject)
        return subjects

    def _seed_classes(self, semester, subjects, instructors, sections, rng):
        """One class per section (so every student has something on their
        roster) plus one deliberately bigger class spanning every section
        in the semester — the "largest class" tools/perf_check.py times."""
        classes = []
        for index, section in enumerate(sections):
            subject = subjects[index % len(subjects)]
            # schedule="" is part of the lookup (not just defaults) so a
            # per-section class never collides with the LOAD-BIG class
            # below when they happen to share a subject+semester — without
            # it, re-running this command after the subject cycle wraps
            # onto the same subject the big class uses raises
            # MultipleObjectsReturned on the second run's get_or_create.
            class_offering, _ = ClassOffering.objects.get_or_create(
                subject=subject,
                semester=semester,
                schedule="",
                defaults={"instructor": instructors[index % len(instructors)]},
            )
            class_offering.sections.set([section])
            classes.append(class_offering)

        big_subject = subjects[-1]
        big_class, _ = ClassOffering.objects.get_or_create(
            subject=big_subject,
            semester=semester,
            schedule="LOAD-BIG",
            defaults={"instructor": instructors[0]},
        )
        big_class.sections.set(sections)
        classes.append(big_class)
        return classes

    def _seed_roster(self, class_offering, students):
        section_ids = set(class_offering.sections.values_list("id", flat=True))
        wanted_students = [
            s
            for s in students
            if StudentProfile.objects.filter(user=s, section_id__in=section_ids).exists()
        ]
        existing_ids = set(
            ClassRosterEntry.objects.filter(class_offering=class_offering).values_list("student_id", flat=True)
        )
        new_entries = [
            ClassRosterEntry(student=s, class_offering=class_offering) for s in wanted_students if s.id not in existing_ids
        ]
        if new_entries:
            ClassRosterEntry.objects.bulk_create(new_entries)

    def _seed_scores(self, class_offering, rng):
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
        scheme_components = {sc.name: sc for sc in scheme.components.all()}

        items_by_component = {}
        for name, maxes in ITEM_PLAN:
            scheme_component = scheme_components.get(name)
            if scheme_component is None:
                continue
            items = []
            for i, max_score in enumerate(maxes):
                term = EXAM_TERM_CYCLE[i] if name == "Examination" else EXAM_TERM_CYCLE[i % len(EXAM_TERM_CYCLE)]
                item, _ = AssessmentItem.objects.get_or_create(
                    class_offering=class_offering,
                    component=scheme_component,
                    title=f"{name} {i + 1}",
                    defaults={"max_score": max_score, "term": term, "order": i},
                )
                items.append(item)
            items_by_component[name] = items

        roster_entries = list(class_offering.roster_entries.select_related("student"))
        existing_scored_item_ids = set(
            Score.objects.filter(roster_entry__class_offering=class_offering).values_list("item_id", flat=True)
        )

        new_scores = []
        for roster_entry in roster_entries:
            student_rng = random.Random(f"{RANDOM_SEED}-{class_offering.pk}-{roster_entry.student_id}")
            is_weak = student_rng.random() < 0.15  # ~15% of a class scores weakly, for forecast variety
            score_range = (0.35, 0.60) if is_weak else (0.70, 0.98)
            for items in items_by_component.values():
                for item in items:
                    if item.id in existing_scored_item_ids and Score.objects.filter(roster_entry=roster_entry, item=item).exists():
                        continue
                    fraction = student_rng.uniform(*score_range)
                    value = max(0, min(item.max_score, round(fraction * item.max_score)))
                    new_scores.append(Score(roster_entry=roster_entry, item=item, score=value))
        if new_scores:
            Score.objects.bulk_create(new_scores, ignore_conflicts=True)

    def _progress_to_released(self, class_offering, program_heads):
        from approvals.models import GradeSheet, GradeSheetStatus

        sheet = GradeSheet.objects.filter(class_offering=class_offering).first()
        if sheet and sheet.status == GradeSheetStatus.RELEASED:
            return
        reviewer = program_heads[0]
        if not sheet or sheet.status == GradeSheetStatus.DRAFT:
            submit_grade_sheet(class_offering, class_offering.instructor)
            sheet = GradeSheet.objects.get(class_offering=class_offering)
        if sheet.status == GradeSheetStatus.SUBMITTED:
            approve_grade_sheet(sheet, reviewer)
            sheet.refresh_from_db()
        if sheet.status == GradeSheetStatus.APPROVED:
            release_grade_sheet(sheet, reviewer)
