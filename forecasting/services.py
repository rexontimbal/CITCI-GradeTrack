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


def _checkpoints_for_classes(class_offerings):
    """{class_offering_id: checkpoint-or-None} for MANY classes in exactly
    2 queries total (one per tier), instead of up to 2 queries PER class —
    the batch primitive behind current_checkpoint_for_class (1 class),
    count_at_risk_watch, and get_display_forecasts_for_classes (Phase 8
    part B dashboard query-count pass — count_at_risk_watch calling the
    single-class version in a loop was the Program Head dashboard's
    biggest N+1, ~3 queries x every class in the program)."""
    from grading.models import ASSESSMENT_TERM_ORDER, AssessmentTerm, ComponentCategory, Score

    class_offerings = list(class_offerings)
    if not class_offerings:
        return {}

    midterm_cutoff = ASSESSMENT_TERM_ORDER[AssessmentTerm.MIDTERM]
    terms_upto_midterm = [t for t, order in ASSESSMENT_TERM_ORDER.items() if order <= midterm_cutoff]
    prelim_cutoff = ASSESSMENT_TERM_ORDER[AssessmentTerm.PRELIM]
    terms_upto_prelim = [t for t, order in ASSESSMENT_TERM_ORDER.items() if order <= prelim_cutoff]

    midterm_class_ids = set(
        Score.objects.filter(
            item__class_offering__in=class_offerings,
            item__component__category=ComponentCategory.EXAM,
            item__term__in=terms_upto_midterm,
            score__isnull=False,
        )
        .values_list("item__class_offering_id", flat=True)
        .distinct()
    )
    prelim_class_ids = set(
        Score.objects.filter(
            item__class_offering__in=class_offerings,
            item__term__in=terms_upto_prelim,
            score__isnull=False,
        )
        .values_list("item__class_offering_id", flat=True)
        .distinct()
    )

    checkpoints = {}
    for co in class_offerings:
        if co.pk in midterm_class_ids:
            checkpoints[co.pk] = Checkpoint.MIDTERM
        elif co.pk in prelim_class_ids:
            checkpoints[co.pk] = Checkpoint.PRELIM
        else:
            checkpoints[co.pk] = None
    return checkpoints


def current_checkpoint_for_class(class_offering):
    """MIDTERM if any EXAM-category item with term <= MIDTERM has a score
    anywhere in the class; else PRELIM if any PRELIM item (any category)
    has a score; else None ("Not enough data yet"). Single-class
    convenience wrapper around _checkpoints_for_classes — callers looping
    over many classes should call that directly instead (see
    count_at_risk_watch/get_display_forecasts_for_classes)."""
    return _checkpoints_for_classes([class_offering]).get(class_offering.pk)


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


def get_display_forecasts_for_classes(class_offerings):
    """Batch version of get_display_forecasts_for_class across MANY classes
    at once — the At-Risk pages (instructor and program head) used to call
    the single-class version once per class, which meant every one of its
    internal queries (checkpoint determination, roster fetch, prediction
    fetch, editability check) repeated per class — ~6-7 queries x N classes
    (Phase 8 part A left this at 118 queries for a program head with many
    classes; this pass batches every one of those steps into a handful of
    queries total). Returns {class_offering_id: (checkpoint-or-None,
    {roster_entry_id: forecast}, {roster_entry_id: ClassRosterEntry})} —
    the third element lets callers build display rows (student name,
    interventions) with no further queries."""
    from django.db.models import Prefetch

    from approvals.models import GradeSheet, GradeSheetPeriod, GradeSheetStatus

    from .models import Intervention

    class_offerings = list(class_offerings)
    if not class_offerings:
        return {}

    checkpoints = _checkpoints_for_classes(class_offerings)
    active_class_ids = [co.pk for co in class_offerings if checkpoints[co.pk] is not None]
    if not active_class_ids:
        return {co.pk: (None, {}, {}) for co in class_offerings}

    # Roster + interventions for every active class in one query each,
    # instead of once per class (and the old code fetched the roster
    # twice per class — once here, once in the view's row-builder).
    roster_entries = list(
        ClassRosterEntry.objects.filter(class_offering_id__in=active_class_ids, status=ClassRosterEntry.Status.ACTIVE)
        .select_related("student")
        .prefetch_related(Prefetch("interventions", queryset=Intervention.objects.order_by("-date", "-created_at")))
    )
    entries_by_class = {}
    entries_by_id_by_class = {}
    for entry in roster_entries:
        entries_by_class.setdefault(entry.class_offering_id, []).append(entry)
        entries_by_id_by_class.setdefault(entry.class_offering_id, {})[entry.id] = entry

    # All stored predictions for all these roster entries in one query
    # (both checkpoints — the table is small per student), instead of one
    # query per class.
    all_entry_ids = [e.id for e in roster_entries]
    predictions_by_entry = {}
    for p in Prediction.objects.filter(roster_entry_id__in=all_entry_ids).select_related("model_version"):
        predictions_by_entry.setdefault(p.roster_entry_id, {})[p.checkpoint] = p

    # Editability for every active class in one query, instead of one
    # GradeSheet query per class (approvals.services.is_class_editable).
    sheet_status = dict(
        GradeSheet.objects.filter(class_offering_id__in=active_class_ids, period=GradeSheetPeriod.FINAL).values_list(
            "class_offering_id", "status"
        )
    )
    editable_class_ids = {
        class_id
        for class_id in active_class_ids
        if sheet_status.get(class_id) is None
        or sheet_status.get(class_id) in (GradeSheetStatus.DRAFT, GradeSheetStatus.RETURNED)
    }

    results = {}
    for co in class_offerings:
        checkpoint = checkpoints[co.pk]
        if checkpoint is None:
            results[co.pk] = (None, {}, {})
            continue
        editable = co.pk in editable_class_ids
        forecasts = {}
        for entry in entries_by_class.get(co.pk, []):
            prediction = predictions_by_entry.get(entry.id, {}).get(checkpoint)
            if prediction is not None:
                forecasts[entry.id] = prediction
                continue
            if not editable:
                forecasts[entry.id] = NOT_ENOUGH_DATA
                continue
            try:
                from .ml.predict import predict_and_store

                result = predict_and_store(entry, checkpoint)
                forecasts[entry.id] = NOT_ENOUGH_DATA if result == "insufficient_data" else result
            except Exception:
                logger.exception("Forecast backfill failed for roster_entry=%s", entry.pk)
                forecasts[entry.id] = UNAVAILABLE
        results[co.pk] = (checkpoint, forecasts, entries_by_id_by_class.get(co.pk, {}))
    return results


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
    return _forecast_card_from(forecast, roster_entry.class_offering.subject.code)


def _forecast_card_from(forecast, subject_code):
    """The display-building half of student_forecast_card, factored out so
    the batch version below shares it instead of re-deriving the dict
    shape."""
    if isinstance(forecast, str):
        return None
    level = risk_level(forecast.probability, forecast.model_version.threshold)
    if level == "ON_TRACK":
        return {"level": level, "message": f"You're on track in {subject_code}. Keep it up!", "factors": [], "tips": []}
    return {
        "level": level,
        "message": f"{subject_code} needs your attention.",
        "factors": _top_student_factors(forecast),
        "tips": STUDENT_STUDY_TIPS,
    }


def student_forecast_cards_batch(roster_entries):
    """Batch version of student_forecast_card for the student dashboard
    (one student, several classes) — calls show_forecasts_to_students()
    once and get_display_forecasts_for_classes once, instead of the
    single-entry version's full checkpoint/prediction/editability query
    set PER roster entry (Phase 8 part B dashboard query-count pass — this
    was ~4-6 queries x every subject on the student dashboard). Returns
    {roster_entry_id: card-or-None}."""
    roster_entries = list(roster_entries)
    if not roster_entries or not show_forecasts_to_students():
        return {e.id: None for e in roster_entries}

    class_offerings = {e.class_offering_id: e.class_offering for e in roster_entries}
    bulk = get_display_forecasts_for_classes(class_offerings.values())

    cards = {}
    for entry in roster_entries:
        _checkpoint, forecasts, _entries = bulk.get(entry.class_offering_id, (None, {}, {}))
        forecast = forecasts.get(entry.id)
        cards[entry.id] = (
            _forecast_card_from(forecast, entry.class_offering.subject.code) if forecast is not None else None
        )
    return cards


def count_at_risk_watch(classes):
    """Cheap, read-only count for dashboard stat cards — never backfills
    missing predictions (that would make a dashboard load as slow as a
    full recompute sweep); just counts whatever's already stored for each
    class's current checkpoint. Returns {"at_risk": n, "watch": m}.

    Batched (Phase 8 part B dashboard query-count pass): checkpoints for
    every class are resolved in 2 queries total via _checkpoints_for_classes
    (not current_checkpoint_for_class in a loop), and every class's
    predictions are fetched in a single query grouped by checkpoint —
    instead of ~3 queries PER class, which was the Program Head dashboard's
    biggest single contributor (101 queries measured before this fix)."""
    from django.db.models import Q

    classes = list(classes)
    counts = {"at_risk": 0, "watch": 0}
    if not classes:
        return counts

    checkpoints = _checkpoints_for_classes(classes)
    by_checkpoint = {}
    for co in classes:
        checkpoint = checkpoints.get(co.pk)
        if checkpoint is not None:
            by_checkpoint.setdefault(checkpoint, []).append(co.pk)
    if not by_checkpoint:
        return counts

    query = Q()
    for checkpoint, class_ids in by_checkpoint.items():
        query |= Q(roster_entry__class_offering_id__in=class_ids, checkpoint=checkpoint)

    predictions = Prediction.objects.filter(
        query, roster_entry__status=ClassRosterEntry.Status.ACTIVE
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
