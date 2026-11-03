"""Evaluation — single-split metrics + 95% bootstrap CIs + 5-fold stratified
CV, run on every training run (forecasting/ml/train.py). CLAUDE.md section 7.
"""

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_validate

N_BOOTSTRAP = 1000
BOOTSTRAP_SEED = 20261104
CV_FOLDS = 5
THRESHOLD_SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7)


def _metrics_at_threshold(y_true, y_prob, threshold):
    y_pred = (y_prob >= threshold).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }


def _bootstrap_ci(y_true, y_prob, threshold, n=N_BOOTSTRAP, seed=BOOTSTRAP_SEED):
    rng = np.random.RandomState(seed)
    n_samples = len(y_true)
    samples = {"accuracy": [], "precision": [], "recall": [], "f1": [], "roc_auc": []}
    for _ in range(n):
        idx = rng.randint(0, n_samples, n_samples)
        y_true_sample, y_prob_sample = y_true[idx], y_prob[idx]
        if len(set(y_true_sample)) < 2:
            continue  # roc_auc (and a meaningful precision/recall) need both classes present
        metrics = _metrics_at_threshold(y_true_sample, y_prob_sample, threshold)
        for key, value in metrics.items():
            samples[key].append(value)
        samples["roc_auc"].append(float(roc_auc_score(y_true_sample, y_prob_sample)))

    ci = {}
    for key, values in samples.items():
        if not values:
            ci[key] = [None, None]
            continue
        ci[key] = [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
    return ci


def threshold_table(y_true, y_prob, thresholds=THRESHOLD_SWEEP):
    return [{"threshold": t, **_metrics_at_threshold(y_true, y_prob, t)} for t in thresholds]


def evaluate_model(pipeline, X_test, y_test, X_train, y_train, threshold=0.5):
    """Returns {"metrics": {...with ci_95...}, "confusion_matrix": [[..]],
    "cv": {...}, "threshold_table": [...]}. `pipeline` must already be
    fitted on X_train/y_train; CV refits fresh clones per fold internally
    (no leakage — the scaler is part of the pipeline)."""
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    metrics = _metrics_at_threshold(y_test, y_prob, threshold)
    metrics["roc_auc"] = float(roc_auc_score(y_test, y_prob)) if len(set(y_test)) > 1 else None
    metrics["ci_95"] = _bootstrap_ci(y_test, y_prob, threshold)

    y_pred = (y_prob >= threshold).astype(int)
    confusion = confusion_matrix(y_test, y_pred, labels=[0, 1]).tolist()

    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=BOOTSTRAP_SEED)
    scoring = ["accuracy", "precision", "recall", "f1", "roc_auc"]
    cv_results = cross_validate(pipeline, X_train, y_train, cv=skf, scoring=scoring)
    cv = {
        key: {"mean": float(np.mean(cv_results[f"test_{key}"])), "sd": float(np.std(cv_results[f"test_{key}"]))}
        for key in scoring
    }

    return {
        "metrics": metrics,
        "confusion_matrix": confusion,
        "cv": cv,
        "threshold_table": threshold_table(y_test, y_prob),
    }
