from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import User
from accounts.utils import coming_soon

from .historical_import import build_import_preview, commit_import, export_released_data_to_historical
from .ml.train import train_model
from .models import Checkpoint, HistoricalImportBatch, MlModelVersion, TrainingSource

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
# Phase 7 placeholder
# ---------------------------------------------------------------------------


@role_required(PROGRAM_HEAD, INSTRUCTOR)
def at_risk(request):
    return coming_soon(request, "At-Risk Students")
