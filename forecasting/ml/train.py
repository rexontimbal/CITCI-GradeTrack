"""Training pipeline: StandardScaler -> LogisticRegression(class_weight=
"balanced", max_iter=1000), fixed random_state throughout. CLAUDE.md
section 7.
"""

import math
from decimal import Decimal

import joblib
import numpy as np
from django.conf import settings
from django.core.exceptions import ValidationError
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from forecasting.models import HistoricalRecord, MlModelVersion, TrainingSource

from .evaluate import evaluate_model
from .features import FEATURE_NAMES, FEATURE_VECTOR_NAMES, compute_medians, to_vector
from .synthetic import generate_synthetic_rows

RANDOM_STATE = 20261104
MIN_HISTORICAL_ROWS = 200
MIN_HISTORICAL_POSITIVES = 30


def _rows_from_historical(checkpoint):
    """HistoricalRecord.features_json stores each value as a string (or
    null) — JSONField can't hold Decimal directly — so convert back here."""
    rows = []
    for record in HistoricalRecord.objects.filter(checkpoint=checkpoint):
        row = {
            name: (Decimal(value) if value is not None else None)
            for name, value in record.features_json.items()
            if name in FEATURE_NAMES
        }
        row["label"] = record.label
        rows.append(row)
    return rows


def _check_historical_sufficient(rows, checkpoint):
    positives = sum(row["label"] for row in rows)
    if len(rows) < MIN_HISTORICAL_ROWS or positives < MIN_HISTORICAL_POSITIVES:
        raise ValidationError(
            f"Not enough historical data to train the {checkpoint} model on HISTORICAL alone: "
            f"{len(rows)} row(s), {positives} positive. Need at least {MIN_HISTORICAL_ROWS} rows "
            f"and {MIN_HISTORICAL_POSITIVES} positives. Import more historical data, or use "
            "source=mixed for development (never for the Chapter 4 / final-defense model)."
        )


def gather_training_rows(checkpoint, source):
    """Returns (rows, used_source). Each row is a dict with FEATURE_NAMES
    keys (raw, pre-imputation — may be None for historical-derived rows)
    plus "label" (1/0)."""
    if source == TrainingSource.SYNTHETIC:
        return generate_synthetic_rows(checkpoint), TrainingSource.SYNTHETIC

    historical_rows = _rows_from_historical(checkpoint)

    if source == TrainingSource.HISTORICAL:
        _check_historical_sufficient(historical_rows, checkpoint)
        return historical_rows, TrainingSource.HISTORICAL

    if source == TrainingSource.MIXED:
        return historical_rows + generate_synthetic_rows(checkpoint), TrainingSource.MIXED

    raise ValueError(f"Unknown training source: {source!r}")


def _vectorize(rows, medians):
    return np.array([[to_vector(row, medians)[name] for name in FEATURE_VECTOR_NAMES] for row in rows])


def train_model(checkpoint, source, threshold=Decimal("0.50")):
    """Trains, evaluates, and persists a new INACTIVE MlModelVersion (an
    admin must explicitly Activate it — never automatic on training, see
    CLAUDE.md section 7). Raises ValidationError if source=HISTORICAL and
    there isn't enough data yet."""
    rows, used_source = gather_training_rows(checkpoint, source)
    labels = [row["label"] for row in rows]

    train_idx, test_idx = train_test_split(
        range(len(rows)), test_size=0.2, stratify=labels, random_state=RANDOM_STATE
    )
    train_rows = [rows[i] for i in train_idx]
    test_rows = [rows[i] for i in test_idx]
    y_train = np.array([row["label"] for row in train_rows])
    y_test = np.array([row["label"] for row in test_rows])

    # Fit ONCE on the training split only, reused as-is for the test split
    # and for every later live prediction — never refit.
    medians = compute_medians(train_rows)
    X_train = _vectorize(train_rows, medians)
    X_test = _vectorize(test_rows, medians)

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE)),
        ]
    )
    pipeline.fit(X_train, y_train)

    evaluation = evaluate_model(pipeline, X_test, y_test, X_train, y_train, threshold=float(threshold))

    clf = pipeline.named_steps["clf"]
    coefficients = [
        {"feature": name, "coefficient": float(coef), "odds_ratio": float(math.exp(coef))}
        for name, coef in zip(FEATURE_VECTOR_NAMES, clf.coef_[0])
    ]
    feature_list = {
        "names": FEATURE_VECTOR_NAMES,
        "medians": {name: str(value) for name, value in medians.items()},
        "intercept": float(clf.intercept_[0]),
    }

    metrics_json = {**evaluation["metrics"], "threshold_table": evaluation["threshold_table"]}
    version = MlModelVersion.objects.create(
        checkpoint=checkpoint,
        training_source=used_source,
        n_samples=len(rows),
        positive_rate=Decimal(str(round(sum(labels) / len(labels), 4))),
        threshold=threshold,
        metrics_json=metrics_json,
        cv_json=evaluation["cv"],
        confusion_matrix_json=evaluation["confusion_matrix"],
        coefficients_json=coefficients,
        feature_list=feature_list,
        is_active=False,
        model_file="",
    )

    models_dir = settings.MEDIA_ROOT / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_path = models_dir / f"{version.pk}.joblib"
    joblib.dump(pipeline, model_path)
    version.model_file = str(model_path.relative_to(settings.MEDIA_ROOT))
    version.save(update_fields=["model_file"])

    return version
