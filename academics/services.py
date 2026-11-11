"""Teaching-load assignment: Program Heads assign which instructor teaches
each class in their program (CITCI confirmed practice); Admin keeps the
ability to set/change it too, as a logged "admin override". Pure functions
— no view/HTTP concerns; views call these and translate ValidationError to
a form error.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q

import re

from .models import (
    AcademicSetupChangeLog,
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Section,
    Semester,
    SemesterStatus,
    StudentProfile,
    Subject,
    SubjectOffering,
    TeachingAssignmentLog,
)


def check_instructor_change_allowed(class_offering):
    """Raises ValidationError if this class's grade sheet has already been
    submitted — once grades are in the approval pipeline, who taught the
    class shouldn't change out from under it. Allowed while the sheet is
    still DRAFT/RETURNED, or doesn't exist yet. Also blocked once the
    class's semester is CLOSED (read-only everywhere except admin grade
    corrections)."""
    from approvals.services import is_class_editable

    if is_semester_locked(class_offering.semester):
        raise ValidationError("This semester is closed — the instructor can no longer be changed.")

    if not is_class_editable(class_offering):
        raise ValidationError(
            "This class's grade sheet has already been submitted — the instructor can no longer be changed."
        )


def assign_instructor(class_offering, new_instructor, actor, is_admin_override=False, reason=""):
    """Assigns/changes/clears (new_instructor=None) a class's instructor.
    Returns the TeachingAssignmentLog row, or None if the instructor didn't
    actually change (a no-op is never logged or notified)."""
    old_instructor = class_offering.instructor
    if old_instructor_id_matches(old_instructor, new_instructor):
        return None

    check_instructor_change_allowed(class_offering)

    class_offering.instructor = new_instructor
    class_offering.save(update_fields=["instructor"])

    return log_and_notify_instructor_change(
        class_offering, old_instructor, new_instructor, actor, is_admin_override=is_admin_override, reason=reason
    )


def old_instructor_id_matches(old_instructor, new_instructor):
    old_id = old_instructor.id if old_instructor else None
    new_id = new_instructor.id if new_instructor else None
    return old_id == new_id


def log_and_notify_instructor_change(class_offering, old_instructor, new_instructor, actor, is_admin_override=False, reason=""):
    """Writes the TeachingAssignmentLog row and notifies both the new
    instructor and the previous one (if any) — shared by the dedicated
    assign/bulk-assign views and the admin Classes edit form, so every
    path that changes an instructor logs and notifies the same way."""
    from dashboard.services import notify

    log = TeachingAssignmentLog.objects.create(
        class_offering=class_offering,
        old_instructor=old_instructor,
        new_instructor=new_instructor,
        changed_by=actor,
        is_admin_override=is_admin_override,
        reason=reason,
    )

    if new_instructor is not None:
        notify(
            new_instructor,
            "New teaching assignment",
            f"You've been assigned {class_offering}.",
            link="/academics/my-classes/",
        )
    if old_instructor is not None and (new_instructor is None or old_instructor.id != new_instructor.id):
        notify(
            old_instructor,
            "Teaching assignment changed",
            f"{class_offering.subject.code} was reassigned.",
            link="/academics/my-classes/",
        )
    return log


def teaching_load_rows(semester, programs, program_id=None, instructor_id=None):
    """Per-instructor teaching load for `semester`, scoped to `programs`
    (already role-scoped by the caller — see reports.views._scope_programs
    for the same pattern). Returns (rows, unassigned_classes):
    rows = [{"instructor": User, "classes": [...], "total_units": Decimal,
    "total_students": int}, ...] sorted by instructor name; unassigned
    classes are listed separately, never silently dropped."""
    if semester is None:
        return [], []

    scoped_programs = programs.filter(pk=program_id) if program_id else programs
    classes = (
        ClassOffering.objects.filter(semester=semester, sections__program__in=scoped_programs)
        .distinct()
        .select_related("subject", "instructor")
        .annotate(
            roster_size=Count(
                "roster_entries", filter=Q(roster_entries__status=ClassRosterEntry.Status.ACTIVE), distinct=True
            )
        )
    )
    if instructor_id:
        classes = classes.filter(instructor_id=instructor_id)

    by_instructor = {}
    unassigned = []
    for class_offering in classes:
        if class_offering.instructor_id is None:
            unassigned.append(class_offering)
            continue
        row = by_instructor.setdefault(
            class_offering.instructor_id,
            {"instructor": class_offering.instructor, "classes": [], "total_units": Decimal("0"), "total_students": 0},
        )
        row["classes"].append(class_offering)
        row["total_units"] += class_offering.subject.units
        row["total_students"] += class_offering.roster_size

    rows = sorted(by_instructor.values(), key=lambda r: r["instructor"].full_name)
    return rows, unassigned


# ---------------------------------------------------------------------------
# Program Head assignment notification — Admin assigns a head on the
# Programs/Majors pages; the new head is notified. Modeled directly on
# log_and_notify_instructor_change's no-op guard (re-saving the same head
# is never notified twice).
# ---------------------------------------------------------------------------


def notify_program_head_assignment(entity, old_head, new_head):
    from dashboard.services import notify

    old_id = old_head.id if old_head else None
    new_id = new_head.id if new_head else None
    if old_id == new_id or new_head is None:
        return
    notify(
        new_head,
        "You've been assigned as Program Head",
        f"You now manage {entity}.",
        link="/academics/my-program/sections/",
    )


# ---------------------------------------------------------------------------
# "Copy classes from previous semester" — admin picks a source semester
# (defaults to the same term, previous A.Y.), previews the classes that
# would be created for the active/target semester, then confirms. The
# instructor is always left Unassigned on the copy — Program Heads assign
# teaching loads (section 3a) — regardless of who taught the source class.
# ---------------------------------------------------------------------------


def default_source_semester(target_semester):
    """Same term, previous academic year — just a pre-selected default;
    the admin can still pick a different source semester."""
    previous_ay = AcademicYear.objects.filter(start_year=target_semester.academic_year.start_year - 1).first()
    if previous_ay is None:
        return None
    return Semester.objects.filter(academic_year=previous_ay, term=target_semester.term).first()


def build_copy_preview(source_semester, target_semester):
    """Never writes. One row per source ClassOffering: its subject, its
    source sections, the resolved equivalent sections in the target
    semester's academic year (same program/major/year_level/name), or a
    reported "no equivalent section" if one can't be found — never
    guessed."""
    rows = []
    classes = source_semester.class_offerings.select_related("subject").prefetch_related(
        "sections__program", "sections__major"
    )
    for class_offering in classes:
        source_sections = list(class_offering.sections.all())
        target_sections = []
        missing = []
        for section in source_sections:
            equivalent = Section.objects.filter(
                program=section.program,
                major=section.major,
                academic_year=target_semester.academic_year,
                year_level=section.year_level,
                name=section.name,
            ).first()
            if equivalent is None:
                missing.append(section)
            else:
                target_sections.append(equivalent)
        rows.append(
            {
                "class_offering": class_offering,
                "subject": class_offering.subject,
                "source_sections": source_sections,
                "target_section_ids": [s.id for s in target_sections],
                "target_sections": target_sections,
                "missing_sections": missing,
                "can_copy": not missing,
            }
        )
    return rows


def commit_copy(preview_rows, target_semester):
    """One atomic transaction. Skips (and the caller reports) any row
    whose sections didn't fully resolve rather than creating a class with
    missing sections. Instructor is always None on the copy."""
    created = 0
    skipped = 0
    with transaction.atomic():
        for row in preview_rows:
            if not row["can_copy"]:
                skipped += 1
                continue
            source = row["class_offering"]
            new_class = ClassOffering.objects.create(
                subject=source.subject,
                semester=target_semester,
                instructor=None,
                schedule=source.schedule,
                room=source.room,
            )
            new_class.sections.set(row["target_section_ids"])
            created += 1
    return {"created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# Add/Edit Subject — the subject catalog is school-wide, so a new code
# must never silently duplicate an existing one that's merely spelled or
# spaced differently ("EL 100" vs "el100"); a code match always wins over
# creating a new row. A subject also sits in a given program/major's
# curriculum AT MOST ONCE, period (see CurriculumEntry's Meta constraints)
# — not once per year-level/term slot.
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_code(code):
    """Case/spacing-insensitive canonical form of a subject code, used
    only for matching — never stored or displayed (the original casing
    a human typed is what's saved)."""
    return _WHITESPACE_RE.sub(" ", (code or "").strip()).upper()


def find_subject_by_normalized_code(code):
    """Exact match against the catalog, ignoring case and whitespace
    differences. The catalog is small (low hundreds of rows at most) so
    a Python-side scan is simpler and plenty fast — no need for a
    generated/indexed normalized-code column."""
    target = normalize_code(code)
    if not target:
        return None
    for subject in Subject.objects.all():
        if normalize_code(subject.code) == target:
            return subject
    return None


def slot_label(year_level, term):
    """"1st Year · 1st Semester" / "1st Semester" (no year level, e.g.
    TCP) — display label for one curriculum slot."""
    term_labels = {"FIRST": "1st Semester", "SECOND": "2nd Semester", "SUMMER": "Summer"}
    term_label = term_labels.get(term, term)
    if not year_level:
        return term_label
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(year_level, "th")
    return f"{year_level}{suffix} Year · {term_label}"


def scope_label(program, major):
    """Display label for a program/major scope, e.g. "BSED – English".
    `.title()` guards against a Major whose `name` happens to be stored
    in a different case (e.g. imported from an all-caps docx heading like
    "MAJOR IN ENGLISH") -- the badge should always read in proper case
    regardless of how it's stored."""
    return f"{program.code} – {major.name.title()}" if major else program.code


def subject_duplicate_error(subject, program, major, year_level, term):
    """None if `subject` isn't already in this program/major's curriculum
    anywhere; else a user-facing message — worded differently depending
    on whether the existing placement happens to be the exact slot being
    added to, or elsewhere in the same program/major (a subject can only
    ever sit once per program/major, so these are the only two cases)."""
    existing = CurriculumEntry.objects.filter(program=program, major=major, subject=subject).first()
    if existing is None:
        return None
    if existing.year_level == year_level and existing.term == term:
        return f"{subject.code} is already in {slot_label(year_level, term)}."
    return (
        f"{subject.code} is already in {slot_label(existing.year_level, existing.term)} of "
        f"{scope_label(program, major)}. Remove it there first."
    )


def subject_used_in_released_grades(subject):
    """True if any class using this subject has a RELEASED/LOCKED grade
    sheet — changing the subject's code at that point would alter what
    reads as an official record, so a code change is blocked (admin can
    still force it through the explicit "Correct code" action)."""
    from approvals.models import GradeSheetStatus

    return ClassOffering.objects.filter(
        subject=subject, grade_sheets__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED]
    ).exists()


# ---------------------------------------------------------------------------
# Subject Offering — a Program Head checks a box next to a curriculum
# subject to "offer" it for the active (or an upcoming) semester; offering
# creates one ClassOffering per active section of that program/major/
# year_level and fills its roster from the section's active students.
# Preview (read-only) → commit (one atomic transaction) — same shape as
# offerings_import's/the AY wizard's existing preview-then-confirm flows.
# ---------------------------------------------------------------------------


def is_semester_locked(semester):
    """CLOSED semesters are read-only everywhere except admin grade
    corrections (which have their own RELEASED/LOCKED-only gate already,
    independent of this)."""
    return semester is not None and semester.status == SemesterStatus.CLOSED


def offering_allowed(semester):
    """Offering (and everything that follows from it -- classes, roster,
    instructor assignment) is allowed for ACTIVE and UPCOMING semesters,
    so the next semester can be planned ahead; never for CLOSED."""
    return semester is not None and semester.status != SemesterStatus.CLOSED


def offerable_subjects_for(program, major, semester):
    """Curriculum subjects for this program/major, for `semester`'s own
    term, that don't already have a SubjectOffering this semester."""
    entries = (
        CurriculumEntry.objects.filter(program=program, major=major, term=semester.term)
        .select_related("subject")
        .order_by("year_level", "subject__code")
    )
    offered_subject_ids = set(
        SubjectOffering.objects.filter(semester=semester, program=program, major=major).values_list(
            "subject_id", flat=True
        )
    )
    return [entry for entry in entries if entry.subject_id not in offered_subject_ids]


def _resolve_offering_sections_and_conflicts(subject, program, major, year_level, semester):
    """Shared by preview_subject_offerings (curriculum-driven) and
    preview_adhoc_offering ("Offer another subject…", not in the
    curriculum) — resolves the active section(s) for this scope/year_level
    in the semester's academic year and flags a "shared subject" conflict
    per section. Returns (plan_rows, has_sections)."""
    sections = Section.objects.filter(program=program, major=major, year_level=year_level, academic_year=semester.academic_year)
    if not sections.exists():
        return [], False

    plan_rows = []
    for section in sections:
        conflict_class = (
            ClassOffering.objects.filter(subject=subject, semester=semester, sections__year_level=year_level)
            .exclude(sections=section)
            .exclude(sections__program=program, sections__major=major)
            .distinct()
            .first()
        )
        plan_rows.append(
            {
                "subject": subject,
                "program": program,
                "major": major,
                "year_level": year_level,
                "section": section,
                "conflict_class": conflict_class,
            }
        )
    return plan_rows, True


def preview_subject_offerings(curriculum_entry_ids, semester):
    """Read-only. For each requested CurriculumEntry: resolves the active
    section(s) of its program/major/year_level in the semester's academic
    year (one plan row per section — "one class per active section", per
    spec), flags a "shared subject" conflict when another program/major
    already has a class for the same subject+semester+year_level, and
    reports (separately) any entry with no matching section at all, and
    any entry already offered this semester (defense in depth — the UI
    disables an already-offered checkbox, but a stale page shouldn't be
    trusted blindly). Returns a dict of plain dicts holding live model
    instances — the view is responsible for whatever session-safe id-only
    serialization it needs for its own preview→confirm round trip."""
    entries = CurriculumEntry.objects.filter(pk__in=curriculum_entry_ids).select_related(
        "subject", "program", "major"
    )
    already_offered_keys = set(
        SubjectOffering.objects.filter(semester=semester).values_list("program_id", "major_id", "year_level", "subject_id")
    )

    plan_rows = []
    missing_section_rows = []
    already_offered_rows = []

    for entry in entries:
        key = (entry.program_id, entry.major_id, entry.year_level, entry.subject_id)
        if key in already_offered_keys:
            already_offered_rows.append({"curriculum_entry": entry, "subject": entry.subject})
            continue

        entry_rows, has_sections = _resolve_offering_sections_and_conflicts(
            entry.subject, entry.program, entry.major, entry.year_level, semester
        )
        if not has_sections:
            missing_section_rows.append(
                {
                    "curriculum_entry": entry,
                    "subject": entry.subject,
                    "program": entry.program,
                    "major": entry.major,
                    "year_level": entry.year_level,
                }
            )
            continue
        for row in entry_rows:
            row["curriculum_entry"] = entry
        plan_rows.extend(entry_rows)

    return {
        "plan_rows": plan_rows,
        "missing_section_rows": missing_section_rows,
        "already_offered_rows": already_offered_rows,
    }


def preview_adhoc_offering(subject, program, major, year_level, semester):
    """"Offer another subject…" — a subject not in this program/major's
    curriculum for this term, offered anyway via an explicit searchable
    picker + warning. Same conflict/missing-section resolution as the
    curriculum-driven path, just with no CurriculumEntry to key off (each
    plan row's "curriculum_entry" is None)."""
    already_offered = SubjectOffering.objects.filter(
        semester=semester, program=program, major=major, year_level=year_level, subject=subject
    ).exists()
    if already_offered:
        return {"plan_rows": [], "missing_section_rows": [], "already_offered_rows": [{"subject": subject}]}

    plan_rows, has_sections = _resolve_offering_sections_and_conflicts(subject, program, major, year_level, semester)
    for row in plan_rows:
        row["curriculum_entry"] = None
    missing_section_rows = (
        []
        if has_sections
        else [{"curriculum_entry": None, "subject": subject, "program": program, "major": major, "year_level": year_level}]
    )
    return {"plan_rows": plan_rows, "missing_section_rows": missing_section_rows, "already_offered_rows": []}


def fill_roster_from_section(class_offering, section):
    """Adds every active student of `section` to `class_offering`'s roster
    (idempotent — safe to call again, e.g. when Combine adds a section to
    an already-populated class). Returns how many roster entries were
    newly created. Modeled directly on roster_import.commit_import's
    identical ClassRosterEntry.objects.get_or_create(...) call."""
    added = 0
    profiles = StudentProfile.objects.filter(section=section, status=StudentProfile.Status.ACTIVE).select_related("user")
    for profile in profiles:
        _, created = ClassRosterEntry.objects.get_or_create(
            student=profile.user, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
        if created:
            added += 1
    return added


def commit_subject_offerings(plan_rows, decisions, semester, actor, is_admin_override=False):
    """One atomic transaction. `decisions` is {str(conflict_class_id):
    "combine"|"separate"} — a conflicting row with no decision defaults to
    "combine" per spec. Returns counts for the summary toast. Logs one
    AcademicSetupChangeLog row per newly-created SubjectOffering (not per
    class — the classes it spawns are an implicit detail of the offering,
    recorded in that row's `details`, to avoid doubling up with the
    existing per-class CREATED logging used by manual class creation)."""
    offerings_created = 0
    classes_created = 0
    students_added = 0
    offering_by_key = {}

    with transaction.atomic():
        for row in plan_rows:
            subject = row["subject"]
            program = row["program"]
            major = row["major"]
            year_level = row["year_level"]
            section = row["section"]
            conflict_class = row["conflict_class"]

            key = (program.id, major.id if major else None, year_level, subject.id)
            subject_offering = offering_by_key.get(key)
            is_new_offering = subject_offering is None
            if is_new_offering:
                subject_offering = SubjectOffering.objects.create(
                    semester=semester, program=program, major=major, year_level=year_level, subject=subject, created_by=actor
                )
                offering_by_key[key] = subject_offering
                offerings_created += 1

            decision = decisions.get(str(conflict_class.id), "combine") if conflict_class else None
            combine = conflict_class is not None and decision != "separate"

            if combine:
                class_offering = conflict_class
                if not class_offering.sections.filter(pk=section.pk).exists():
                    class_offering.sections.add(section)
                if class_offering.offering_id is None:
                    class_offering.offering = subject_offering
                    class_offering.save(update_fields=["offering"])
            else:
                class_offering = ClassOffering.objects.create(subject=subject, semester=semester, offering=subject_offering)
                class_offering.snapshot_subject()
                class_offering.save(
                    update_fields=["subject_code_snapshot", "subject_title_snapshot", "subject_units_snapshot"]
                )
                class_offering.sections.add(section)
                classes_created += 1

            students_added += fill_roster_from_section(class_offering, section)

            if is_new_offering:
                AcademicSetupChangeLog.objects.create(
                    model_name=AcademicSetupChangeLog.ModelName.OFFERING,
                    object_id=subject_offering.pk,
                    object_repr=str(subject_offering),
                    action=AcademicSetupChangeLog.Action.OFFERED,
                    program=program,
                    major=major,
                    actor=actor,
                    is_admin_override=is_admin_override,
                )

    return {"offerings_created": offerings_created, "classes_created": classes_created, "students_added": students_added}


def withdraw_offering(offering, actor):
    """Deletes `offering` and every class it created, but only if none of
    those classes has a score encoded or a submitted-or-later grade sheet.
    Returns (True, None) on success, or (False, reason) if blocked — never
    partially deletes."""
    from approvals.services import is_class_editable
    from grading.models import Score

    classes = list(offering.class_offerings.all())
    blocking = [
        class_offering
        for class_offering in classes
        if Score.objects.filter(roster_entry__class_offering=class_offering, score__isnull=False).exists()
        or not is_class_editable(class_offering)
    ]
    if blocking:
        names = ", ".join(str(c) for c in blocking)
        return False, f"Can't withdraw — {names} already has scores or a submitted grade sheet."

    with transaction.atomic():
        AcademicSetupChangeLog.objects.create(
            model_name=AcademicSetupChangeLog.ModelName.OFFERING,
            object_id=offering.pk,
            object_repr=str(offering),
            action=AcademicSetupChangeLog.Action.WITHDRAWN,
            program=offering.program,
            major=offering.major,
            actor=actor,
            is_admin_override=False,
            details={"classes_deleted": len(classes)},
        )
        for class_offering in classes:
            # ClassRosterEntry.class_offering is PROTECT -- clear the
            # roster first, or the class delete below raises ProtectedError.
            class_offering.roster_entries.all().delete()
            class_offering.delete()
        offering.delete()

    return True, None


def close_semester(semester, actor):
    """Closes `semester` (status=CLOSED, is_active=False) once every one
    of its classes' grade sheets is LOCKED, or its end_date has already
    passed. Returns (True, None) or (False, reason)."""
    from django.utils import timezone

    from approvals.models import GradeSheet, GradeSheetStatus

    end_date_passed = bool(semester.end_date and semester.end_date <= timezone.localdate())
    all_locked = not GradeSheet.objects.filter(class_offering__semester=semester).exclude(
        status=GradeSheetStatus.LOCKED
    ).exists()

    if not (all_locked or end_date_passed):
        return False, "Not every grade sheet is locked yet, and the semester's end date hasn't passed."

    semester.status = SemesterStatus.CLOSED
    semester.is_active = False
    semester.save(update_fields=["status", "is_active"])

    AcademicSetupChangeLog.objects.create(
        model_name=AcademicSetupChangeLog.ModelName.SEMESTER,
        object_id=semester.pk,
        object_repr=str(semester),
        action=AcademicSetupChangeLog.Action.CLOSED,
        actor=actor,
        is_admin_override=True,
    )
    return True, None


def class_status_chip(class_offering):
    """"needs_instructor" / "needs_schedule" / "ready" — drives the Classes
    page's status chip and filter."""
    if class_offering.instructor_id is None:
        return "needs_instructor"
    if not class_offering.schedule:
        return "needs_schedule"
    return "ready"
