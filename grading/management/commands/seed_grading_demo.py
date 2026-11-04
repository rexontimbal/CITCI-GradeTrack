"""Seeds the default grading template plus realistic assessment items/scores
for two of the demo instructor's classes, so Phase 4 (Grading) has something
to look at out of the box. Idempotent — safe to re-run (get_or_create /
update_or_create throughout; scores use a fixed random seed so re-running
always produces the same numbers instead of drifting).
"""

import random

from django.core.management.base import BaseCommand

from academics.models import ClassOffering, ClassRosterEntry
from core.management.guards import add_force_demo_argument, ensure_demo_allowed
from grading.models import AssessmentItem, AssessmentTerm, ClassGradingScheme, ComponentCategory, GradingComponent, GradingTemplate
from grading.services import save_score

# (component name, category, weight, is_locked, [max scores for each item])
# — matches grading-system.xlsx row 10 (CITCI's real class record). Only
# Examination's weight is fixed by the school; the other four are the
# suggested starting point an instructor can freely rename/reweight.
DEFAULT_TEMPLATE_COMPONENTS = [
    ("Attendance", ComponentCategory.ATTENDANCE, 5, False, [10, 10, 10, 10, 10]),
    ("Quizzes", ComponentCategory.QUIZ, 30, False, [20, 20, 30, 20, 30, 40, 50]),
    ("Recitation", ComponentCategory.RECITATION, 15, False, [10, 10, 20, 30, 30, 30, 40]),
    ("Project", ComponentCategory.PROJECT, 10, False, [50, 70, 60, 80, 90]),
    ("Examination", ComponentCategory.EXAM, 40, True, [80, 100, 80, 100]),
]

TERM_CYCLE = [AssessmentTerm.PRELIM, AssessmentTerm.MIDTERM, AssessmentTerm.SEMIFINAL, AssessmentTerm.FINAL]

RANDOM_SEED = 20261026  # fixed so re-running the command never drifts
LOW_PERFORMER_COUNT = 2  # first N active students in each roster score poorly

_STATUS_RANK = {"DRAFT": 0, "SUBMITTED": 1, "RETURNED": 1, "APPROVED": 2, "RELEASED": 3, "LOCKED": 4}


class Command(BaseCommand):
    help = "Seeds the default grading template and demo assessment items/scores (Phase 4). Idempotent."

    def add_arguments(self, parser):
        add_force_demo_argument(parser)

    def handle(self, *args, **options):
        ensure_demo_allowed(options.get("force_demo"))
        template = self._seed_default_template()

        # Any two classes that have both an assigned instructor and an
        # active roster — not hardcoded to a specific demo username, so this
        # works whether or not seed_demo_users ran before seed_citci_academics.
        classes_with_roster = (
            ClassOffering.objects.filter(
                instructor__isnull=False, roster_entries__status=ClassRosterEntry.Status.ACTIVE
            )
            .distinct()
            .order_by("id")
        )
        demo_classes = list(classes_with_roster[:3])

        if not demo_classes:
            self.stdout.write(self.style.WARNING("No class with an instructor and a roster yet — run seed_citci_academics first."))
            return

        # index 0 stays DRAFT with its Final exam deliberately blank (demos
        # the running-grade rule); index 1 goes all the way to RELEASED;
        # index 2 (if a third demo class exists) stops at SUBMITTED — so the
        # Program Head queue and Admin Grade Sheets page aren't empty.
        workflow_targets = ["DRAFT", "RELEASED", "SUBMITTED"]

        for index, class_offering in enumerate(demo_classes):
            scheme = ClassGradingScheme.get_or_create_default(class_offering)
            if scheme.source_template_id != template.id:
                scheme = ClassGradingScheme.apply_template(class_offering, template)
            skip_final_exam = index == 0
            self._seed_class_scores(class_offering, scheme, skip_final_exam, class_offering.instructor)
            self.stdout.write(self.style.SUCCESS(f"Grading data ready for {class_offering}."))

            target = workflow_targets[index] if index < len(workflow_targets) else "DRAFT"
            if target != "DRAFT":
                self._progress_grade_sheet(class_offering, target)

        self.stdout.write(self.style.SUCCESS("Grading demo data ready."))

    def _seed_default_template(self):
        template, _ = GradingTemplate.objects.update_or_create(
            name="CITCI Default",
            defaults={
                "description": "Attendance 5%, Quizzes 30%, Recitation 15%, Project 10%, Examination 40% "
                "— CITCI's official class record weights.",
                "is_default": True,
                "is_active": True,
            },
        )
        for order, (name, category, weight, is_locked, _maxes) in enumerate(DEFAULT_TEMPLATE_COMPONENTS, start=1):
            GradingComponent.objects.update_or_create(
                template=template,
                name=name,
                defaults={"category": category, "weight": weight, "is_locked": is_locked, "order": order},
            )
        self.stdout.write(self.style.SUCCESS("Default grading template ready (CITCI Default)."))
        return template

    def _seed_class_scores(self, class_offering, scheme, skip_final_exam, instructor):
        scheme_components = {sc.name: sc for sc in scheme.components.all()}
        items_by_component = {}

        for name, _category, _weight, _is_locked, maxes in DEFAULT_TEMPLATE_COMPONENTS:
            scheme_component = scheme_components[name]
            items = []
            for i, max_score in enumerate(maxes):
                term = TERM_CYCLE[i % len(TERM_CYCLE)]
                item, _ = AssessmentItem.objects.update_or_create(
                    class_offering=class_offering,
                    component=scheme_component,
                    title=f"{name[:1]}{i + 1}" if name != "Examination" else ["Prelim Exam", "Midterm Exam", "Semi-Final Exam", "Final Exam"][i],
                    defaults={"max_score": max_score, "term": term, "order": i},
                )
                items.append(item)
            items_by_component[name] = items

        final_exam_item = items_by_component["Examination"][-1]

        roster_entries = list(
            class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )
        rng = random.Random(f"{RANDOM_SEED}-{class_offering.pk}")

        for student_index, roster_entry in enumerate(roster_entries):
            is_low_performer = student_index < LOW_PERFORMER_COUNT
            score_range = (0.40, 0.62) if is_low_performer else (0.72, 0.98)

            for name, items in items_by_component.items():
                for item in items:
                    if skip_final_exam and item is final_exam_item:
                        continue  # left blank on purpose to demo the running grade
                    fraction = rng.uniform(*score_range)
                    value = max(0, min(item.max_score, round(fraction * item.max_score)))
                    save_score(roster_entry, item, value, instructor)

    def _progress_grade_sheet(self, class_offering, target_status):
        """Idempotent: only takes whatever steps haven't already happened —
        safe to re-run without re-submitting an already-SUBMITTED sheet."""
        from accounts.models import User
        from approvals.models import GradeSheet, GradeSheetStatus
        from approvals.services import approve_grade_sheet, release_grade_sheet, submit_grade_sheet

        reviewer = (
            User.objects.filter(
                role=User.Role.PROGRAM_HEAD, headed_programs__sections__class_offerings=class_offering
            )
            .distinct()
            .first()
        ) or User.objects.filter(role=User.Role.PROGRAM_HEAD).first()

        def current_status():
            sheet = GradeSheet.objects.filter(class_offering=class_offering).first()
            return sheet.status if sheet else GradeSheetStatus.DRAFT

        if _STATUS_RANK[current_status()] < _STATUS_RANK["SUBMITTED"] <= _STATUS_RANK[target_status]:
            submit_grade_sheet(class_offering, class_offering.instructor)

        if reviewer is None:
            self.stdout.write(self.style.WARNING(f"No program head found to approve/release {class_offering} — left SUBMITTED."))
            return

        if _STATUS_RANK[current_status()] < _STATUS_RANK["APPROVED"] <= _STATUS_RANK[target_status]:
            sheet = GradeSheet.objects.get(class_offering=class_offering)
            approve_grade_sheet(sheet, reviewer)

        if _STATUS_RANK[current_status()] < _STATUS_RANK["RELEASED"] <= _STATUS_RANK[target_status]:
            sheet = GradeSheet.objects.get(class_offering=class_offering)
            release_grade_sheet(sheet, reviewer)
