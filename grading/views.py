import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from academics.models import ClassOffering, ClassRosterEntry
from accounts.decorators import role_required
from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from accounts.utils import coming_soon
from core.crud import EntityDeleteView, EntityFormView, EntityListView, ToggleActiveView, trigger_response
from core.htmx import is_htmx

from .forms import AssessmentItemForm, GradingComponentForm, GradingTemplateForm, MarkIncompleteForm
from .models import AssessmentItem, AssessmentTerm, ClassGradingScheme, GradingComponent, GradingTemplate, Score
from .services import PASSING_THRESHOLD, compute_class, compute_student, get_encoded_item_ids, get_scheme_components, save_score

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
    return user.is_instructor and class_offering.instructor_id == user.id


def _get_class_offering_for_grading(request, pk):
    class_offering = get_object_or_404(
        ClassOffering.objects.select_related("subject", "semester", "instructor").prefetch_related(
            "sections__program"
        ),
        pk=pk,
    )
    user = request.user
    if user.is_program_head and not class_offering.sections.filter(program__program_head_id=user.id).exists():
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
    return trigger_response("refreshTemplates")


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
            return trigger_response("refreshComponents")
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
    return {
        "columns": columns,
        "rows": rows,
        "missing_count": missing_count,
        "selected_term_label": selected_term_label,
        "not_yet_set_up": not_yet_set_up,
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

    return {"results": results, "counts": counts, "average": average, "distribution": distribution}


@role_required(ADMIN, PROGRAM_HEAD, INSTRUCTOR)
def class_grading(request, pk):
    class_offering = _get_class_offering_for_grading(request, pk)
    can_edit = _can_edit(request.user, class_offering)

    scheme_error = None
    try:
        scheme = ClassGradingScheme.get_or_create_default(class_offering)
    except ValidationError as exc:
        scheme = None
        scheme_error = str(exc)

    term_filter = request.GET.get("term") or None

    context = {
        "page_title": f"Grading — {class_offering}",
        "class_offering": class_offering,
        "can_edit": can_edit,
        "is_admin": request.user.is_admin_role,
        "scheme": scheme,
        "scheme_error": scheme_error,
        "tab": request.GET.get("tab", "setup"),
        "term_filter": term_filter,
        "assessment_terms": AssessmentTerm.choices,
    }

    if scheme:
        context["record"] = _build_class_record_context(class_offering, term_filter)
        context["summary"] = _build_summary_context(class_offering)

    return render(request, "grading/class_grading.html", context)


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
        form = AssessmentItemForm(instance=obj, scheme=scheme)
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

    for roster_entry in class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE):
        existing = Score.objects.filter(roster_entry=roster_entry, item=item).first()
        if existing is None or existing.score is None:
            save_score(roster_entry, item, item.max_score, request.user)

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
# Student-/placeholder pages kept from before this phase
# ---------------------------------------------------------------------------


@role_required(INSTRUCTOR)
def submitted(request):
    return coming_soon(request, "Submitted Grades")


@role_required(STUDENT)
def my_grades(request):
    return coming_soon(request, "My Grades")


@role_required(STUDENT)
def my_progress(request):
    return coming_soon(request, "My Progress")
