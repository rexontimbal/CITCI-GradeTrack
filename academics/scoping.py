"""Program Head scope — a head can be assigned at PROGRAM level
(`Program.program_head`, covers every major in that program that has no
major-level head of its own) or at MAJOR level (`Major.program_head`,
takes precedence over the program-level catch-all for that one major).

This module is the single source of truth every object-level "does this
Program Head own X" check should use, replacing what used to be the same
`sections__program__program_head=user` / `program__program_head_id=
user.id` expression duplicated independently across ~10 files (academics,
approvals, dashboard, forecasting, grading, reports, accounts).

`scope_for(user)` returns `None` for an admin — "unrestricted" — rather
than an empty set, specifically so every caller is forced to branch on
"is this admin" before applying a filter, instead of accidentally
over-restricting an admin query by treating `None` as "no matches"."""

from django.db.models import Q

from .models import ClassOffering, Major, Program, Section, Subject


def scope_for(user):
    """None = unrestricted (admin). Else a set of (program_id,
    major_id-or-None) tuples. major_id=None means "this program, every
    major that has no major-level head of its own" — a program-level and
    a major-level assignment for the same user are both kept, since they
    mean different things downstream."""
    if user.is_admin_role:
        return None
    if not user.is_program_head:
        return set()

    scope = set()
    for program_id in Program.objects.filter(program_head=user).values_list("id", flat=True):
        scope.add((program_id, None))
    for program_id, major_id in Major.objects.filter(program_head=user).values_list("program_id", "id"):
        scope.add((program_id, major_id))
    return scope


def _scope_q(scope, program_field="program", major_field="major"):
    """OR's together one Q() clause per scope tuple, against a model with
    `program_field`/`major_field` FKs (possibly a multi-hop lookup path,
    e.g. "sections__program" for ClassOffering). An empty scope must
    produce a never-matching Q() — a bare Q() matches everything when
    passed to .filter(), which would silently unrestrict an empty-scope
    Program Head's queries."""
    q = Q()
    matched_any = False
    for program_id, major_id in scope:
        matched_any = True
        if major_id is None:
            q |= Q(**{program_field: program_id, f"{major_field}__program_head__isnull": True}) | Q(
                **{program_field: program_id, f"{major_field}__isnull": True}
            )
        else:
            q |= Q(**{major_field: major_id})
    return q if matched_any else Q(pk__in=[])


def sections_in_scope(user):
    scope = scope_for(user)
    if scope is None:
        return Section.objects.all()
    return Section.objects.filter(_scope_q(scope))


def subjects_editable_by(user):
    """Excludes shared/general subjects (program=None) — those stay
    admin-only to edit, per CLAUDE.md section 4's subject-catalog rule."""
    scope = scope_for(user)
    if scope is None:
        return Subject.objects.all()
    return Subject.objects.filter(_scope_q(scope), program__isnull=False)


def programs_in_scope(user):
    scope = scope_for(user)
    if scope is None:
        return Program.objects.all()
    return Program.objects.filter(pk__in={program_id for program_id, _ in scope})


def classes_in_scope(user, semester=None):
    """A class is in scope if ANY of its sections is — matches the "a
    class is visible/manageable by every head whose section is in it"
    rule for shared classes."""
    scope = scope_for(user)
    qs = ClassOffering.objects.all()
    if semester is not None:
        qs = qs.filter(semester=semester)
    if scope is None:
        return qs.distinct()
    return qs.filter(_scope_q(scope, program_field="sections__program", major_field="sections__major")).distinct()


def is_in_scope(user, program_id, major_id):
    """Membership check for one (program, major) pair — e.g. "can this
    Program Head edit a Section/Subject with this exact program/major?"
    Admin is always True."""
    scope = scope_for(user)
    if scope is None:
        return True
    if (program_id, major_id) in scope:
        return True
    if major_id is not None and (program_id, None) in scope:
        # Program-level scope only catches majors with no head of their own.
        return not Major.objects.filter(pk=major_id, program_head__isnull=False).exists()
    return False


def heads_for_class(class_offering):
    """Every User responsible for at least one of this class's sections —
    the *reverse* of scope_for: "who is this for," not "what's this
    user's scope." A section's major-level head if it has one, else the
    section's program's head (if any). Used for submit/notification
    fan-out (e.g. approvals.services._program_heads_for)."""
    from accounts.models import User

    head_ids = set()
    for section in class_offering.sections.select_related("program", "major"):
        if section.major_id and section.major.program_head_id:
            head_ids.add(section.major.program_head_id)
        elif section.program.program_head_id:
            head_ids.add(section.program.program_head_id)
    return list(User.objects.filter(id__in=head_ids))
