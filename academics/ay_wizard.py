"""New Academic Year wizard — pure preview/commit functions for the four
steps (new A.Y. + semesters, section structure, student promotion,
summary). No existing wizard pattern in the codebase to reuse (no
django-formtools) — views orchestrate the session-stash between steps the
same way academics/roster_import.py and offerings_import.py do, just with
more steps. Nothing is written to the database until step 4's commit,
which is one transaction."""

from django.db import transaction

from .models import AcademicYear, Section, SectionMembership, Semester, StudentProfile, Term


def step1_preview(start_year):
    """Just the facts about the year being proposed — whether it already
    exists (which blocks continuing, never silently reused)."""
    return {
        "start_year": start_year,
        "end_year": start_year + 1,
        "already_exists": AcademicYear.objects.filter(start_year=start_year).exists(),
        "terms": [{"term": value, "label": label} for value, label in Term.choices],
    }


def step2_preview_sections(source_academic_year):
    """Sections to recreate verbatim (same program/major/year_level/name)
    for the new academic year — this step does NOT promote year levels,
    it only recreates the structure (e.g. BSED-ENG 1-4, BSED-SS 1-4, TCP)."""
    sections = Section.objects.filter(academic_year=source_academic_year).select_related("program", "major")
    return [
        {
            "program_id": s.program_id,
            "major_id": s.major_id,
            "year_level": s.year_level,
            "name": s.name,
            "label": str(s),
        }
        for s in sections
    ]


def _section_key(program_id, major_id, year_level, name):
    return (program_id, major_id, year_level, name)


def _latest_semester_membership_subquery(source_academic_year):
    """The ONE semester of `source_academic_year` to read promotion-time
    section membership from: the active one if it belongs to this
    academic year, else the latest term that exists for it. A student can
    have at most one membership per semester, but could have different
    ones across 1st/2nd Sem -- this picks whichever semester is the
    "current" snapshot of where students actually are."""
    semester = Semester.objects.filter(academic_year=source_academic_year, is_active=True).first()
    if semester is None:
        semester = Semester.objects.filter(academic_year=source_academic_year).order_by("-term").first()
    return semester


def step3_preview_promotions(source_academic_year, new_sections):
    """Every ACTIVE student with a SectionMembership in source_academic_year's
    "current" semester (see _latest_semester_membership_subquery): resolves
    to either a promotion (year_level + 1, same program/major/name in the
    new year) or COMPLETED (4th year, or no year_level at all — e.g. TCP).
    `new_sections` is step 2's (not-yet-created) list — resolved by key,
    never guessed. A promotion target not present in that list is reported
    as unresolved rather than silently skipped or invented."""
    new_section_keys = {
        _section_key(s["program_id"], s["major_id"], s["year_level"], s["name"]) for s in new_sections
    }
    source_semester = _latest_semester_membership_subquery(source_academic_year)
    if source_semester is None:
        return []

    memberships = (
        SectionMembership.objects.filter(
            semester=source_semester, student__student_profile__status=StudentProfile.Status.ACTIVE
        )
        .select_related("student", "section", "section__program", "section__major")
        .order_by("section__program__code", "section__year_level", "student__last_name")
    )
    rows = []
    for membership in memberships:
        section = membership.section
        will_complete = section.year_level is None or section.year_level >= 4
        target_key = None
        unresolved = False
        if not will_complete:
            target_key = _section_key(section.program_id, section.major_id, section.year_level + 1, section.name)
            unresolved = target_key not in new_section_keys
        rows.append(
            {
                "profile_id": membership.student_id,
                "student": membership.student,
                "current_section": section,
                "will_complete": will_complete,
                "target_key": target_key,
                "unresolved": unresolved,
                "excluded": False,
            }
        )
    return rows


def step4_commit(start_year, term_values, sections_to_create, promotion_rows, actor, term_dates=None, source_academic_year=None):
    """One atomic transaction: creates the AcademicYear + its Semesters,
    creates every previewed Section, promotes/completes every non-excluded
    student (a promotion creates a SectionMembership in the new academic
    year's semester matching the SOURCE semester's term -- e.g. a 1st Sem
    promotion lands the student in the new year's own 1st Sem), and writes
    one AuditLog row summarizing the run (counts only — never a name/ID
    number). Never touches ClassOffering/GradeSheet/GradeSheetEntry rows
    in any prior semester.

    `term_dates` (optional): {term_value: (start_iso_or_None, end_iso_or_None)}
    from step 1's date fields, already validated there (range, within the
    academic year, no overlap among the terms being created) — applied
    here as-is, never re-validated."""
    from accounts.audit import log_audit
    from accounts.models import AuditLog
    from datetime import date as _date

    promoted = 0
    completed = 0
    excluded = 0
    term_dates = term_dates or {}
    source_term = None
    if source_academic_year is not None:
        source_semester = _latest_semester_membership_subquery(source_academic_year)
        source_term = source_semester.term if source_semester else None

    with transaction.atomic():
        academic_year = AcademicYear.objects.create(start_year=start_year)
        created_semesters = {}
        for term in term_values:
            start_iso, end_iso = term_dates.get(term, (None, None))
            created_semesters[term] = Semester.objects.create(
                academic_year=academic_year,
                term=term,
                start_date=_date.fromisoformat(start_iso) if start_iso else None,
                end_date=_date.fromisoformat(end_iso) if end_iso else None,
            )
        target_semester = created_semesters.get(source_term) if source_term else None

        created_sections = {}
        for s in sections_to_create:
            section = Section.objects.create(
                program_id=s["program_id"], major_id=s["major_id"], academic_year=academic_year,
                year_level=s["year_level"], name=s["name"],
            )
            created_sections[_section_key(s["program_id"], s["major_id"], s["year_level"], s["name"])] = section

        for row in promotion_rows:
            if row["excluded"]:
                excluded += 1
                continue
            profile = StudentProfile.objects.filter(user_id=row["profile_id"]).first()
            if profile is None:
                continue
            if row["will_complete"]:
                profile.status = StudentProfile.Status.COMPLETED
                profile.save(update_fields=["status"])
                completed += 1
            elif not row["unresolved"]:
                target_section = created_sections.get(row["target_key"])
                if target_section is None or target_semester is None:
                    continue
                SectionMembership.objects.update_or_create(
                    student_id=row["profile_id"], semester=target_semester, defaults={"section": target_section}
                )
                promoted += 1

        log_audit(
            actor,
            AuditLog.Action.ACADEMIC_YEAR_WIZARD_RUN,
            academic_year=str(academic_year),
            sections_created=len(created_sections),
            promoted=promoted,
            completed=completed,
            excluded=excluded,
        )

    return {
        "academic_year": academic_year,
        "sections_created": len(created_sections),
        "promoted": promoted,
        "completed": completed,
        "excluded": excluded,
    }
