from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from academics.models import ClassOffering, ClassRosterEntry, Program, Semester
from accounts.decorators import role_required
from accounts.models import User

from .forms import InterventionForm
from .historical_import import build_import_preview, commit_import, export_released_data_to_historical
from .ml.train import train_model
from .models import Checkpoint, HistoricalImportBatch, Intervention, MlModelVersion, Prediction, TrainingSource
from .services import current_checkpoint_for_class, get_display_forecasts_for_class, recompute_and_notify, risk_level

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
            messages.success(request, f"Trained {version} — inactive until you Activate it below.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
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


@role_required(ADMIN)
def historical_import_upload(request):
    if request.method != "POST":
        return render(request, "forecasting/_historical_import_modal.html", {})

    uploaded_files = request.FILES.getlist("files")
    if not uploaded_files:
        return render(request, "forecasting/_historical_import_modal.html", {"error": "Choose at least one file."})

    files = [(f.name, f) for f in uploaded_files]
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


@role_required(ADMIN)
def historical_import_confirm(request):
    stashed = request.session.get("historical_import_preview")
    if not stashed:
        response = render(
            request, "forecasting/_historical_import_modal.html", {"error": "Your preview expired — upload again."}
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


def _class_at_risk_rows(class_offering, level_filter=None):
    """[{entry, class_offering, checkpoint, level, probability, prediction,
    reasons, last_intervention}, ...] for AT_RISK/WATCH students only."""
    checkpoint, forecasts = get_display_forecasts_for_class(class_offering)
    if checkpoint is None:
        return []

    # prefetch_related + Prefetch(..., to_attr=) so entry.interventions.first()
    # below reads from memory instead of issuing one query per AT_RISK/
    # WATCH row (Phase 8 part A query-count pass).
    from django.db.models import Prefetch

    roster_entries = {
        e.id: e
        for e in class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE)
        .select_related("student")
        .prefetch_related(Prefetch("interventions", queryset=Intervention.objects.order_by("-date", "-created_at")))
    }
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
def at_risk(request):
    if request.user.is_instructor:
        return _at_risk_instructor(request)
    return _at_risk_program_head(request)


def _at_risk_instructor(request):
    active_semester = Semester.objects.filter(is_active=True).first()
    classes = (
        ClassOffering.objects.filter(instructor=request.user, semester=active_semester).select_related("subject")
        if active_semester
        else ClassOffering.objects.none()
    )

    class_filter = request.GET.get("class")
    level_filter = request.GET.get("level")

    rows = []
    for class_offering in classes:
        if class_filter and str(class_offering.pk) != class_filter:
            continue
        rows.extend(_class_at_risk_rows(class_offering, level_filter))
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
        "show_synthetic_banner": _any_non_historical_active_model(),
    }
    return render(request, "forecasting/at_risk_instructor.html", context)


def _program_head_classes(user, active_semester):
    if active_semester is None:
        return ClassOffering.objects.none()
    return (
        ClassOffering.objects.filter(sections__program__program_head=user, semester=active_semester)
        .select_related("subject", "instructor")
        .distinct()
    )


def _at_risk_program_head(request):
    active_semester = Semester.objects.filter(is_active=True).first()
    classes = list(_program_head_classes(request.user, active_semester))

    class_filter = request.GET.get("class")
    level_filter = request.GET.get("level")

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

    rows = []
    by_class = {}
    for class_offering in classes:
        class_rows = _class_at_risk_rows(class_offering)
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
            rows.append(row)
    rows.sort(key=lambda r: r["probability"], reverse=True)

    total_at_risk = sum(c["at_risk"] for c in by_class.values())
    total_watch = sum(c["watch"] for c in by_class.values())
    classes_affected = sum(1 for c in by_class.values() if c["at_risk"] or c["watch"])
    total_interventions = sum(intervention_counts.values())

    from django.core.paginator import Paginator

    paginator = Paginator(rows, 25)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "At-Risk Students",
        "classes": classes,
        "rows": page,
        "class_filter": class_filter,
        "level_filter": level_filter,
        "by_class": by_class.values(),
        "summary": {
            "at_risk": total_at_risk,
            "watch": total_watch,
            "classes_affected": classes_affected,
            "interventions": total_interventions,
        },
        "show_synthetic_banner": _any_non_historical_active_model(),
    }
    return render(request, "forecasting/at_risk_program_head.html", context)


@role_required(PROGRAM_HEAD)
def at_risk_export(request):
    from openpyxl import Workbook

    from reports.excel import workbook_response

    active_semester = Semester.objects.filter(is_active=True).first()
    classes = list(_program_head_classes(request.user, active_semester))

    wb = Workbook()
    ws = wb.active
    ws.title = "At-Risk Students"
    ws.append(["Student", "ID Number", "Class", "Instructor", "Checkpoint", "Risk Level", "Probability %"])
    for class_offering in classes:
        for row in _class_at_risk_rows(class_offering):
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
    if user.is_instructor:
        return class_offering.instructor_id == user.id
    if user.is_program_head:
        return class_offering.sections.filter(program__program_head_id=user.id).exists()
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
    program = get_object_or_404(Program, pk=pk)
    if program.program_head_id != request.user.id:
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
