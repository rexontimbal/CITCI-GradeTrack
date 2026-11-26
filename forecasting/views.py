from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from academics.models import AcademicYear, ClassOffering, ClassRosterEntry, Program, Semester, Term
from accounts.decorators import role_required
from accounts.models import User
from grading.models import AssessmentTerm, ComponentCategory

from . import flexible_import, gradebook_import
from .forms import InterventionForm
from .historical_import import build_import_preview, commit_import, export_released_data_to_historical, looks_like_known_template
from .ml.features import FEATURE_NAMES
from .ml.train import train_model
from .models import Checkpoint, HistoricalImportBatch, Intervention, MlModelVersion, Prediction, TrainingSource
from .services import (
    current_checkpoint_for_class,
    get_display_forecasts_for_class,
    get_display_forecasts_for_classes,
    recompute_and_notify,
    risk_level,
)

ADMIN = User.Role.ADMIN
PROGRAM_HEAD = User.Role.PROGRAM_HEAD
INSTRUCTOR = User.Role.INSTRUCTOR


# ---------------------------------------------------------------------------
# Model Performance
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def model(request):
    if request.method == "POST":
        checkpoint = request.POST.get("checkpoint")
        source = request.POST.get("source")
        try:
            threshold = Decimal(request.POST.get("threshold", "0.50"))
        except InvalidOperation:
            threshold = Decimal("0.50")
        try:
            version = train_model(checkpoint, source, threshold=threshold)
            messages.success(request, f"Trained {version}. Inactive until you Activate it below.")
        except ValidationError as exc:
            # Always a "not enough data yet" refusal, never a system
            # failure -- amber, not red, so it doesn't read as something
            # broke.
            messages.warning(request, " ".join(exc.messages))
        return redirect("forecasting:model")

    versions_by_checkpoint = {}
    active_by_checkpoint = {}
    for checkpoint, _label in Checkpoint.choices:
        versions = list(MlModelVersion.objects.filter(checkpoint=checkpoint))
        versions_by_checkpoint[checkpoint] = versions
        active_by_checkpoint[checkpoint] = next((v for v in versions if v.is_active), None)

    context = {
        "page_title": "Forecast Model",
        "checkpoints": Checkpoint.choices,
        "versions_by_checkpoint": versions_by_checkpoint,
        "active_by_checkpoint": active_by_checkpoint,
        "sources": TrainingSource.choices,
    }
    return render(request, "forecasting/model.html", context)


@role_required(ADMIN)
def model_activate(request, pk):
    version = get_object_or_404(MlModelVersion, pk=pk)
    version.is_active = True
    version.save()
    messages.success(request, f"Activated {version}.")
    return redirect("forecasting:model")


@role_required(ADMIN)
def model_report_pdf(request, pk):
    from reports.pdf import render_pdf
    from reports.views import _logo_context

    version = get_object_or_404(MlModelVersion, pk=pk)
    inst, logo_url = _logo_context()
    context = {
        "settings": inst,
        "logo_url": logo_url,
        "generated_at": timezone.now(),
        "watermark_text": None,
        "version": version,
    }
    filename = f"ForecastModel_{version.checkpoint}_v{version.pk}.pdf"
    return render_pdf("forecasting/pdf/model_report.html", context, filename)


# ---------------------------------------------------------------------------
# Historical Data
# ---------------------------------------------------------------------------


@role_required(ADMIN)
def historical(request):
    batches = HistoricalImportBatch.objects.select_related("uploaded_by")
    context = {"page_title": "Historical Data", "batches": batches}
    return render(request, "forecasting/historical.html", context)


_FEATURE_DISPLAY_LABELS = {
    "quiz_pct": "Quiz %",
    "recitation_pct": "Recitation %",
    "project_pct": "Project %",
    "attendance_pct": "Attendance %",
    "exam_pct": "Exam %",
    "running_grade": "Running Grade",
    "missing_rate_pct": "Missing %",
}


@role_required(ADMIN)
def historical_detail(request, pk):
    """Read-only drill-down into one import batch's rows -- masked_id is
    shown only as a short reference (its first 8 hex characters), never
    the full hash or anything that could be reversed to a real identity.
    Paginated since a real CITCI dataset can run to hundreds of rows."""
    from django.core.paginator import Paginator

    batch = get_object_or_404(HistoricalImportBatch, pk=pk)
    records = batch.records.all().order_by("checkpoint", "subject_code", "masked_id")

    checkpoint_filter = request.GET.get("checkpoint", "")
    if checkpoint_filter:
        records = records.filter(checkpoint=checkpoint_filter)

    paginator = Paginator(records, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "forecasting/historical_detail.html",
        {
            "page_title": f"Historical Data: Batch #{batch.pk}",
            "batch": batch,
            "page": page,
            "feature_columns": [(name, _FEATURE_DISPLAY_LABELS[name]) for name in FEATURE_NAMES],
            "checkpoint_choices": Checkpoint.choices,
            "checkpoint_filter": checkpoint_filter,
        },
    )


def _mapping_context(files_payload):
    return {
        "files": files_payload,
        "role_choices": flexible_import.ColumnRole.CHOICES,
        "kind_choices": flexible_import.SCORE_KIND_CHOICES,
        "category_choices": ComponentCategory.choices,
        "term_choices": AssessmentTerm.choices,
    }


@role_required(ADMIN)
def historical_import_instructions(request):
    """Shown before the file picker, every time -- explains the one rule
    that makes clean parsing possible (headers in literal row 1) before
    the admin ever sees an upload form. "Continue" re-GETs the existing
    upload view into the same #modal-content target."""
    return render(request, "forecasting/_historical_import_instructions.html", {})


@role_required(ADMIN)
def historical_import_upload(request):
    if request.method != "POST":
        return render(request, "forecasting/_historical_import_modal.html", {})

    uploaded_files = request.FILES.getlist("files")
    if not uploaded_files:
        return render(request, "forecasting/_historical_import_modal.html", {"error": "Choose at least one file."})

    semester_fallback = request.POST.get("semester_label", "").strip()
    subject_fallback = request.POST.get("subject_code", "").strip()

    files = [(f.name, f) for f in uploaded_files]

    # A file from a real third-party gradebook export (a `Meta` sheet
    # naming "fullyear") is fully self-describing -- no mapping-confirm
    # screen needed at all, straight to the preview. Checked first since
    # its fingerprint is the most specific/unambiguous of the three.
    if all(gradebook_import.looks_like_fullyear_gradebook(f) for name, f in files):
        try:
            preview = gradebook_import.build_gradebook_import_preview(files)
        except Exception as exc:  # pragma: no cover — surfaced to the admin, not silently swallowed
            return render(request, "forecasting/_historical_import_modal.html", {"error": str(exc)})

        if preview.row_count == 0:
            return render(
                request,
                "forecasting/_historical_import_modal.html",
                {"error": "No usable rows found in the uploaded file(s). See the skipped-row reasons if any."},
            )

        request.session["historical_import_preview"] = preview.to_session()
        return render(request, "forecasting/_historical_import_preview.html", {"preview": preview})

    # If every file matches the known rigid layout (CITCI's own template or
    # this system's Class Record export), behavior is identical to before
    # this feature existed -- the fast path, untouched. Mixing rigid and
    # flexible files in one batch is unsupported: any mismatch sends the
    # whole batch through the flexible mapper instead.
    if all(looks_like_known_template(name, f) for name, f in files):
        try:
            preview = build_import_preview(files)
        except Exception as exc:  # pragma: no cover — surfaced to the admin, not silently swallowed
            return render(request, "forecasting/_historical_import_modal.html", {"error": str(exc)})

        if preview.row_count == 0:
            return render(
                request,
                "forecasting/_historical_import_modal.html",
                {"error": "No usable rows found in the uploaded file(s). See the skipped-row reasons if any."},
            )

        request.session["historical_import_preview"] = preview.to_session()
        return render(request, "forecasting/_historical_import_preview.html", {"preview": preview})

    files_payload = []
    for name, uploaded_file in files:
        try:
            df = flexible_import.read_table(name, uploaded_file)
        except ValueError as exc:
            return render(request, "forecasting/_historical_import_modal.html", {"error": str(exc)})
        candidates = flexible_import.suggest_columns(df)
        stem = name.rsplit(".", 1)[0]  # matches the rigid path's own filename-stem fallback
        files_payload.append(
            flexible_import.build_file_payload(name, df, candidates, semester_fallback or stem, subject_fallback or stem)
        )

    request.session["flexible_import_mapping"] = {"files": files_payload}
    return render(request, "forecasting/_historical_import_mapping.html", _mapping_context(files_payload))


@role_required(ADMIN)
def historical_import_mapping_confirm(request):
    stashed = request.session.get("flexible_import_mapping")
    if not stashed:
        response = render(
            request, "forecasting/_historical_import_modal.html", {"error": "Your upload expired. Upload again."}
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    files_payload = stashed["files"]
    mapping = flexible_import.parse_mapping_from_post(files_payload, request.POST)
    errors = flexible_import.validate_mapping(files_payload, mapping)

    if errors:
        response = render(
            request,
            "forecasting/_historical_import_mapping.html",
            {**_mapping_context(files_payload), "errors": errors},
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    preview_dict = flexible_import.build_flexible_preview(files_payload, mapping)
    del request.session["flexible_import_mapping"]

    if preview_dict["row_count"] == 0:
        response = render(
            request,
            "forecasting/_historical_import_modal.html",
            {"error": "No usable rows found with this mapping. See the skipped-row reasons if any."},
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    request.session["historical_import_preview"] = preview_dict
    # _historical_import_preview.html only reads attributes off `preview`
    # (row_count/positive_count/skipped/file_names) -- a plain namespace
    # satisfies it exactly like the rigid path's dataclass instance does.
    from types import SimpleNamespace

    namespace_dict = {
        **preview_dict,
        "skipped": [SimpleNamespace(**s) for s in preview_dict["skipped"]],
        "per_file": [SimpleNamespace(**f) for f in preview_dict.get("per_file", [])],
    }
    preview = SimpleNamespace(**namespace_dict)
    return render(request, "forecasting/_historical_import_preview.html", {"preview": preview})


@role_required(ADMIN)
def historical_import_confirm(request):
    stashed = request.session.get("historical_import_preview")
    if not stashed:
        response = render(
            request, "forecasting/_historical_import_modal.html", {"error": "Your preview expired. Upload again."}
        )
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    commit_import(stashed, request.user)
    del request.session["historical_import_preview"]

    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@role_required(ADMIN)
def historical_delete(request, pk):
    batch = get_object_or_404(HistoricalImportBatch, pk=pk)
    batch.delete()
    messages.success(request, "Batch deleted.")
    return redirect("forecasting:historical")


@role_required(ADMIN)
def historical_export_live(request):
    batch = export_released_data_to_historical(request.user)
    messages.success(request, f"Added {batch.row_count} row(s) from released/locked grade sheets.")
    return redirect("forecasting:historical")


# ---------------------------------------------------------------------------
# At-Risk Students — instructor and program head
# ---------------------------------------------------------------------------


def _any_non_historical_active_model():
    return MlModelVersion.objects.filter(is_active=True).exclude(training_source=TrainingSource.HISTORICAL).exists()


def _build_at_risk_rows(class_offering, checkpoint, forecasts, roster_entries, level_filter=None):
    """[{entry, class_offering, checkpoint, level, probability, prediction,
    reasons, last_intervention}, ...] for AT_RISK/WATCH students only.

    Takes already-fetched data (from get_display_forecasts_for_classes) and
    issues no queries of its own — entry.interventions.all() below reads
    the prefetch cache that call already populated (Phase 8 part A/B
    query-count passes)."""
    if checkpoint is None:
        return []
    rows = []
    for entry_id, forecast in forecasts.items():
        if not isinstance(forecast, Prediction):
            continue
        level = risk_level(forecast.probability, forecast.model_version.threshold)
        if level not in ("AT_RISK", "WATCH"):
            continue
        if level_filter and level != level_filter:
            continue
        entry = roster_entries.get(entry_id)
        if entry is None:
            continue
        rows.append(
            {
                "entry": entry,
                "class_offering": class_offering,
                "checkpoint": checkpoint,
                "level": level,
                "probability": round(float(forecast.probability) * 100, 1),
                "prediction": forecast,
                "reasons": (forecast.contributions_json or {}).get("reasons", [])[:3],
                # .all() reuses the prefetch_related cache above (already
                # ordered newest-first); .first() would re-query per row.
                "last_intervention": next(iter(entry.interventions.all()), None),
            }
        )
    return rows


@role_required(PROGRAM_HEAD, INSTRUCTOR)
def _resolve_semester_from_request(request):
    """Academic Year + Semester filter, same ?ay=<academic_year_id>&
    sem_term=<term> convention as the Subjects/Classes pages (see
    academics.views._resolve_semester_from_request) -- defaults to the
    active semester so a past term's at-risk data stays reachable once a
    new school year starts, instead of silently disappearing."""
    ay_id = request.GET.get("ay")
    sem_term = request.GET.get("sem_term")
    if ay_id and sem_term:
        semester = Semester.objects.filter(academic_year_id=ay_id, term=sem_term).select_related("academic_year").first()
        if semester:
            return semester
    return Semester.objects.filter(is_active=True).select_related("academic_year").first()


def _semester_filter_context(selected_semester):
    return {
        "academic_years": AcademicYear.objects.order_by("-start_year"),
        "selected_ay_id": selected_semester.academic_year_id if selected_semester else None,
        "selected_sem_term": selected_semester.term if selected_semester else None,
        "semester_term_choices": Term.choices,
        "selected_semester": selected_semester,
    }


def at_risk(request):
    if request.user.is_instructor:
        return _at_risk_instructor(request)
    return _at_risk_program_head(request)


def _at_risk_instructor(request):
    selected_semester = _resolve_semester_from_request(request)
    classes = list(
        ClassOffering.objects.filter(instructor=request.user, semester=selected_semester)
        .select_related("subject")
        .prefetch_related("sections__program", "sections__major")
        if selected_semester
        else ClassOffering.objects.none()
    )

    class_filter = request.GET.get("class")
    level_filter = request.GET.get("level")
    student_query = request.GET.get("q", "").strip()

    bulk = get_display_forecasts_for_classes(classes)
    rows = []
    for class_offering in classes:
        if class_filter and str(class_offering.pk) != class_filter:
            continue
        checkpoint, forecasts, roster_entries = bulk.get(class_offering.pk, (None, {}, {}))
        rows.extend(_build_at_risk_rows(class_offering, checkpoint, forecasts, roster_entries, level_filter))
    if student_query:
        rows = [r for r in rows if student_query.lower() in r["entry"].student.full_name.lower()]
    rows.sort(key=lambda r: r["probability"], reverse=True)

    from django.core.paginator import Paginator

    paginator = Paginator(rows, 25)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "At-Risk Students",
        "classes": classes,
        "rows": page,
        "class_filter": class_filter,
        "level_filter": level_filter,
        "student_query": student_query,
        "show_synthetic_banner": _any_non_historical_active_model(),
        **_semester_filter_context(selected_semester),
    }
    return render(request, "forecasting/at_risk_instructor.html", context)


def _program_head_classes(user, semester):
    if semester is None:
        return ClassOffering.objects.none()
    # prefetch sections__program/major so every ClassOffering.__str__()/
    # Section.__str__() call in the template (one per row, one per
    # by-class summary row, one per filter dropdown option) reads from
    # memory instead of re-querying Section/Program per call (Phase 8
    # part B query-count pass — this alone was ~84 of the 103 queries
    # measured before the fix, same N+1 already fixed on Admin Grade
    # Sheets in Phase 8 part A but not carried over to this page).
    from academics.scoping import classes_in_scope

    return (
        classes_in_scope(user, semester=semester)
        .select_related("subject", "instructor")
        .prefetch_related("sections__program", "sections__major")
        .distinct()
    )


def _at_risk_program_head(request):
    selected_semester = _resolve_semester_from_request(request)
    classes = list(_program_head_classes(request.user, selected_semester))

    class_filter = request.GET.get("class")
    level_filter = request.GET.get("level")
    student_query = request.GET.get("q", "").strip()
    class_query = request.GET.get("class_q", "").strip()

    # One grouped query for every class's intervention count, instead of a
    # per-class .count() query in the loop below (Phase 8 part A query-
    # count pass — this view previously issued 150+ queries for a program
    # head with ~40 classes).
    intervention_counts = dict(
        Intervention.objects.filter(roster_entry__class_offering__in=classes)
        .values("roster_entry__class_offering_id")
        .annotate(count=Count("id"))
        .values_list("roster_entry__class_offering_id", "count")
    )

    bulk = get_display_forecasts_for_classes(classes)
    rows = []
    by_class = {}
    for class_offering in classes:
        checkpoint, forecasts, roster_entries = bulk.get(class_offering.pk, (None, {}, {}))
        class_rows = _build_at_risk_rows(class_offering, checkpoint, forecasts, roster_entries)
        by_class[class_offering.pk] = {
            "class_offering": class_offering,
            "at_risk": sum(1 for r in class_rows if r["level"] == "AT_RISK"),
            "watch": sum(1 for r in class_rows if r["level"] == "WATCH"),
            "interventions": intervention_counts.get(class_offering.pk, 0),
        }
        if class_filter and str(class_offering.pk) != class_filter:
            continue
        for row in class_rows:
            if level_filter and row["level"] != level_filter:
                continue
            if student_query and student_query.lower() not in row["entry"].student.full_name.lower():
                continue
            rows.append(row)
    rows.sort(key=lambda r: r["probability"], reverse=True)

    total_at_risk = sum(c["at_risk"] for c in by_class.values())
    total_watch = sum(c["watch"] for c in by_class.values())
    classes_affected = sum(1 for c in by_class.values() if c["at_risk"] or c["watch"])
    total_interventions = sum(intervention_counts.values())

    by_class_list = list(by_class.values())
    if class_query:
        q = class_query.lower()
        by_class_list = [
            c
            for c in by_class_list
            if q in c["class_offering"].subject.code.lower()
            or q in c["class_offering"].subject.title.lower()
            or (c["class_offering"].instructor and q in c["class_offering"].instructor.full_name.lower())
        ]

    from django.core.paginator import Paginator

    paginator = Paginator(rows, 25)
    page = paginator.get_page(request.GET.get("page"))

    class_paginator = Paginator(by_class_list, 10)
    class_page = class_paginator.get_page(request.GET.get("class_page"))

    context = {
        "page_title": "At-Risk Students",
        "classes": classes,
        "rows": page,
        "class_filter": class_filter,
        "level_filter": level_filter,
        "student_query": student_query,
        "class_query": class_query,
        "by_class": class_page,
        "summary": {
            "at_risk": total_at_risk,
            "watch": total_watch,
            "classes_affected": classes_affected,
            "interventions": total_interventions,
        },
        "show_synthetic_banner": _any_non_historical_active_model(),
        **_semester_filter_context(selected_semester),
    }
    return render(request, "forecasting/at_risk_program_head.html", context)


@role_required(PROGRAM_HEAD)
def at_risk_export(request):
    from openpyxl import Workbook

    from reports.excel import workbook_response

    selected_semester = _resolve_semester_from_request(request)
    classes = list(_program_head_classes(request.user, selected_semester))

    wb = Workbook()
    ws = wb.active
    ws.title = "At-Risk Students"
    ws.append(["Student", "ID Number", "Class", "Instructor", "Checkpoint", "Risk Level", "Probability %"])
    bulk = get_display_forecasts_for_classes(classes)
    for class_offering in classes:
        checkpoint, forecasts, roster_entries = bulk.get(class_offering.pk, (None, {}, {}))
        for row in _build_at_risk_rows(class_offering, checkpoint, forecasts, roster_entries):
            ws.append(
                [
                    row["entry"].student.full_name,
                    row["entry"].student.id_number or "",
                    str(class_offering),
                    class_offering.instructor.full_name if class_offering.instructor else "",
                    row["checkpoint"],
                    row["level"],
                    row["probability"],
                ]
            )
    return workbook_response(wb, "AtRiskStudents.xlsx")


# ---------------------------------------------------------------------------
# Recompute
# ---------------------------------------------------------------------------


def _owns_class_for_forecasting(user, class_offering):
    from academics.scoping import sections_in_scope

    if user.is_instructor:
        return class_offering.instructor_id == user.id
    if user.is_program_head:
        return class_offering.sections.filter(pk__in=sections_in_scope(user)).exists()
    return False


@role_required(INSTRUCTOR, PROGRAM_HEAD)
def recompute_class(request, pk):
    class_offering = get_object_or_404(ClassOffering, pk=pk)
    if not _owns_class_for_forecasting(request.user, class_offering):
        raise PermissionDenied("This class is not yours to recompute.")
    entries = class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE)
    recompute_and_notify(entries)
    messages.success(request, f"Forecasts recomputed for {class_offering}.")
    return redirect(request.META.get("HTTP_REFERER") or "forecasting:at_risk")


@role_required(PROGRAM_HEAD)
def recompute_program(request, pk):
    from academics.scoping import scope_for

    program = get_object_or_404(Program, pk=pk)
    scope = scope_for(request.user)
    if scope is not None and not any(program_id == program.id for program_id, _ in scope):
        raise PermissionDenied("This program is not under your headship.")
    active_semester = Semester.objects.filter(is_active=True).first()
    classes = ClassOffering.objects.filter(sections__program=program, semester=active_semester).distinct()
    entries = ClassRosterEntry.objects.filter(class_offering__in=classes, status=ClassRosterEntry.Status.ACTIVE)
    recompute_and_notify(entries)
    messages.success(request, f"Forecasts recomputed for {program.code}.")
    return redirect("forecasting:at_risk")


# ---------------------------------------------------------------------------
# Forecast detail (drawer) + interventions
# ---------------------------------------------------------------------------


@role_required(INSTRUCTOR, PROGRAM_HEAD)
def forecast_detail(request, pk):
    roster_entry = get_object_or_404(ClassRosterEntry.objects.select_related("student", "class_offering__subject"), pk=pk)
    if not _owns_class_for_forecasting(request.user, roster_entry.class_offering):
        raise PermissionDenied("This student is not in one of your classes.")
    return render(request, "forecasting/_forecast_drawer.html", _forecast_drawer_context(request, roster_entry))


@role_required(INSTRUCTOR, PROGRAM_HEAD)
def intervention_create(request, pk):
    roster_entry = get_object_or_404(ClassRosterEntry, pk=pk)
    class_offering = roster_entry.class_offering
    if not _owns_class_for_forecasting(request.user, class_offering):
        raise PermissionDenied("This student is not in one of your classes.")

    if request.method == "GET":
        form = InterventionForm(initial={"date": timezone.localdate()})
        return render(request, "forecasting/_intervention_modal.html", {"roster_entry": roster_entry, "form": form})

    form = InterventionForm(request.POST)
    if not form.is_valid():
        response = render(request, "forecasting/_intervention_modal.html", {"roster_entry": roster_entry, "form": form})
        response["HX-Retarget"] = "#modal-content"
        response["HX-Reswap"] = "innerHTML"
        return response

    intervention = form.save(commit=False)
    intervention.roster_entry = roster_entry
    intervention.created_by = request.user
    intervention.save()

    # Re-render the drawer (not a "modal-success" close) — the point is to
    # show the new intervention in place, not dismiss the drawer.
    return render(request, "forecasting/_forecast_drawer.html", _forecast_drawer_context(request, roster_entry))


def _forecast_drawer_context(request, roster_entry):
    """Shared by intervention_create's post-save re-render so the drawer
    refreshes with the new intervention in place."""
    class_offering = roster_entry.class_offering
    predictions = {
        p.checkpoint: p
        for p in Prediction.objects.filter(roster_entry=roster_entry).select_related("model_version")
    }
    current_checkpoint = current_checkpoint_for_class(class_offering)
    current_prediction = predictions.get(current_checkpoint) if current_checkpoint else None
    history = []
    for checkpoint, label in Checkpoint.choices:
        prediction = predictions.get(checkpoint)
        if prediction is None:
            continue
        history.append(
            {
                "checkpoint": checkpoint,
                "label": label,
                "probability_pct": round(float(prediction.probability) * 100, 1),
                "level": risk_level(prediction.probability, prediction.model_version.threshold),
            }
        )
    contributions = (current_prediction.contributions_json or {}).get("values", []) if current_prediction else []
    chart_labels = [c["feature"] for c in contributions]
    chart_values = [c["contribution"] for c in contributions]
    return {
        "roster_entry": roster_entry,
        "class_offering": class_offering,
        "prediction": current_prediction,
        "probability_pct": round(float(current_prediction.probability) * 100, 1) if current_prediction else None,
        "level": risk_level(current_prediction.probability, current_prediction.model_version.threshold) if current_prediction else None,
        "history": history,
        "contributions": contributions,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "interventions": roster_entry.interventions.select_related("created_by"),
        "show_synthetic_banner": current_prediction is not None and current_prediction.model_version.training_source != TrainingSource.HISTORICAL,
    }
