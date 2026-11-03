"""Live prediction for one (roster_entry, checkpoint) pair. CLAUDE.md
section 7.
"""

from decimal import Decimal

import joblib
from django.conf import settings

from forecasting.models import MlModelVersion, Prediction, RiskLabel

from .features import FEATURE_NAMES, FEATURE_VECTOR_NAMES, extract_features, to_vector

# Plain-language reason templates for the student/instructor-facing
# explanation — only used for a feature whose contribution pushed risk UP.
REASON_TEMPLATES = {
    "quiz_pct": "Quiz average ({value:.0f}%) is low",
    "recitation_pct": "Recitation average ({value:.0f}%) is low",
    "project_pct": "Project/activity average ({value:.0f}%) is low",
    "attendance_pct": "Attendance ({value:.0f}%) is low",
    "exam_pct": "Exam average ({value:.0f}%) is low",
    "running_grade": "Running grade ({value:.2f}) is weak",
    "missing_rate_pct": "Many missing scores ({value:.0f}%)",
}

_pipeline_cache = {}  # {model_version_id: fitted sklearn Pipeline} — process-local


def _load_pipeline(model_version):
    cached = _pipeline_cache.get(model_version.pk)
    if cached is not None:
        return cached
    pipeline = joblib.load(settings.MEDIA_ROOT / model_version.model_file)
    _pipeline_cache[model_version.pk] = pipeline
    return pipeline


def get_active_model(checkpoint):
    return MlModelVersion.objects.filter(checkpoint=checkpoint, is_active=True).first()


def _contributions(pipeline, vector):
    scaler = pipeline.named_steps["scaler"]
    clf = pipeline.named_steps["clf"]
    raw = [vector[name] for name in FEATURE_VECTOR_NAMES]
    standardized = scaler.transform([raw])[0]

    values = [
        {"feature": name, "contribution": float(coef * z)}
        for name, coef, z in zip(FEATURE_VECTOR_NAMES, clf.coef_[0], standardized)
    ]
    values.sort(key=lambda c: abs(c["contribution"]), reverse=True)

    reasons = []
    for item in values:
        name = item["feature"]
        if name.endswith("_missing") or name not in REASON_TEMPLATES:
            continue
        if item["contribution"] <= 0:
            continue  # only features that pushed risk UP become a "reason"
        reasons.append(REASON_TEMPLATES[name].format(value=vector[name]))
        if len(reasons) >= 3:
            break

    return {"values": values, "reasons": reasons, "intercept": float(clf.intercept_[0])}


def predict(roster_entry, checkpoint, model_version=None):
    """Returns {"probability", "label", "contributions"} or the string
    "insufficient_data" — either no trained/active model for this
    checkpoint yet, or the class has no scored items up to it."""
    if model_version is None:
        model_version = get_active_model(checkpoint)
        if model_version is None:
            return "insufficient_data"

    features = extract_features(roster_entry, checkpoint)
    if features is None:
        return "insufficient_data"

    medians = {name: Decimal(model_version.feature_list["medians"][name]) for name in FEATURE_NAMES}
    vector = to_vector(features, medians)

    pipeline = _load_pipeline(model_version)
    x = [[vector[name] for name in FEATURE_VECTOR_NAMES]]
    probability = float(pipeline.predict_proba(x)[0, 1])
    label = RiskLabel.AT_RISK if probability >= float(model_version.threshold) else RiskLabel.NOT_AT_RISK

    return {
        "probability": probability,
        "label": label,
        "contributions": _contributions(pipeline, vector),
    }


def predict_and_store(roster_entry, checkpoint):
    """predict() plus persisting (or updating) the forecasting.Prediction
    row for this (roster_entry, checkpoint). Returns the Prediction
    instance, or "insufficient_data"."""
    model_version = get_active_model(checkpoint)
    if model_version is None:
        return "insufficient_data"

    result = predict(roster_entry, checkpoint, model_version=model_version)
    if result == "insufficient_data":
        return result

    prediction, _ = Prediction.objects.update_or_create(
        roster_entry=roster_entry,
        checkpoint=checkpoint,
        defaults={
            "model_version": model_version,
            "probability": Decimal(str(round(result["probability"], 5))),
            "label": result["label"],
            "contributions_json": result["contributions"],
        },
    )
    return prediction
