"""New Academic Year wizard — pure preview/commit functions for the four
steps (new A.Y. + semesters, section structure, student promotion,
summary). No existing wizard pattern in the codebase to reuse (no
django-formtools) — views orchestrate the session-stash between steps the
same way academics/roster_import.py and offerings_import.py do, just with
more steps. Nothing is written to the database until step 4's commit,
which is one transaction."""

from django.db import transaction

from .models import AcademicYear, Section, Semester, StudentProfile, Term


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


def step3_preview_promotions(source_academic_year, new_sections):
    """Every ACTIVE student currently in a section under source_academic_year:
    resolves to either a promotion (year_level + 1, same program/major/name
    in the new year) or COMPLETED (4th year, or no year_level at all — e.g.
    TCP). `new_sections` is step 2's (not-yet-created) list — resolved by
    key, never guessed. A promotion target not present in that list is
    reported as unresolved rather than silently skipped or invented."""
    new_section_keys = {
        _section_key(s["program_id"], s["major_id"], s["year_level"], s["name"]) for s in new_sections
    }
    profiles = (
        StudentProfile.objects.filter(status=StudentProfile.Status.ACTIVE, section__academic_year=source_academic_year)
        .select_related("user", "section", "section__program", "section__major")
        .order_by("section__program__code", "section__year_level", "user__last_name")
    )
    rows = []
    for profile in profiles:
        section = profile.section
        will_complete = section.year_level is None or section.year_level >= 4
        target_key = None
        unresolved = False
        if not will_complete:
            target_key = _section_key(section.program_id, section.major_id, section.year_level + 1, section.name)
            unresolved = target_key not in new_section_keys
        rows.append(
            {
                "profile_id": profile.id,
                "student": profile.user,
                "current_section": section,
                "will_complete": will_complete,
                "target_key": target_key,
                "unresolved": unresolved,
                "excluded": False,
            }
        )
    return rows


def step4_commit(start_year, term_values, sections_to_create, promotion_rows, actor):
    """One atomic transaction: creates the AcademicYear + its Semesters,
    creates every previewed Section, promotes/completes every non-excluded
    student, and writes one AuditLog row summarizing the run (counts only
    — never a name/ID number). Never touches ClassOffering/GradeSheet/
    GradeSheetEntry rows in any prior semester."""
    from accounts.audit import log_audit
    from accounts.models import AuditLog

    promoted = 0
    completed = 0
    excluded = 0

    with transaction.atomic():
        academic_year = AcademicYear.objects.create(start_year=start_year)
        for term in term_values:
            Semester.objects.create(academic_year=academic_year, term=term)

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
            profile = StudentProfile.objects.filter(pk=row["profile_id"]).first()
            if profile is None:
                continue
            if row["will_complete"]:
                profile.status = StudentProfile.Status.COMPLETED
                profile.save(update_fields=["status"])
                completed += 1
            elif not row["unresolved"]:
                target_section = created_sections.get(row["target_key"])
                if target_section is None:
                    continue
                profile.section = target_section
                profile.year_level = target_section.year_level
                profile.save(update_fields=["section", "year_level"])
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
