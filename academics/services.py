"""Teaching-load assignment: Program Heads assign which instructor teaches
each class in their program (CITCI confirmed practice); Admin keeps the
ability to set/change it too, as a logged "admin override". Pure functions
— no view/HTTP concerns; views call these and translate ValidationError to
a form error.
"""

import re
import secrets
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    AcademicSetupChangeLog,
    AcademicYear,
    ClassJoinRequest,
    ClassOffering,
    ClassRosterEntry,
    CurriculumEntry,
    Section,
    SectionMembership,
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
        raise ValidationError("This semester is closed. The instructor can no longer be changed.")

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


def build_offering_rows(subject, program, major, year_level, semester):
    """Shared by preview_subject_offerings (curriculum-driven),
    preview_adhoc_offering ("Offer another subject…", not in the
    curriculum), and preview_manage_sections (re-opening an existing
    offering) — resolves every active section for this scope/year_level in
    the semester's academic year, one row per section, and flags:
    - `conflict_class`: an existing class for the same subject+semester+
      year_level from a DIFFERENT program/major (the Combine toggle's
      backend metadata).
    - `already_offered`: this section is already covered by a class
      belonging to THIS subject's existing SubjectOffering for this scope,
      if one exists — checked+disabled in the matrix, never re-created.
    Each row also carries `combine: False` as the default the matrix form
    will override. Returns (rows, has_sections)."""
    sections = Section.objects.filter(program=program, major=major, year_level=year_level, academic_year=semester.academic_year)
    if not sections.exists():
        return [], False

    existing_offering = SubjectOffering.objects.filter(
        semester=semester, program=program, major=major, year_level=year_level, subject=subject
    ).first()
    covered_section_ids = set(existing_offering.covered_sections.values_list("pk", flat=True)) if existing_offering else set()

    rows = []
    for section in sections:
        conflict_class = (
            ClassOffering.objects.filter(subject=subject, semester=semester, sections__year_level=year_level)
            .exclude(sections=section)
            .exclude(sections__program=program, sections__major=major)
            .distinct()
            .first()
        )
        rows.append(
            {
                "subject": subject,
                "program": program,
                "major": major,
                "year_level": year_level,
                "section": section,
                "conflict_class": conflict_class,
                "already_offered": section.pk in covered_section_ids,
                "combine": False,
            }
        )
    return rows, True


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

        entry_rows, has_sections = build_offering_rows(
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

    plan_rows, has_sections = build_offering_rows(subject, program, major, year_level, semester)
    for row in plan_rows:
        row["curriculum_entry"] = None
    missing_section_rows = (
        []
        if has_sections
        else [{"curriculum_entry": None, "subject": subject, "program": program, "major": major, "year_level": year_level}]
    )
    return {"plan_rows": plan_rows, "missing_section_rows": missing_section_rows, "already_offered_rows": []}


def preview_manage_sections(offering):
    """Re-opens the matrix for one already-offered subject: same rows as a
    fresh offer, but with already-covered sections pre-checked+disabled.
    Ticking a new section adds a class/joins the combine group the same
    way commit_subject_offerings always has; unticking one already
    `already_offered` is a withdraw, resolved by the caller via the same
    per-section removal `withdraw_offering_sections` uses."""
    rows, has_sections = build_offering_rows(offering.subject, offering.program, offering.major, offering.year_level, offering.semester)
    for row in rows:
        row["curriculum_entry"] = None
    return {"plan_rows": rows, "missing_section_rows": [] if has_sections else [{"subject": offering.subject}], "already_offered_rows": []}


def fill_roster_from_section(class_offering, section):
    """Adds every active student currently a SectionMembership member of
    `section` FOR THIS CLASS'S OWN SEMESTER to `class_offering`'s roster
    (idempotent — safe to call again, e.g. when Combine adds a section to
    an already-populated class, or "Sync class lists from sections").
    Returns how many roster entries were newly created. Modeled directly
    on roster_import.commit_import's identical
    ClassRosterEntry.objects.get_or_create(...) call."""
    added = 0
    memberships = SectionMembership.objects.filter(
        section=section, semester=class_offering.semester, student__student_profile__status=StudentProfile.Status.ACTIVE
    ).select_related("student")
    for membership in memberships:
        _, created = ClassRosterEntry.objects.get_or_create(
            student=membership.student, class_offering=class_offering, defaults={"status": ClassRosterEntry.Status.ACTIVE}
        )
        if created:
            added += 1
    return added


def commit_subject_offerings(plan_rows, semester, actor, is_admin_override=False):
    """One atomic transaction. Each row carries its own `combine` flag
    (default False — one class per ticked section); a row already flagged
    `already_offered` is skipped (nothing to create, matrix cells for
    covered sections are checked+disabled and never reach here as new
    work). combine=True rows for the same (program, major, year_level,
    subject) all land on one class, reusing `conflict_class` if the matrix
    detected an existing cross-program class to join instead of creating a
    fresh one. Returns counts for the summary toast. Logs one
    AcademicSetupChangeLog row per newly-created SubjectOffering (not per
    class — the classes it spawns are an implicit detail of the offering,
    recorded in that row's `details`, to avoid doubling up with the
    existing per-class CREATED logging used by manual class creation)."""
    offerings_created = 0
    classes_created = 0
    students_added = 0
    offering_by_key = {}
    combine_class_by_key = {}

    with transaction.atomic():
        for row in plan_rows:
            if row.get("already_offered"):
                continue

            subject = row["subject"]
            program = row["program"]
            major = row["major"]
            year_level = row["year_level"]
            section = row["section"]
            conflict_class = row["conflict_class"]
            combine = row.get("combine", False)

            key = (program.id, major.id if major else None, year_level, subject.id)
            subject_offering = offering_by_key.get(key)
            if subject_offering is None:
                subject_offering = SubjectOffering.objects.filter(
                    semester=semester, program=program, major=major, year_level=year_level, subject=subject
                ).first()
            is_new_offering = subject_offering is None
            if is_new_offering:
                subject_offering = SubjectOffering.objects.create(
                    semester=semester, program=program, major=major, year_level=year_level, subject=subject, created_by=actor
                )
                offerings_created += 1
            offering_by_key[key] = subject_offering

            if combine:
                class_offering = combine_class_by_key.get(key)
                if class_offering is None:
                    class_offering = conflict_class
                    if class_offering is None:
                        class_offering = ClassOffering.objects.create(subject=subject, semester=semester, offering=subject_offering)
                        class_offering.snapshot_subject()
                        class_offering.save(
                            update_fields=["subject_code_snapshot", "subject_title_snapshot", "subject_units_snapshot"]
                        )
                        classes_created += 1
                    combine_class_by_key[key] = class_offering
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


def withdraw_offering_section(offering, section, actor):
    """Removes just `section`'s class coverage from `offering` — the
    Manage Sections / Classes-page per-badge "x" primitive. Skipped (with
    a reason) if that section's class has scores or a submitted-or-later
    grade sheet; a shared/combined class only loses this one section, it
    is never deleted outright unless this was its last section. Calls
    sync_offering_after_section_change afterward so Principle 0 holds.
    Returns (True, None) or (False, reason)."""
    class_offering = ClassOffering.objects.filter(offering=offering, sections=section).first()
    if class_offering is None:
        return True, None
    if class_has_scores_or_submitted_sheet(class_offering):
        return False, f"{offering.subject.code} · {section.short_label} has scores or a submitted grade sheet."

    with transaction.atomic():
        class_offering.sections.remove(section)
        if class_offering.sections.count() == 0:
            class_offering.roster_entries.all().delete()
            class_offering.delete()
        sync_offering_after_section_change(offering)

    return True, None


def class_has_scores_or_submitted_sheet(class_offering):
    """The one predicate every "can this class/section safely be torn
    down" check in this module shares: a score encoded, or a grade sheet
    that's already left DRAFT/RETURNED. Used by withdraw_offering,
    ph_class_leave ("withdraw this section"), and split_class/
    combine_classes."""
    from approvals.services import is_class_editable
    from grading.models import Score

    return (
        Score.objects.filter(roster_entry__class_offering=class_offering, score__isnull=False).exists()
        or not is_class_editable(class_offering)
    )


def withdraw_offering(offering, actor):
    """Deletes `offering` and every class it created, but only if none of
    those classes has a score encoded or a submitted-or-later grade sheet.
    Returns (True, None) on success, or (False, reason) if blocked — never
    partially deletes."""
    classes = list(offering.class_offerings.all())
    blocking = [class_offering for class_offering in classes if class_has_scores_or_submitted_sheet(class_offering)]
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


def withdraw_offerings_bulk(offerings, actor):
    """Loops withdraw_offering over many offerings for the three bulk-
    withdraw entry points (selected rows, a Year Level card's "Withdraw
    all", the toolbar's "Withdraw all") — one skip-with-reason per
    offering that can't be withdrawn, never a partial withdraw of a single
    offering's own classes. Returns (withdrawn, skipped) where `skipped`
    is a list of (offering, reason) tuples, for the result toast's
    "X skipped: ..." list."""
    withdrawn = []
    skipped = []
    for offering in offerings:
        offering_id = offering.pk  # withdraw_offering() deletes the row -- .pk goes None after
        ok, reason = withdraw_offering(offering, actor)
        if ok:
            withdrawn.append(offering_id)
        else:
            skipped.append((offering, reason))
    return withdrawn, skipped


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


# ---------------------------------------------------------------------------
# Section letters — "BSED-ENG 1-A", or just "BSED-ENG 1" when there's only
# one section at that year level (see Section.name's validator for the
# single-uppercase-letter rule this suggests into).
# ---------------------------------------------------------------------------


def next_section_letter(program, major, academic_year, year_level):
    """"A" if no section exists yet in this exact scope, else the letter
    after the current highest one. Blank/un-lettered existing sections are
    treated as coming before "A" (a plain .exclude(name="") scan), so the
    very first section ever created in a scope still suggests "A" rather
    than "" forever."""
    existing_letters = sorted(
        Section.objects.filter(program=program, major=major, academic_year=academic_year, year_level=year_level)
        .exclude(name="")
        .values_list("name", flat=True)
    )
    if not existing_letters:
        return "A"
    next_ord = ord(existing_letters[-1]) + 1
    if next_ord > ord("Z"):
        return ""
    return chr(next_ord)


def move_students_to_section(student_ids, target_section, semester, actor, is_admin_override=False):
    """Bulk-sets/moves students' SectionMembership to `target_section` FOR
    `semester` — restricted by the caller to sections sharing the same
    program/major/year_level (scoping.py's existing in-scope filter
    already enforces who may touch which sections; this function trusts
    its caller to have validated that `target_section` is actually a
    valid destination). Upserts (a student has at most one section per
    semester) — "moving" and "adding for the first time" are the same
    operation here. Returns the number of students touched."""
    moved = 0
    for student_id in student_ids:
        SectionMembership.objects.update_or_create(
            student_id=student_id, semester=semester, defaults={"section": target_section}
        )
        moved += 1
    if moved:
        AcademicSetupChangeLog.objects.create(
            model_name=AcademicSetupChangeLog.ModelName.SECTION,
            object_id=target_section.pk,
            object_repr=str(target_section),
            action=AcademicSetupChangeLog.Action.STUDENTS_MOVED,
            program=target_section.program,
            major=target_section.major,
            actor=actor,
            is_admin_override=is_admin_override,
            details={"moved_count": moved, "to_section_id": target_section.pk, "semester_id": semester.pk},
        )
    return moved


def remove_section_membership(student_ids, semester, actor):
    """Removes selected students' SectionMembership for `semester`
    entirely (they stay enrolled on the account level — Program/Major —
    just without a section for this one term, same as any irregular/
    join-by-code student). Returns the count removed."""
    return SectionMembership.objects.filter(student_id__in=student_ids, semester=semester).delete()[0]


def copy_section_membership_to_semester(section, from_semester, to_semester, actor):
    """"Copy from previous semester" — every student who was a member of
    `section` in `from_semester` becomes a member of the SAME section in
    `to_semester` (e.g. 1st Sem -> 2nd Sem of the same academic year).
    Never overwrites a student who already has a membership for
    `to_semester` (an irregular already placed elsewhere, or moved
    manually ahead of time) — returns the count actually added."""
    existing_student_ids = set(
        SectionMembership.objects.filter(semester=to_semester).values_list("student_id", flat=True)
    )
    added = 0
    with transaction.atomic():
        for membership in SectionMembership.objects.filter(section=section, semester=from_semester):
            if membership.student_id in existing_student_ids:
                continue
            SectionMembership.objects.create(student_id=membership.student_id, section=section, semester=to_semester)
            added += 1
    if added:
        AcademicSetupChangeLog.objects.create(
            model_name=AcademicSetupChangeLog.ModelName.SECTION,
            object_id=section.pk,
            object_repr=str(section),
            action=AcademicSetupChangeLog.Action.STUDENTS_MOVED,
            program=section.program,
            major=section.major,
            actor=actor,
            is_admin_override=False,
            details={"copied_count": added, "from_semester_id": from_semester.pk, "to_semester_id": to_semester.pk},
        )
    return added


def preview_promote_students(section, from_semester, target_section, to_semester):
    """Preview for the Program Head "Promote" action (e.g. BSED-ENG 1-A ->
    BSED-ENG 2-A for a new academic year): every student who was a member
    of `section` in `from_semester`, flagged if they already have a
    membership for `to_semester` elsewhere (an irregular the UI should
    leave unchecked by default, not silently move)."""
    existing_student_ids = set(
        SectionMembership.objects.filter(semester=to_semester).values_list("student_id", flat=True)
    )
    rows = []
    for membership in (
        SectionMembership.objects.filter(section=section, semester=from_semester)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    ):
        rows.append(
            {
                "student": membership.student,
                "already_placed": membership.student_id in existing_student_ids,
            }
        )
    return rows


def commit_promote_students(student_ids, target_section, to_semester, actor):
    """Creates a SectionMembership in `target_section`/`to_semester` for
    each student id, skipping anyone who already has one for that
    semester (never overwrites). Returns the count actually promoted."""
    promoted = 0
    with transaction.atomic():
        for student_id in student_ids:
            _, created = SectionMembership.objects.get_or_create(
                student_id=student_id, semester=to_semester, defaults={"section": target_section}
            )
            if created:
                promoted += 1
    if promoted:
        AcademicSetupChangeLog.objects.create(
            model_name=AcademicSetupChangeLog.ModelName.SECTION,
            object_id=target_section.pk,
            object_repr=str(target_section),
            action=AcademicSetupChangeLog.Action.STUDENTS_MOVED,
            program=target_section.program,
            major=target_section.major,
            actor=actor,
            is_admin_override=False,
            details={"promoted_count": promoted, "to_section_id": target_section.pk, "to_semester_id": to_semester.pk},
        )
    return promoted


def sync_offering_after_section_change(subject_offering):
    """The single chokepoint for Principle 0: a SubjectOffering exists iff
    it still has at least one class. Every code path that can reduce a
    SubjectOffering's class count to zero (Split, Combine, "withdraw this
    section", Manage Sections) calls this afterward -- not just the
    dedicated withdraw-offering button -- so the Subjects page's "Offered"
    state can never drift out of sync with what Classes actually shows.
    Deletes `subject_offering` if it has no classes left; a no-op
    otherwise. Safe to call with None (a class not linked to any
    offering, e.g. a manually-created one)."""
    if subject_offering is None:
        return
    if not subject_offering.class_offerings.exists():
        subject_offering.delete()


# ---------------------------------------------------------------------------
# Class join codes — a student self-join request that an instructor still
# has to approve (never an automatic roster add). Complements the existing
# Program-Head section auto-fill and instructor manual-add/import roster
# paths, not a replacement for either.
# ---------------------------------------------------------------------------

# Uppercase letters + digits, excluding visually-ambiguous 0/O/1/I.
JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 7
_JOIN_RATE_LIMIT_MAX_ATTEMPTS = 10
_JOIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60


def generate_join_code():
    """A random 7-char code, retried on the rare DB collision (unique
    across every class ever, including classes whose code was reset —
    the old code is simply abandoned, never reassigned)."""
    for _ in range(20):
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        if not ClassOffering.objects.filter(join_code=code).exists():
            return code
    raise RuntimeError("Could not generate a unique join code after 20 attempts.")


def ensure_join_code(class_offering):
    """Lazily assigns a join code the first time anyone opens the Invite
    Students card for a class created before this feature, or that has
    never had one for any other reason. Returns the (possibly freshly
    assigned) code."""
    if not class_offering.join_code:
        class_offering.join_code = generate_join_code()
        class_offering.save(update_fields=["join_code"])
    return class_offering.join_code


def reset_join_code(class_offering, actor):
    """Old code stops working immediately (a pending request already
    filed under the old code is untouched — it was validated against the
    class, not the code string, at request time)."""
    class_offering.join_code = generate_join_code()
    class_offering.save(update_fields=["join_code"])
    return class_offering.join_code


def set_join_enabled(class_offering, enabled, actor):
    class_offering.join_enabled = enabled
    class_offering.save(update_fields=["join_enabled"])


def _join_rate_limit_cache_key(user):
    return f"join_code_attempts:{user.id}"


def check_join_rate_limit(user):
    """True if `user` may try another join code right now. Simple
    fixed-window counter (cache.add/incr — no Celery/Redis in this
    project, LocMemCache is fine at this scale, same philosophy as
    everywhere else synchronous in this codebase) -- 10 attempts per 15
    minutes, to slow down code-guessing without needing django-axes-style
    infrastructure for what's a much lower-stakes guess space already
    gated behind a logged-in STUDENT account."""
    key = _join_rate_limit_cache_key(user)
    count = cache.get(key, 0)
    return count < _JOIN_RATE_LIMIT_MAX_ATTEMPTS


def record_join_attempt(user):
    key = _join_rate_limit_cache_key(user)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, _JOIN_RATE_LIMIT_WINDOW_SECONDS)


class JoinCodeError(ValidationError):
    """Raised for every student-facing join-code rejection reason —
    views catch this and show exc.messages[0] directly, same convention
    as every other ValidationError-raising service in this module."""


def resolve_join_code(code):
    """Looks up a class by its join code (case/space-insensitive), or
    raises JoinCodeError. Does not check eligibility -- callers that also
    need join_enabled/semester/grade-sheet checks call
    check_join_eligibility separately (the join confirmation page shows
    the class before the student commits, so code-resolution and
    eligibility are deliberately two steps)."""
    normalized = (code or "").strip().upper()
    if not normalized:
        raise JoinCodeError("Enter a join code.")
    class_offering = ClassOffering.objects.filter(join_code=normalized).select_related("subject", "semester", "instructor").first()
    if class_offering is None:
        raise JoinCodeError("That join code isn't valid. Double-check it with your instructor.")
    return class_offering


def check_join_eligibility(class_offering, student):
    """Raises JoinCodeError with a clear, specific reason if `student`
    can't join `class_offering` right now; returns silently if they can."""
    if not student.id_number:
        raise JoinCodeError("Your account has no ID number on file yet. Ask the Registrar/Admin to add it before joining a class.")
    if not class_offering.join_enabled:
        raise JoinCodeError("This class isn't accepting join requests right now.")
    if not class_offering.semester.is_active:
        raise JoinCodeError("This class isn't in the current active semester.")

    from approvals.services import is_class_editable

    if not is_class_editable(class_offering):
        raise JoinCodeError("Grades for this class have already been submitted. Ask your instructor to add you manually.")
    if ClassRosterEntry.objects.filter(student=student, class_offering=class_offering).exists():
        raise JoinCodeError("You're already in this class.")
    if ClassJoinRequest.objects.filter(
        student=student, class_offering=class_offering, status=ClassJoinRequest.Status.PENDING
    ).exists():
        raise JoinCodeError("You already have a pending request for this class.")


def request_to_join(class_offering, student):
    """Creates the PENDING ClassJoinRequest and notifies the instructor.
    Raises JoinCodeError (never silently fails) if `student` isn't
    eligible right now."""
    from dashboard.services import notify

    check_join_eligibility(class_offering, student)
    join_request = ClassJoinRequest.objects.create(class_offering=class_offering, student=student)

    if class_offering.instructor_id:
        pending_count = ClassJoinRequest.objects.filter(
            class_offering=class_offering, status=ClassJoinRequest.Status.PENDING
        ).count()
        notify(
            class_offering.instructor,
            f"New join request: {class_offering}",
            f"{student.full_name} wants to join {class_offering}. {pending_count} request"
            f"{'s' if pending_count != 1 else ''} pending.",
            link="/academics/classes/%d/join-requests/" % class_offering.pk,
        )
    return join_request


def cancel_join_request(join_request, student):
    if join_request.student_id != student.id:
        raise PermissionError("Not your request.")
    if join_request.status != ClassJoinRequest.Status.PENDING:
        raise JoinCodeError("This request has already been decided.")
    join_request.status = ClassJoinRequest.Status.CANCELLED
    join_request.decided_at = timezone.now()
    join_request.save(update_fields=["status", "decided_at"])


def approve_join_request(join_request, actor):
    """Creates the roster entry (source=JOIN_CODE) and notifies the
    student. Re-checks eligibility at decision time, not just at request
    time -- the grade sheet could have been submitted in between."""
    from dashboard.services import notify

    if join_request.status != ClassJoinRequest.Status.PENDING:
        raise JoinCodeError("This request has already been decided.")

    from approvals.services import is_class_editable

    if not is_class_editable(join_request.class_offering):
        raise JoinCodeError("Grades for this class have already been submitted. This request can no longer be approved.")

    with transaction.atomic():
        ClassRosterEntry.objects.get_or_create(
            student=join_request.student,
            class_offering=join_request.class_offering,
            defaults={"status": ClassRosterEntry.Status.ACTIVE, "source": ClassRosterEntry.Source.JOIN_CODE},
        )
        join_request.status = ClassJoinRequest.Status.APPROVED
        join_request.decided_by = actor
        join_request.decided_at = timezone.now()
        join_request.save(update_fields=["status", "decided_by", "decided_at"])

    notify(
        join_request.student,
        f"You're in — {join_request.class_offering}",
        f"Your request to join {join_request.class_offering} was approved.",
        link="/academics/my-classes/",
    )


def reject_join_request(join_request, actor, reason=""):
    from dashboard.services import notify

    if join_request.status != ClassJoinRequest.Status.PENDING:
        raise JoinCodeError("This request has already been decided.")

    join_request.status = ClassJoinRequest.Status.REJECTED
    join_request.decided_by = actor
    join_request.decided_at = timezone.now()
    join_request.reject_reason = reason
    join_request.save(update_fields=["status", "decided_by", "decided_at", "reject_reason"])

    notify(
        join_request.student,
        f"Request declined — {join_request.class_offering}",
        reason or f"Your request to join {join_request.class_offering} was declined.",
        link="/academics/my-classes/",
    )


def bulk_decide_join_requests(join_requests, actor, approve, reason=""):
    """Loops approve_join_request/reject_join_request per row so one
    already-decided/no-longer-eligible request is skipped with a reason
    instead of failing the whole batch -- same "skip with reason, never
    fail the batch" shape as withdraw_offerings_bulk."""
    decided = 0
    skipped = []
    for join_request in join_requests:
        try:
            if approve:
                approve_join_request(join_request, actor)
            else:
                reject_join_request(join_request, actor, reason)
            decided += 1
        except JoinCodeError as exc:
            skipped.append((join_request, str(exc.messages[0]) if hasattr(exc, "messages") else str(exc)))
    return decided, skipped


def join_request_section_match(join_request):
    """True if the requesting student's SectionMembership for the class's
    OWN semester is one of the class's sections -- backs the Pending
    Requests list's "Matches section X ✓" / "Different section ⚠" badge.
    None if the student has no section membership for that semester (a
    TCP-style/irregular student, or one who only ever joins by code --
    this is deliberately not an error)."""
    section_id = SectionMembership.objects.filter(
        student_id=join_request.student_id, semester_id=join_request.class_offering.semester_id
    ).values_list("section_id", flat=True).first()
    if not section_id:
        return None
    return join_request.class_offering.sections.filter(pk=section_id).exists()
