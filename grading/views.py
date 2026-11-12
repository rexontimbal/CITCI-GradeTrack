import re
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from academics.models import ClassOffering, ClassRosterEntry
from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from core.crud import EntityDeleteView, EntityFormView, EntityListView, ToggleActiveView, trigger_response
from core.htmx import is_htmx

from .forms import (
    AssessmentItemForm,
    GradingComponentForm,
    GradingTemplateForm,
    MarkIncompleteForm,
    SchemeComponentFormSet,
)
from .models import (
    AssessmentItem,
    AssessmentTerm,
    ClassGradingScheme,
    GradingComponent,
    GradingTemplate,
    Score,
    SchemeComponent,
    SchemeComponentChangeLog,
)
from .services import (
    PASSING_THRESHOLD,
    compute_class,
    compute_student,
    component_snapshot,
    delete_scheme_component,
    get_encoded_item_ids,
    get_scheme_components,
    log_component_change,
    save_score,
    scheme_total_weight,
)

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR
STUDENT = User.Role.STUDENT

_WHOLE_NUMBER_RE = re.compile(r"^\d+$")


def _parse_whole_number(raw_value):
    """Blank -> (None, None). A non-negative integer string -> (int, None).
    Anything else (decimals, negatives, letters) -> (None, "Whole numbers
    only.") — scores/max-scores are whole numbers, matching CITCI's class
    record; the above-max case is a separate message from save_score."""
    raw_value = raw_value.strip()
    if raw_value == "":
        return None, None
    if not _WHOLE_NUMBER_RE.match(raw_value):
        return None, "Whole numbers only."
    return int(raw_value), None


# ---------------------------------------------------------------------------
# Access helpers — same object-level pattern as academics.views: admin can
# view/manage anything, a program head can view (read-only) classes under
# their program, and only the assigned instructor can edit.
# ---------------------------------------------------------------------------


def _can_edit(user, class_offering):
    """Instructor-owned AND the grade sheet is still editable (no sheet yet,
    DRAFT, or RETURNED) — local import to avoid a grading<->approvals
    import cycle at app-loading time (approvals imports grading.services
    at module level; this direction can only be a function-local import)."""
    from approvals.services import is_class_editable

    return (
        user.is_instructor and class_offering.instructor_id == user.id and is_class_editable(class_offering)
    )


def _get_class_offering_for_grading(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "semester", "instructor").prefetch_related(
            "sections__program"
        ),
        pk=pk,
    )
    from academics.scoping import sections_in_scope

    user = request.user
    if user.is_program_head and not class_offering.sections.filter(pk__in=sections_in_scope(user)).exists():
        raise PermissionDenied("This class is not under your program.")
    if user.is_instructor and class_offering.instructor_id != user.id:
        raise PermissionDenied("This class is not assigned to you.")
    return class_offering


# ---------------------------------------------------------------------------
# Admin — Grading Templates (list/CRUD) + per-template Components
# ---------------------------------------------------------------------------


class GradingTemplateListView(RoleRequiredMixin, EntityListView):
    allowed_roles = (ADMIN,)
    model = GradingTemplate
    list_template = "grading/templates.html"
    table_template = "grading/_templates_table.html"
    table_id = "templates-table"
    page_title = "Grading Templates"
    search_fields = ["name__icontains"]
    refresh_event = "refreshTemplates"

    def apply_filters(self, request, qs):
        return qs.prefetch_related("components").annotate(classes_count=Count("class_schemes", distinct=True))


class GradingTemplateFormView(RoleRequiredMixin, EntityFormView):
    allowed_roles = (ADMIN,)
    model = GradingTemplate
    form_class = GradingTemplateForm
    refresh_event = "refreshTemplates"
    modal_title_create = "Add Grading Template"
    modal_title_edit = "Edit Grading Template"


class GradingTemplateDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = GradingTemplate
    refresh_event = "refreshTemplates"
    deactivate_url_name = "grading:template_toggle_active"
    protect_message = "This template is used by one or more classes."


class GradingTemplateToggleActiveView(RoleRequiredMixin, ToggleActiveView):
    allowed_roles = (ADMIN,)
    model = GradingTemplate
    refresh_event = "refreshTemplates"


@role_required(ADMIN)
def template_set_default(request, pk):
    template = get_object_or_404(GradingTemplate, pk=pk)
    template.is_default = True
    template.save()  # model.save() unsets every other template's is_default
    return trigger_response("refreshTemplates", toast=f"{template.name} is now the default template.")


@role_required(ADMIN)
def template_components(request, pk):
    template = get_object_or_404(GradingTemplate, pk=pk)
    context = {"template": template, "components": template.components.all()}
    if is_htmx(request):
        return render(request, "grading/_template_components_table.html", context)
    context["page_title"] = f"Components — {template.name}"
    return render(request, "grading/template_components.html", context)


class GradingComponentFormView(RoleRequiredMixin, View):
    allowed_roles = (ADMIN,)

    def get_object(self, pk):
        return get_object_or_404(GradingComponent, pk=pk) if pk else None

    def _template(self, obj, template_pk):
        return obj.template if obj else get_object_or_404(GradingTemplate, pk=template_pk)

    def get(self, request, template_pk=None, pk=None):
        obj = self.get_object(pk)
        template = self._template(obj, template_pk)
        form = GradingComponentForm(instance=obj)
        return render(
            request,
            "partials/_entity_form_modal.html",
            {"form": form, "object": obj, "modal_title": "Edit Component" if obj else "Add Component"},
        )

    def post(self, request, template_pk=None, pk=None):
        obj = self.get_object(pk)
        template = self._template(obj, template_pk)
        form = GradingComponentForm(request.POST, instance=obj)
        if form.is_valid():
            component = form.save(commit=False)
            component.template = template
            component.save()
            return trigger_response("refreshComponents", toast=f"{component.name} saved.")
        return render(
            request,
            "partials/_entity_form_modal.html",
            {"form": form, "object": obj, "modal_title": "Edit Component" if obj else "Add Component"},
        )


class GradingComponentDeleteView(RoleRequiredMixin, EntityDeleteView):
    allowed_roles = (ADMIN,)
    model = GradingComponent
    refresh_event = "refreshComponents"


# ---------------------------------------------------------------------------
# Class grading page (instructor edits, admin/program-head view read-only)
# ---------------------------------------------------------------------------


def _item_columns(components, term_filter):
    columns = []
    for component in components:
        items = list(component.items.all())
        if term_filter:
            items = [i for i in items if i.term == term_filter]
        columns.append({"component": component, "items": items})
    return columns


def _build_class_record_context(class_offering, term_filter=None):
    results = compute_class(class_offering)
    components = get_scheme_components(class_offering)

    # A component with zero items anywhere is "not yet set up" — always
    # hidden from the grid regardless of the term filter, and called out in
    # a muted note above it. Computed independent of term_filter, otherwise
    # a component that simply has no items *for the selected term* would be
    # wrongly reported as unset-up.
    not_yet_set_up = [col["component"] for col in _item_columns(components, None) if not col["items"]]

    # Visible columns: filtered by term, then any component left with zero
    # visible items (not set up at all, or just not in this term) is hidden
    # — the info bar above the grid already explains totals include every
    # term, so an empty column here would only be confusing clutter.
    columns = [col for col in _item_columns(components, term_filter) if col["items"]]
    flat_item_ids = [item.id for col in columns for item in col["items"]]
    encoded_item_ids = get_encoded_item_ids(flat_item_ids)

    scores_lookup = {}
    if flat_item_ids:
        for s in Score.objects.filter(roster_entry__class_offering=class_offering, item_id__in=flat_item_ids):
            scores_lookup[(s.roster_entry_id, s.item_id)] = s.score

    active_entry_ids = [
        r.roster_entry.id for r in results if r.roster_entry.status == ClassRosterEntry.Status.ACTIVE
    ]

    rows = []
    for result in results:
        entry = result.roster_entry
        is_active = entry.status == ClassRosterEntry.Status.ACTIVE
        entry_index = active_entry_ids.index(entry.id) if is_active else None
        breakdown_by_component_id = {b.component.id: b for b in result.components}

        # One block per visible component: its column definition, this
        # student's already-computed breakdown (for Total/Grade), and the
        # editable score cells — bundled together so the row template never
        # has to index two parallel lists by the same loop counter.
        component_blocks = []
        for col in columns:
            breakdown = breakdown_by_component_id[col["component"].id]
            cells = []
            for item in col["items"]:
                value = scores_lookup.get((entry.id, item.id))
                cell = {
                    "item": item,
                    "value": value,
                    "cell_id": f"score-{entry.id}-{item.id}",
                    "needs_score": value is None and item.id in encoded_item_ids,
                    "up": "",
                    "down": "",
                    "left": "",
                    "right": "",
                }
                if is_active:
                    if entry_index > 0:
                        cell["up"] = f"score-{active_entry_ids[entry_index - 1]}-{item.id}"
                    if entry_index < len(active_entry_ids) - 1:
                        cell["down"] = f"score-{active_entry_ids[entry_index + 1]}-{item.id}"
                    item_pos = flat_item_ids.index(item.id)
                    if item_pos > 0:
                        cell["left"] = f"score-{entry.id}-{flat_item_ids[item_pos - 1]}"
                    if item_pos < len(flat_item_ids) - 1:
                        cell["right"] = f"score-{entry.id}-{flat_item_ids[item_pos + 1]}"
                cells.append(cell)
            component_blocks.append({"component": col["component"], "breakdown": breakdown, "cells": cells})

        running_grade = result.running_grade
        rows.append(
            {
                "result": result,
                "component_blocks": component_blocks,
                "is_active": is_active,
                "row_number": (entry_index + 1) if is_active else None,
                "running_grade_over_threshold": running_grade is not None and running_grade > PASSING_THRESHOLD,
            }
        )

    missing_count = sum(len(r["result"].missing_items) for r in rows if r["is_active"])
    selected_term_label = dict(AssessmentTerm.choices).get(term_filter, "") if term_filter else ""

    from forecasting.services import get_display_forecasts_for_class, risk_level

    forecast_checkpoint, forecasts_by_entry = get_display_forecasts_for_class(class_offering)
    for row in rows:
        forecast = forecasts_by_entry.get(row["result"].roster_entry.id)
        if forecast is None:
            row["forecast_level"] = None
        elif isinstance(forecast, str):
            row["forecast_level"] = forecast  # "not_enough_data" / "unavailable"
        else:
            row["forecast_level"] = risk_level(forecast.probability, forecast.model_version.threshold)
            row["forecast_probability_pct"] = round(float(forecast.probability) * 100, 1)
            row["forecast_reasons"] = (forecast.contributions_json or {}).get("reasons", [])[:3]

    return {
        "columns": columns,
        "rows": rows,
        "missing_count": missing_count,
        "selected_term_label": selected_term_label,
        "not_yet_set_up": not_yet_set_up,
        "forecast_checkpoint": forecast_checkpoint,
    }


def _build_summary_context(class_offering):
    results = compute_class(class_offering)
    counts = {"PASSED": 0, "FAILED": 0, "INC": 0, "DROPPED": 0}
    final_grades = []
    for result in results:
        remark = result.remarks
        if remark in counts:
            counts[remark] += 1
        if remark in ("PASSED", "FAILED") and result.final_grade is not None:
            final_grades.append(result.final_grade)

    average = sum(final_grades) / len(final_grades) if final_grades else None
    distribution = {str(i): 0 for i in range(1, 6)}
    for grade in final_grades:
        bucket = min(5, max(1, int(grade)))
        distribution[str(bucket)] += 1

    from forecasting.services import get_display_forecasts_for_class, risk_level

    _checkpoint, forecasts_by_entry = get_display_forecasts_for_class(class_offering)
    risk_counts = {"AT_RISK": 0, "WATCH": 0, "ON_TRACK": 0}
    for forecast in forecasts_by_entry.values():
        if isinstance(forecast, str):
            continue
        level = risk_level(forecast.probability, forecast.model_version.threshold)
        risk_counts[level] += 1

    return {
        "results": results,
        "counts": counts,
        "average": average,
        "distribution": distribution,
        "risk_counts": risk_counts,
    }


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_grading(request, pk):
    from approvals.services import get_grade_sheet, missing_score_students

    class_offering = _get_class_offering_for_grading(request, pk)
    can_edit = _can_edit(request.user, class_offering)
    grade_sheet = get_grade_sheet(class_offering)
    is_owner = request.user.is_instructor and class_offering.instructor_id == request.user.id

    scheme_error = None
    try:
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
    except ValidationError as exc:
        scheme = None
        scheme_error = str(exc)

    term_filter = request.GET.get("term") or None
    deadline = class_offering.semester.submission_deadline
    is_overdue = bool(deadline and timezone.now() > deadline and grade_sheet is None)

    context = {
        "page_title": f"Grading — {class_offering}",
        "class_offering": class_offering,
        "can_edit": can_edit,
        "is_admin": request.user.is_admin_role,
        "is_owner": is_owner,
        "grade_sheet": grade_sheet,
        "missing_count_for_submit": len(missing_score_students(class_offering)) if is_owner else 0,
        "scheme": scheme,
        "scheme_error": scheme_error,
        "tab": request.GET.get("tab", "setup"),
        "term_filter": term_filter,
        "assessment_terms": AssessmentTerm.choices,
        "deadline": deadline,
        "is_overdue": is_overdue,
    }

    if scheme:
        context["record"] = _build_class_record_context(class_offering, term_filter)
        context["summary"] = _build_summary_context(class_offering)
        context["components"] = _build_components_panel_context(scheme, can_edit)
        context["scheme_total"] = scheme_total_weight(scheme)

    return render(request, "grading/class_grading.html", context)


def _build_components_panel_context(scheme, can_edit, formset=None):
    if formset is None and can_edit:
        formset = SchemeComponentFormSet(
            instance=scheme, queryset=scheme.components.order_by("-is_locked", "order", "id"), prefix="components"
        )
    locked_total = sum(c.weight for c in scheme.components.all() if c.is_locked)
    return {
        "scheme": scheme,
        "formset": formset,
        "can_edit": can_edit,
        "locked_total": locked_total,
        "instructor_share": 100 - locked_total,
        "change_logs": scheme.component_change_logs.select_related("changed_by")[:50],
    }


@role_required(INSTRUCTOR)
def class_components_save(request, pk):
    """GET opens the "Grading Components" modal (gear icon on the Setup
    tab's Assessment Items card); POST saves it. Both share this one view
    since the save target and the modal-open target are the same URL —
    a validation error on save re-renders just #components-panel inside
    the still-open modal, the same convention every other modal form in
    this codebase uses."""
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _can_edit(request.user, class_offering):
        raise PermissionDenied
    scheme = ClassGradingScheme.get_or_create_default(class_offering)

    if request.method != "POST":
        context = _build_components_panel_context(scheme, True)
        context["class_offering"] = class_offering
        return render(request, "grading/_components_modal.html", context)

    formset = SchemeComponentFormSet(
        request.POST, instance=scheme, queryset=scheme.components.order_by("-is_locked", "order", "id"), prefix="components"
    )
    if formset.is_valid():
        for form in formset.forms:
            if not form.cleaned_data:
                continue
            instance = form.instance
            if form.cleaned_data.get("DELETE"):
                if instance.pk:
                    before = component_snapshot(instance)
                    name = instance.name
                    delete_scheme_component(instance)
                    log_component_change(scheme, SchemeComponentChangeLog.Action.DELETED, name, request.user, before=before, after=None)
                continue
            if instance.pk:
                before = component_snapshot(SchemeComponent.objects.get(pk=instance.pk))
                saved = form.save()
                after = component_snapshot(saved)
                if before != after:
                    log_component_change(scheme, SchemeComponentChangeLog.Action.EDITED, saved.name, request.user, before=before, after=after)
            else:
                saved = form.save(commit=False)
                saved.scheme = scheme
                saved.save()
                log_component_change(scheme, SchemeComponentChangeLog.Action.ADDED, saved.name, request.user, before=None, after=component_snapshot(saved))

        from django.contrib import messages as django_messages

        django_messages.success(request, "Grading components updated.")
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response

    context = _build_components_panel_context(scheme, True, formset=formset)
    context["class_offering"] = class_offering
    return render(request, "grading/_components_panel.html", context)


@role_required(ADMIN)
def class_change_template(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    scheme = ClassGradingScheme.objects.filter(class_offering=class_offering).first()
    blocked = bool(scheme and scheme.has_scores)
    templates = GradingTemplate.objects.filter(is_active=True)

    if request.method == "GET" or blocked:
        return render(
            request,
            "grading/_change_template_modal.html",
            {
                "class_offering": class_offering,
                "templates": templates,
                "blocked": blocked,
                "current_template_id": scheme.source_template_id if scheme else None,
            },
        )

    template = get_object_or_404(GradingTemplate, pk=request.POST.get("template"))
    try:
        ClassGradingScheme.apply_template(class_offering, template)
    except ValidationError as exc:
        return render(
            request,
            "grading/_change_template_modal.html",
            {
                "class_offering": class_offering,
                "templates": templates,
                "blocked": False,
                "current_template_id": scheme.source_template_id if scheme else None,
                "error": str(exc),
            },
        )
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


# ---------------------------------------------------------------------------
# Setup tab — assessment items (instructor only)
# ---------------------------------------------------------------------------


class AssessmentItemFormView(View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def _resolve(self, request, class_pk, pk):
        obj = get_object_or_404(AssessmentItem, pk=pk) if pk else None
        class_offering = obj.class_offering if obj else get_object_or_404(ClassOffering, pk=class_pk)
        if not _can_edit(request.user, class_offering):
            raise PermissionDenied
        return obj, class_offering

    def get(self, request, class_pk=None, pk=None):
        obj, class_offering = self._resolve(request, class_pk, pk)
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
        initial = {}
        component_id = request.GET.get("component")
        if not obj and component_id and scheme.components.filter(pk=component_id).exists():
            initial["component"] = component_id
        form = AssessmentItemForm(instance=obj, scheme=scheme, initial=initial)
        return render(
            request,
            "partials/_entity_form_modal.html",
            {"form": form, "object": obj, "modal_title": "Edit Assessment Item" if obj else "Add Assessment Item"},
        )

    def post(self, request, class_pk=None, pk=None):
        obj, class_offering = self._resolve(request, class_pk, pk)
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
        form = AssessmentItemForm(request.POST, instance=obj, scheme=scheme)
        if form.is_valid():
            item = form.save(commit=False)
            item.class_offering = class_offering
            item.save()
            response = HttpResponse(status=204)
            response["HX-Refresh"] = "true"
            return response
        return render(
            request,
            "partials/_entity_form_modal.html",
            {"form": form, "object": obj, "modal_title": "Edit Assessment Item" if obj else "Add Assessment Item"},
        )


@role_required(INSTRUCTOR)
def item_delete(request, pk):
    item = get_object_or_404(AssessmentItem, pk=pk)
    if not _can_edit(request.user, item.class_offering):
        raise PermissionDenied

    if request.method != "POST":
        return render(request, "grading/_item_delete_modal.html", {"item": item, "has_scores": item.has_scores})

    if item.has_scores and request.POST.get("confirm") != "yes":
        return render(request, "grading/_item_delete_modal.html", {"item": item, "has_scores": True})

    item.delete()
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


# ---------------------------------------------------------------------------
# Class Record tab — inline score encoding (instructor only)
# ---------------------------------------------------------------------------


@role_required(INSTRUCTOR)
def save_cell(request, roster_entry_pk, item_pk):
    roster_entry = get_object_or_404(ClassRosterEntry, pk=roster_entry_pk)
    class_offering = roster_entry.class_offering
    if not _can_edit(request.user, class_offering):
        raise PermissionDenied
    item = get_object_or_404(AssessmentItem, pk=item_pk, class_offering=class_offering)

    new_value, error = _parse_whole_number(request.POST.get("value", ""))

    if error is None:
        _, error = save_score(roster_entry, item, new_value, request.user)
        if error is None:
            from forecasting.services import recompute_and_notify

            recompute_and_notify([roster_entry])

    term_filter = request.GET.get("term") or None
    record = _build_class_record_context(class_offering, term_filter)
    row = next(r for r in record["rows"] if r["result"].roster_entry.id == roster_entry.id)
    return render(
        request,
        "grading/_grid_row.html",
        {
            "row": row,
            "columns": record["columns"],
            "can_edit": True,
            "saved_item_id": item.id if error is None else None,
            "term_filter": term_filter,
            "error_item_id": item.id if error else None,
            "error_message": error,
        },
    )


@role_required(INSTRUCTOR)
def fill_column(request, pk):
    item = get_object_or_404(AssessmentItem, pk=pk)
    class_offering = item.class_offering
    if not _can_edit(request.user, class_offering):
        raise PermissionDenied

    touched = []
    for roster_entry in class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE):
        existing = Score.objects.filter(roster_entry=roster_entry, item=item).first()
        if existing is None or existing.score is None:
            save_score(roster_entry, item, item.max_score, request.user)
            touched.append(roster_entry)

    if touched:
        from forecasting.services import recompute_and_notify

        recompute_and_notify(touched)

    term_filter = request.GET.get("term") or None
    record = _build_class_record_context(class_offering, term_filter)
    return render(
        request,
        "grading/_grid_body.html",
        {"rows": record["rows"], "columns": record["columns"], "can_edit": True, "term_filter": term_filter},
    )


@role_required(INSTRUCTOR)
def mark_incomplete(request, pk):
    roster_entry = get_object_or_404(ClassRosterEntry, pk=pk)
    class_offering = roster_entry.class_offering
    if not _can_edit(request.user, class_offering):
        raise PermissionDenied

    if request.method == "GET":
        form = MarkIncompleteForm(
            initial={"is_incomplete": roster_entry.is_incomplete, "incomplete_reason": roster_entry.incomplete_reason}
        )
        return render(request, "grading/_mark_incomplete_modal.html", {"roster_entry": roster_entry, "form": form})

    form = MarkIncompleteForm(request.POST)
    if not form.is_valid():
        response = render(
            request, "grading/_mark_incomplete_modal.html", {"roster_entry": roster_entry, "form": form}
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    roster_entry.is_incomplete = form.cleaned_data["is_incomplete"]
    roster_entry.incomplete_reason = form.cleaned_data["incomplete_reason"] if roster_entry.is_incomplete else ""
    roster_entry.save(update_fields=["is_incomplete", "incomplete_reason"])

    term_filter = request.GET.get("term") or None
    record = _build_class_record_context(class_offering, term_filter)
    row = next(r for r in record["rows"] if r["result"].roster_entry.id == roster_entry.id)
    response = render(
        request,
        "grading/_grid_row.html",
        {"row": row, "columns": record["columns"], "can_edit": True, "term_filter": term_filter},
    )
    response["HX-Trigger"] = "modal-success"
    return response


# ---------------------------------------------------------------------------
# Student portal (Phase 5) — a student only ever sees their OWN roster
# entries; every lookup below filters by `student=request.user` (or goes
# through a roster_entry already filtered that way), and a mismatched pk
# 404s via get_object_or_404 rather than raising 403 — a student has no
# business even learning that a given roster entry id exists.
# ---------------------------------------------------------------------------


@role_required(STUDENT)
def my_grades(request):
    from academics.models import Semester
    from approvals.services import compute_gwa

    from .services import compute_students_batch, released_entries_for, show_unofficial_scores_to_students, subject_status_chip

    student = request.user
    show_unofficial = show_unofficial_scores_to_students()

    semesters = (
        Semester.objects.filter(class_offerings__roster_entries__student=student)
        .distinct()
        .order_by("-academic_year__start_year", "term")
    )
    semester_id = request.GET.get("semester")
    semester = semesters.filter(pk=semester_id).first() if semester_id else None
    if semester is None:
        semester = semesters.filter(is_active=True).first() or semesters.first()

    rows = []
    gwa = None
    total_units = Decimal("0")
    if semester:
        # Batched (Phase 8 part B query-count pass) — released_entry and the
        # unofficial running grade were each one query PER subject.
        roster_entries = list(
            ClassRosterEntry.objects.filter(student=student, class_offering__semester=semester)
            .select_related("class_offering__subject", "class_offering__instructor")
            .order_by("class_offering__subject__code")
        )
        released_by_entry = released_entries_for(roster_entries)
        needs_unofficial = [
            e
            for e in roster_entries
            if show_unofficial and released_by_entry.get(e.id) is None and e.status == ClassRosterEntry.Status.ACTIVE
        ]
        unofficial_by_entry = compute_students_batch(needs_unofficial) if needs_unofficial else {}

        for entry in roster_entries:
            released_entry = released_by_entry.get(entry.id)
            status_label, status_key = subject_status_chip(entry, released_entry)
            row = {
                "roster_entry": entry,
                "class_offering": entry.class_offering,
                "released_entry": released_entry,
                "status_label": status_label,
                "status_key": status_key,
                "unofficial_grade": None,
            }
            if entry.id in unofficial_by_entry:
                row["unofficial_grade"] = unofficial_by_entry[entry.id].running_grade
            rows.append(row)
            total_units += entry.class_offering.subject.units

        gwa = compute_gwa(student, semester)

    context = {
        "page_title": "My Grades",
        "semesters": semesters,
        "semester": semester,
        "rows": rows,
        "gwa": gwa,
        "total_units": total_units,
        "show_unofficial": show_unofficial,
    }
    return render(request, "grading/my_grades.html", context)


@role_required(STUDENT)
def subject_detail(request, pk):
    from .services import (
        class_average_per_component,
        released_entry_for,
        running_grade_progression,
        show_unofficial_scores_to_students,
        subject_status_chip,
    )

    roster_entry = get_object_or_404(
        ClassRosterEntry.objects.select_related(
            "class_offering__subject", "class_offering__instructor", "class_offering__semester"
        ),
        pk=pk,
        student=request.user,
    )
    class_offering = roster_entry.class_offering
    released_entry = released_entry_for(roster_entry)
    show_unofficial = show_unofficial_scores_to_students()
    is_released = released_entry is not None
    can_view_detail = is_released or show_unofficial

    status_label, status_key = subject_status_chip(roster_entry, released_entry)

    context = {
        "page_title": f"{class_offering.subject.code} — My Grades",
        "roster_entry": roster_entry,
        "class_offering": class_offering,
        "released_entry": released_entry,
        "is_released": is_released,
        "status_label": status_label,
        "status_key": status_key,
        "can_view_detail": can_view_detail,
        "show_unofficial": show_unofficial,
    }

    if not can_view_detail:
        return render(request, "grading/subject_detail.html", context)

    # Fetched once and threaded through compute_student/
    # running_grade_progression below (Phase 8 part B query-count pass —
    # each used to independently re-fetch the same scheme/components/items/
    # scores for this one roster entry).
    components = get_scheme_components(class_offering)
    item_ids = [item.id for c in components for item in c.items.all()]
    scores_by_item = {
        s.item_id: s.score for s in Score.objects.filter(roster_entry=roster_entry, item_id__in=item_ids)
    }

    if is_released:
        components_display = [
            {
                "name": c["name"],
                "weight": c["weight"],
                "earned": Decimal(c["earned"]),
                "possible": Decimal(c["possible"]),
                "grade": Decimal(c["grade"]) if c["grade"] is not None else None,
            }
            for c in released_entry.components_json
        ]
        final_grade = released_entry.final_grade
        remarks_display = released_entry.get_remarks_display()
    else:
        result = compute_student(roster_entry, components=components)
        components_display = [
            {
                "name": b.component.name,
                "weight": b.component.weight,
                "earned": b.final_earned,
                "possible": b.final_possible,
                "grade": b.final_grade,
            }
            for b in result.components
        ]
        final_grade = result.running_grade
        remarks_display = None

    # Item list grouped by term — always the live AssessmentItem/Score data
    # (informational only; for a released class these are frozen anyway
    # since editing locks at submission, so it never drifts from what the
    # official snapshot was taken from).
    items_by_term = {term: [] for term, _ in AssessmentTerm.choices}
    for component in components:
        for item in component.items.all():
            items_by_term[item.term].append(
                {
                    "component_name": component.name,
                    "title": item.title,
                    "date": item.date,
                    "score": scores_by_item.get(item.id),
                    "max_score": item.max_score,
                }
            )

    class_average = class_average_per_component(class_offering)
    component_averages = []
    if class_average:
        for component in components:
            avg = class_average.get(component.id)
            if avg is not None:
                component_averages.append({"name": component.name, "average": avg})

    progression = running_grade_progression(roster_entry, components=components, scores_by_item=scores_by_item)

    from forecasting.services import student_forecast_card

    context.update(
        {
            "components_display": components_display,
            "final_grade": final_grade,
            "remarks_display": remarks_display,
            "items_by_term": [(term, label, items_by_term[term]) for term, label in AssessmentTerm.choices],
            "component_averages": component_averages,
            "chart_component_labels": [c["name"] for c in components_display],
            "chart_component_percents": [
                float(c["earned"] / c["possible"] * 100) if c["possible"] else 0 for c in components_display
            ],
            "chart_progression_labels": [label for _, label, _ in progression],
            "chart_progression_values": [float(grade) if grade is not None else None for _, _, grade in progression],
            "forecast": student_forecast_card(roster_entry),
        }
    )
    return render(request, "grading/subject_detail.html", context)


@role_required(STUDENT)
def my_progress(request):
    from academics.models import Semester
    from approvals.models import GradeSheetEntry, GradeSheetStatus
    from approvals.services import compute_gwa

    from .services import compute_students_batch, released_entries_for, show_unofficial_scores_to_students, subject_status_chip

    student = request.user
    show_unofficial = show_unofficial_scores_to_students()

    semesters = (
        Semester.objects.filter(class_offerings__roster_entries__student=student)
        .distinct()
        .order_by("academic_year__start_year", "term")
    )

    history = []
    for semester in semesters:
        result = compute_gwa(student, semester)
        counts = {"PASSED": 0, "FAILED": 0, "INC": 0}
        entries = GradeSheetEntry.objects.filter(
            roster_entry__student=student,
            roster_entry__class_offering__semester=semester,
            sheet__status__in=[GradeSheetStatus.RELEASED, GradeSheetStatus.LOCKED],
        )
        for entry in entries:
            if entry.remarks in counts:
                counts[entry.remarks] += 1
        history.append({"semester": semester, "gwa": result, "counts": counts})

    active_semester = semesters.filter(is_active=True).first()
    current_subjects = []
    if active_semester:
        # Batched (Phase 8 part B query-count pass) — see my_grades/
        # dashboard for the same released_entry/compute_student N+1.
        roster_entries = list(
            ClassRosterEntry.objects.filter(student=student, class_offering__semester=active_semester).select_related(
                "class_offering__subject"
            )
        )
        released_by_entry = released_entries_for(roster_entries)
        needs_unofficial = [
            e
            for e in roster_entries
            if show_unofficial and released_by_entry.get(e.id) is None and e.status == ClassRosterEntry.Status.ACTIVE
        ]
        unofficial_by_entry = compute_students_batch(needs_unofficial) if needs_unofficial else {}

        for entry in roster_entries:
            released_entry = released_by_entry.get(entry.id)
            status_label, status_key = subject_status_chip(entry, released_entry)
            if released_entry is not None:
                grade = released_entry.final_grade
            elif entry.id in unofficial_by_entry:
                grade = unofficial_by_entry[entry.id].running_grade
            else:
                grade = None
            current_subjects.append(
                {
                    "code": entry.class_offering.subject.code,
                    "grade": grade,
                    "status_key": status_key,
                    "status_label": status_label,
                }
            )

    context = {
        "page_title": "My Progress",
        "history": history,
        "current_subjects": current_subjects,
        "gwa_chart_labels": [str(h["semester"]) for h in history if h["gwa"]["gwa"] is not None],
        "gwa_chart_values": [float(h["gwa"]["gwa"]) for h in history if h["gwa"]["gwa"] is not None],
        "subject_chart_labels": [s["code"] for s in current_subjects if s["grade"] is not None],
        "subject_chart_values": [float(s["grade"]) for s in current_subjects if s["grade"] is not None],
    }
    return render(request, "grading/my_progress.html", context)
