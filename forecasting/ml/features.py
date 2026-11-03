"""Feature extraction — keyed off grading.ComponentCategory, NEVER a
component's free-text name (CLAUDE.md section 4/7), since instructors
rename/reweight their own unlocked components per class. A renamed or
instructor-invented component still feeds the right feature because
extraction groups by category.

Checkpoints replace "midterm grade" (CITCI's class record has none — only
four grading periods). Features for a checkpoint use ONLY items whose term
is at or before that checkpoint: Semi-final/Final items must NEVER reach a
PRELIM/MIDTERM feature row — this is a data-leakage guard, not a style
choice, and is covered by a dedicated test.
"""

from decimal import Decimal

from grading.models import ASSESSMENT_TERM_ORDER, AssessmentTerm, ComponentCategory, Score
from grading.services import get_encoded_item_ids, get_scheme_components, running_grade_progression

CHECKPOINT_CUTOFF = {
    "PRELIM": ASSESSMENT_TERM_ORDER[AssessmentTerm.PRELIM],
    "MIDTERM": ASSESSMENT_TERM_ORDER[AssessmentTerm.MIDTERM],
}

# The five earned/possible-percentage features, plus running_grade and
# missing_rate_pct — the full, final feature list (CLAUDE.md section 7).
PCT_FEATURES = ["quiz_pct", "recitation_pct", "project_pct", "attendance_pct", "exam_pct"]
FEATURE_NAMES = PCT_FEATURES + ["running_grade", "missing_rate_pct"]
FEATURE_VECTOR_NAMES = FEATURE_NAMES + [f"{name}_missing" for name in FEATURE_NAMES]

# PROJECT and OTHER are merged into one feature — CITCI's "Other" bucket is
# project-adjacent, not a distinct signal (CLAUDE.md section 7).
_CATEGORY_TO_FEATURE = {
    ComponentCategory.QUIZ: "quiz_pct",
    ComponentCategory.RECITATION: "recitation_pct",
    ComponentCategory.PROJECT: "project_pct",
    ComponentCategory.OTHER: "project_pct",
    ComponentCategory.ATTENDANCE: "attendance_pct",
    ComponentCategory.EXAM: "exam_pct",
}


def extract_features(roster_entry, checkpoint):
    """Returns a dict of FEATURE_NAMES -> Decimal-or-None (None = the
    instructor never set up that category at all, or nobody in the class
    has been scored on it yet, at or before this checkpoint — the caller
    imputes those with the TRAINING SET's median, never a fresh value).
    Returns None entirely when nothing at all has been scored up to this
    checkpoint — the "insufficient_data" case."""
    cutoff = CHECKPOINT_CUTOFF[checkpoint]
    components = get_scheme_components(roster_entry.class_offering)

    items_by_feature = {name: [] for name in PCT_FEATURES}
    for component in components:
        feature_name = _CATEGORY_TO_FEATURE.get(component.category)
        if feature_name is None:
            continue
        for item in component.items.all():
            # The leakage guard: an item past the checkpoint's term is
            # simply never added to any bucket below.
            if ASSESSMENT_TERM_ORDER[item.term] <= cutoff:
                items_by_feature[feature_name].append(item)

    all_in_scope_ids = [item.id for items in items_by_feature.values() for item in items]
    if not all_in_scope_ids:
        return None

    encoded_item_ids = get_encoded_item_ids(all_in_scope_ids)
    scores_by_item = {
        s.item_id: s.score for s in Score.objects.filter(roster_entry=roster_entry, item_id__in=all_in_scope_ids)
    }

    features = {}
    for feature_name in PCT_FEATURES:
        encoded_items = [item for item in items_by_feature[feature_name] if item.id in encoded_item_ids]
        if not encoded_items:
            features[feature_name] = None
            continue
        earned = Decimal("0")
        possible = Decimal("0")
        for item in encoded_items:
            possible += item.max_score
            score = scores_by_item.get(item.id)
            if score is not None:
                earned += score
        features[feature_name] = (earned / possible * 100) if possible else None

    all_encoded_items = [
        item for items in items_by_feature.values() for item in items if item.id in encoded_item_ids
    ]
    if all_encoded_items:
        missing = sum(1 for item in all_encoded_items if scores_by_item.get(item.id) is None)
        features["missing_rate_pct"] = Decimal(missing) / Decimal(len(all_encoded_items)) * 100
    else:
        features["missing_rate_pct"] = None

    progression = {term: grade for term, _label, grade in running_grade_progression(roster_entry)}
    features["running_grade"] = progression.get(checkpoint)

    if all(value is None for value in features.values()):
        return None  # nothing scored at all yet — insufficient_data

    return features


def compute_medians(rows):
    """rows: a list of extract_features()-shaped dicts (pre-imputation).
    Returns {feature_name: Decimal} — the median of the non-None values
    for each feature, fit ONCE on a training split and reused as-is for
    the test split and for every later live prediction (never refit)."""
    medians = {}
    for name in FEATURE_NAMES:
        values = sorted(row[name] for row in rows if row.get(name) is not None)
        if not values:
            medians[name] = Decimal("0")
            continue
        mid = len(values) // 2
        if len(values) % 2:
            medians[name] = values[mid]
        else:
            medians[name] = (values[mid - 1] + values[mid]) / 2
    return medians


def to_vector(features, medians):
    """Impute + flag-missing a single extract_features() result into a
    plain float dict keyed by FEATURE_VECTOR_NAMES, ready for sklearn."""
    vector = {}
    for name in FEATURE_NAMES:
        value = features.get(name)
        is_missing = value is None
        vector[f"{name}_missing"] = 1.0 if is_missing else 0.0
        vector[name] = float(medians[name]) if is_missing else float(value)
    return vector
