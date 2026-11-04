"""Forecast display/recompute logic — pure functions, no view/HTTP
concerns. CLAUDE.md section 7 part 2.

Predictions are stored (forecasting.Prediction), not computed live on
every page view — this module keeps that table fresh (after a score save,
after an Excel import, via the "Recompute" button, via `run_forecasts`)
and reads from it for display, lazily backfilling a missing row only when
the class is still editable (never once a grade sheet is SUBMITTED or
later — the last forecast is kept for evaluation at that point).

A prediction is never allowed to break a grading/dashboard page: every
path that can fail is wrapped and logged, surfacing "not_enough_data" or
"unavailable" to the caller instead of raising.
"""

import logging

from django.utils import timezone

from academics.models import ClassRosterEntry

from .models import Checkpoint, Prediction

logger = logging.getLogger(__name__)

NOT_ENOUGH_DATA = "not_enough_data"
UNAVAILABLE = "unavailable"


def risk_level(probability, threshold):
    """The single three-tier helper used everywhere (CLAUDE.md section 7
    part 2): AT_RISK >= threshold, WATCH >= threshold-0.15, else ON_TRACK.
    AT_RISK matches exactly the model's own stored RiskLabel.AT_RISK
    condition — WATCH is a purely-display intermediate tier, never stored."""
    probability = float(probability)
    threshold = float(threshold)
    if probability >= threshold:
        return "AT_RISK"
    if probability >= threshold - 0.15:
        return "WATCH"
    return "ON_TRACK"


def current_checkpoint_for_class(class_offering):
    """MIDTERM if any EXAM-category item with term <= MIDTERM has a score
    anywhere in the class; else PRELIM if any PRELIM item (any category)
    has a score; else None ("Not enough data yet")."""
    from grading.models import ASSESSMENT_TERM_ORDER, AssessmentItem, AssessmentTerm, ComponentCategory, Score

    midterm_cutoff = ASSESSMENT_TERM_ORDER[AssessmentTerm.MIDTERM]
    exam_item_ids = [
        item.id
        for item in AssessmentItem.objects.filter(class_offering=class_offering, component__category=ComponentCategory.EXAM)
        if ASSESSMENT_TERM_ORDER[item.term] <= midterm_cutoff
    ]
    if exam_item_ids and Score.objects.filter(item_id__in=exam_item_ids, score__isnull=False).exists():
        return Checkpoint.MIDTERM

    prelim_cutoff = ASSESSMENT_TERM_ORDER[AssessmentTerm.PRELIM]
    prelim_item_ids = [
        item.id
        for item in AssessmentItem.objects.filter(class_offering=class_offering)
        if ASSESSMENT_TERM_ORDER[item.term] <= prelim_cutoff
    ]
    if prelim_item_ids and Score.objects.filter(item_id__in=prelim_item_ids, score__isnull=False).exists():
        return Checkpoint.PRELIM

    return None


def show_forecasts_to_students():
    from reports.models import InstitutionSettings

    return InstitutionSettings.get_solo().show_forecasts_to_students


def get_display_forecast(roster_entry):
    """Returns a Prediction, or the string NOT_ENOUGH_DATA / UNAVAILABLE.
    Never raises."""
    class_offering = roster_entry.class_offering
    try:
        checkpoint = current_checkpoint_for_class(class_offering)
        if checkpoint is None:
            return NOT_ENOUGH_DATA

        prediction = (
            Prediction.objects.filter(roster_entry=roster_entry, checkpoint=checkpoint)
            .select_related("model_version")
            .first()
        )
        if prediction is not None:
            return prediction

        from approvals.services import is_class_editable

        if not is_class_editable(class_offering):
            return NOT_ENOUGH_DATA  # was never computed while editable — nothing to show

        from .ml.predict import predict_and_store

        result = predict_and_store(roster_entry, checkpoint)
        return NOT_ENOUGH_DATA if result == "insufficient_data" else result
    except Exception:
        logger.exception("Forecast display failed for roster_entry=%s", roster_entry.pk)
        return UNAVAILABLE


def get_display_forecasts_for_class(class_offering):
    """Bulk version of get_display_forecast for a whole class (Class
    Record grid, At-Risk list) — one query for existing predictions, then
    lazily backfills only the roster entries missing one. Returns
    (checkpoint-or-None, {roster_entry_id: Prediction-or-sentinel})."""
    try:
        checkpoint = current_checkpoint_for_class(class_offering)
        if checkpoint is None:
            return None, {}

        roster_entries = list(class_offering.roster_entries.filter(status=ClassRosterEntry.Status.ACTIVE))
        existing = {
            p.roster_entry_id: p
            for p in Prediction.objects.filter(
                roster_entry__in=roster_entries, checkpoint=checkpoint
            ).select_related("model_version")
        }

        from approvals.services import is_class_editable

        editable = is_class_editable(class_offering)
        results = {}
        for entry in roster_entries:
            prediction = existing.get(entry.id)
            if prediction is not None:
                results[entry.id] = prediction
                continue
            if not editable:
                results[entry.id] = NOT_ENOUGH_DATA
                continue
            try:
                from .ml.predict import predict_and_store

                result = predict_and_store(entry, checkpoint)
                results[entry.id] = NOT_ENOUGH_DATA if result == "insufficient_data" else result
            except Exception:
                logger.exception("Forecast backfill failed for roster_entry=%s", entry.pk)
                results[entry.id] = UNAVAILABLE
        return checkpoint, results
    except Exception:
        logger.exception("Forecast bulk display failed for class_offering=%s", class_offering.pk)
        return None, {}


STUDENT_STUDY_TIPS = [
    "Review your notes a little each day instead of cramming before an exam.",
    "Ask your instructor a specific question about what's unclear to you.",
    "Form a small study group with classmates in the same class.",
]

# Deliberately no numbers and never the words "at risk" — CLAUDE.md section
# 7 part 2, section 5: student-facing copy stays supportive and plain.
_STUDENT_FACTOR_LABELS = {
    "quiz_pct": "quiz scores are low",
    "recitation_pct": "recitation scores are low",
    "project_pct": "project/activity scores are low",
    "attendance_pct": "attendance has been low",
    "exam_pct": "exam scores are low",
    "running_grade": "your overall grade needs improvement",
    "missing_rate_pct": "several scores are still missing",
}


def _top_student_factors(prediction, n=2):
    values = (prediction.contributions_json or {}).get("values", [])
    factors = []
    for contribution in values:
        name = contribution["feature"]
        if name.endswith("_missing") or contribution["contribution"] <= 0:
            continue
        label = _STUDENT_FACTOR_LABELS.get(name)
        if label and label not in factors:
            factors.append(label)
        if len(factors) >= n:
            break
    return factors


def student_forecast_card(roster_entry):
    """Supportive, never-probability, never-"at risk" summary for the
    student dashboard card / Subject detail section (CLAUDE.md section 5).
    Returns None when the admin toggle is off, or there's simply nothing
    to show ("not_enough_data"/"unavailable") — the caller omits the card
    entirely in that case, never a blank/broken one."""
    if not show_forecasts_to_students():
        return None

    forecast = get_display_forecast(roster_entry)
    if isinstance(forecast, str):
        return None

    level = risk_level(forecast.probability, forecast.model_version.threshold)
    subject_code = roster_entry.class_offering.subject.code

    if level == "ON_TRACK":
        return {"level": level, "message": f"You're on track in {subject_code}. Keep it up!", "factors": [], "tips": []}

    return {
        "level": level,
        "message": f"{subject_code} needs your attention.",
        "factors": _top_student_factors(forecast),
        "tips": STUDENT_STUDY_TIPS,
    }


def count_at_risk_watch(classes):
    """Cheap, read-only count for dashboard stat cards — never backfills
    missing predictions (that would make a dashboard load as slow as a
    full recompute sweep); just counts whatever's already stored for each
    class's current checkpoint. Returns {"at_risk": n, "watch": m}."""
    counts = {"at_risk": 0, "watch": 0}
    for class_offering in classes:
        checkpoint = current_checkpoint_for_class(class_offering)
        if checkpoint is None:
            continue
        predictions = Prediction.objects.filter(
            roster_entry__class_offering=class_offering,
            roster_entry__status=ClassRosterEntry.Status.ACTIVE,
            checkpoint=checkpoint,
        ).select_related("model_version")
        for prediction in predictions:
            level = risk_level(prediction.probability, prediction.model_version.threshold)
            if level == "AT_RISK":
                counts["at_risk"] += 1
            elif level == "WATCH":
                counts["watch"] += 1
    return counts


def recompute_and_notify(roster_entries):
    """The one trigger used after a score save, an Excel import confirm,
    the "Recompute" button, and `run_forecasts` — recomputes + persists
    predictions for exactly the given roster entries (grouped by class,
    each class's CURRENT checkpoint only), then fires early-warning
    notifications for NEW at-risk/watch episodes only (never a repeat on
    every save while a student stays at the same level). A no-op (per
    class) once that class's grade sheet has left DRAFT/RETURNED — the
    last forecast is kept for evaluation. Never raises; every failure is
    logged and skipped. Returns the list of newly-at-risk roster entries
    (across all classes), mostly useful for tests."""
    from approvals.services import is_class_editable
    from dashboard.services import notify
    from grading.services import released_entry_for

    from .ml.predict import predict_and_store

    roster_entries = list(roster_entries)
    by_class = {}
    for entry in roster_entries:
        by_class.setdefault(entry.class_offering_id, []).append(entry)

    notify_students = show_forecasts_to_students()
    all_newly_at_risk = []

    for entries in by_class.values():
        class_offering = entries[0].class_offering
        if not is_class_editable(class_offering):
            continue
        checkpoint = current_checkpoint_for_class(class_offering)
        if checkpoint is None:
            continue

        newly_at_risk = []
        newly_watch_or_worse = []

        for entry in entries:
            try:
                old = Prediction.objects.filter(roster_entry=entry, checkpoint=checkpoint).first()
                result = predict_and_store(entry, checkpoint)
            except Exception:
                logger.exception("Forecast recompute failed for roster_entry=%s", entry.pk)
                continue
            if result == "insufficient_data":
                continue

            level = risk_level(result.probability, result.model_version.threshold)
            was_notified_instructor = bool(old and old.instructor_notified_at)
            was_notified_student = bool(old and old.student_notified_at)
            update_fields = []

            if level == "AT_RISK" and not was_notified_instructor:
                newly_at_risk.append(entry)
                result.instructor_notified_at = timezone.now()
                update_fields.append("instructor_notified_at")
            elif level != "AT_RISK" and old and old.instructor_notified_at:
                result.instructor_notified_at = None
                update_fields.append("instructor_notified_at")

            if notify_students and level in ("AT_RISK", "WATCH") and not was_notified_student:
                newly_watch_or_worse.append(entry)
                result.student_notified_at = timezone.now()
                update_fields.append("student_notified_at")
            elif level == "ON_TRACK" and old and old.student_notified_at:
                result.student_notified_at = None
                update_fields.append("student_notified_at")

            if update_fields:
                result.save(update_fields=update_fields)

        if newly_at_risk and class_offering.instructor:
            count = len(newly_at_risk)
            notify(
                class_offering.instructor,
                "Students may need attention",
                f"{count} student{'s' if count != 1 else ''} in {class_offering.subject.code} may need attention.",
                link="/forecasting/at-risk/",
            )
            all_newly_at_risk.extend(newly_at_risk)

        for entry in newly_watch_or_worse:
            released_entry = released_entry_for(entry)
            if released_entry is not None:
                continue  # already released — a supportive nudge is pointless now
            notify(
                entry.student,
                "A quick check-in",
                f"We noticed something in {class_offering.subject.code} — take a look when you can.",
                link=f"/grading/my-grades/{entry.pk}/",
            )

    return all_newly_at_risk
