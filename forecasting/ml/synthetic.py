"""Synthetic training data — development and demo ONLY (CLAUDE.md section
7's Chapter 4 rule: the model shown in the final defense must be trained on
real, masked CITCI data). Generates feature rows with a realistic
correlated structure (a latent "skill" drives every feature, plus
independent noise so checkpoint features are predictive but not a perfect
giveaway of the outcome) and a fixed random seed so results are
reproducible.
"""

import numpy as np

DEFAULT_SEED = 20261104
DEFAULT_N = 2000
DEFAULT_POSITIVE_RATE = 0.20


def _clip(values, low, high):
    return np.clip(values, low, high)


def generate_synthetic_rows(checkpoint, n=DEFAULT_N, positive_rate=DEFAULT_POSITIVE_RATE, seed=DEFAULT_SEED):
    """Returns a list of n dicts, each with every name in FEATURE_NAMES
    (as plain floats — synthetic rows never have a "missing category",
    so every `<feature>_missing` flag the caller adds via
    forecasting.ml.features.to_vector-equivalent is always 0) plus
    "label" (1 = at risk, 0 = not)."""
    rng = np.random.RandomState(seed)

    # One latent ability per synthetic student — higher is better. Every
    # observed feature is a noisy linear function of it, so they're
    # correlated with each other and with the outcome, but not identical.
    skill = rng.normal(0, 1, n)
    noise = lambda scale: rng.normal(0, scale, n)  # noqa: E731

    quiz_pct = _clip(70 + 15 * skill + noise(10), 0, 100)
    recitation_pct = _clip(72 + 12 * skill + noise(10), 0, 100)
    project_pct = _clip(75 + 10 * skill + noise(9), 0, 100)
    attendance_pct = _clip(85 + 8 * skill + noise(8), 0, 100)
    exam_pct = _clip(65 + 18 * skill + noise(11), 0, 100)
    missing_rate_pct = _clip(10 - 8 * skill + noise(8), 0, 100)
    running_grade = _clip(3.0 - 1.3 * skill + noise(0.5), 1.0, 5.0)

    # What actually happens after the checkpoint is correlated with, but
    # not fully determined by, the checkpoint's own skill signal — this is
    # what keeps the classification task non-trivial (recall well above
    # 0.7 but not ~1.0 — see the training sanity test).
    outcome_skill = skill + noise(0.9)
    cutoff = np.quantile(outcome_skill, positive_rate)  # bottom `positive_rate` fraction = at risk
    label = (outcome_skill <= cutoff).astype(int)

    rows = []
    for i in range(n):
        rows.append(
            {
                "quiz_pct": float(quiz_pct[i]),
                "recitation_pct": float(recitation_pct[i]),
                "project_pct": float(project_pct[i]),
                "attendance_pct": float(attendance_pct[i]),
                "exam_pct": float(exam_pct[i]),
                "running_grade": float(running_grade[i]),
                "missing_rate_pct": float(missing_rate_pct[i]),
                "label": int(label[i]),
            }
        )
    return rows
