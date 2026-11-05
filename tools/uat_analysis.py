#!/usr/bin/env python
"""Phase 8 part B — analyzes UAT response data (docs/UAT_QUESTIONNAIRE.md /
docs/uat/*.csv item bank) into per-item and per-characteristic statistics,
overall group means, and a one-way ANOVA between respondent groups.

Input: a CSV with one row per respondent. Columns: `role` (one of Student /
Staff / ITExpert — matching which questionnaire version they took) plus one
column per item code they answered (e.g. FS1, FS2, PE1, ...), values 1-5.
Blank cells (an item not on that respondent's version) are treated as not
answered. See docs/uat/sample_responses.csv for the exact shape.

Output: an .xlsx workbook (formatted per-item and per-characteristic tables,
one sheet per group plus a combined/ANOVA sheet) and a Markdown summary
ready to paste into Chapter 4.

Usage:
    python tools/uat_analysis.py docs/uat/sample_responses.csv \\
        --xlsx docs/uat/analysis.xlsx --md docs/uat/analysis.md
"""

import argparse
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_uat_docs import CHAR_NAMES, IT_EXPERTS, STAFF, STUDENTS, items_with_codes  # noqa: E402

VERSION_ITEM_BANKS = {"Student": STUDENTS, "Staff": STAFF, "ITExpert": IT_EXPERTS}

INTERPRETATION_BANDS = [
    (4.21, 5.00, "Excellent"),
    (3.41, 4.20, "Very Good"),
    (2.61, 3.40, "Good"),
    (1.81, 2.60, "Fair"),
    (1.00, 1.80, "Poor"),
]


def interpret(mean):
    if mean is None:
        return "N/A"
    for low, high, label in INTERPRETATION_BANDS:
        if low <= mean <= high:
            return label
    return "N/A"


def read_responses(path):
    """Returns {role: [{item_code: int-or-None, ...}, ...]}."""
    by_role = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            role = row.get("role", "").strip()
            if not role:
                continue
            values = {}
            for key, value in row.items():
                if key == "role":
                    continue
                value = (value or "").strip()
                values[key] = int(value) if value.isdigit() else None
            by_role.setdefault(role, []).append(values)
    return by_role


def item_stats(responses, item_code):
    """responses: list of {item_code: value-or-None}. Returns (mean, sd, n,
    distribution {1..5: count}) or (None, None, 0, {}) if nobody answered."""
    values = [r[item_code] for r in responses if r.get(item_code) is not None]
    if not values:
        return None, None, 0, {}
    mean = statistics.mean(values)
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    distribution = {k: values.count(k) for k in range(1, 6)}
    return mean, sd, len(values), distribution


def characteristic_stats(responses, char_code, item_bank):
    """Mean of the characteristic's item means (equal-weighted across
    items, standard practice for a Likert sub-scale)."""
    item_codes = [code for code, c, _text in items_with_codes(item_bank) if c == char_code]
    item_means = []
    for code in item_codes:
        mean, _sd, n, _dist = item_stats(responses, code)
        if mean is not None and n > 0:
            item_means.append(mean)
    if not item_means:
        return None
    return statistics.mean(item_means)


def one_way_anova(groups):
    """groups: {label: [values]}. Returns (F, p) or None if scipy isn't
    installed or fewer than 2 groups have data."""
    try:
        from scipy import stats as scipy_stats
    except ImportError:
        return None
    samples = [values for values in groups.values() if len(values) >= 2]
    if len(samples) < 2:
        return None
    result = scipy_stats.f_oneway(*samples)
    return float(result.statistic), float(result.pvalue)


def analyze(by_role):
    """Returns a report dict: per-role per-item stats, per-role
    per-characteristic stats + overall mean, and an ANOVA per
    characteristic shared by 2+ roles."""
    report = {"roles": {}, "anova": {}}

    for role, responses in by_role.items():
        item_bank = VERSION_ITEM_BANKS.get(role, {})
        item_rows = []
        for code, char_code, text in items_with_codes(item_bank):
            mean, sd, n, distribution = item_stats(responses, code)
            item_rows.append(
                {
                    "code": code,
                    "characteristic": char_code,
                    "text": text,
                    "mean": mean,
                    "sd": sd,
                    "n": n,
                    "distribution": distribution,
                    "interpretation": interpret(mean),
                }
            )

        char_rows = []
        char_means = []
        for char_code in item_bank:
            mean = characteristic_stats(responses, char_code, item_bank)
            if mean is not None:
                char_means.append(mean)
            char_rows.append({"characteristic": char_code, "name": CHAR_NAMES[char_code], "mean": mean, "interpretation": interpret(mean)})

        overall_mean = statistics.mean(char_means) if char_means else None
        report["roles"][role] = {
            "n_respondents": len(responses),
            "items": item_rows,
            "characteristics": char_rows,
            "overall_mean": overall_mean,
            "overall_interpretation": interpret(overall_mean),
        }

    # ANOVA per characteristic shared by 2+ roles that answered it.
    all_chars = set()
    for item_bank in VERSION_ITEM_BANKS.values():
        all_chars.update(item_bank.keys())

    for char_code in sorted(all_chars):
        groups = {}
        for role, responses in by_role.items():
            item_bank = VERSION_ITEM_BANKS.get(role, {})
            if char_code not in item_bank:
                continue
            item_codes = [code for code, c, _t in items_with_codes(item_bank) if c == char_code]
            per_respondent_means = []
            for r in responses:
                vals = [r[code] for code in item_codes if r.get(code) is not None]
                if vals:
                    per_respondent_means.append(statistics.mean(vals))
            if per_respondent_means:
                groups[role] = per_respondent_means
        if len(groups) >= 2:
            result = one_way_anova(groups)
            report["anova"][char_code] = {"groups": {k: len(v) for k, v in groups.items()}, "result": result}

    return report


def write_markdown(report, path):
    lines = ["# UAT Analysis Summary", ""]
    for role, data in report["roles"].items():
        lines.append(f"## {role} (n={data['n_respondents']})")
        lines.append("")
        lines.append("| Characteristic | Weighted Mean | Interpretation |")
        lines.append("|---|---|---|")
        for row in data["characteristics"]:
            mean_display = f"{row['mean']:.2f}" if row["mean"] is not None else "N/A"
            lines.append(f"| {row['name']} | {mean_display} | {row['interpretation']} |")
        overall = f"{data['overall_mean']:.2f}" if data["overall_mean"] is not None else "N/A"
        lines.append(f"| **Overall** | **{overall}** | **{data['overall_interpretation']}** |")
        lines.append("")

    lines.append("## One-way ANOVA between respondent groups (α = 0.05)")
    lines.append("")
    lines.append("| Characteristic | Groups (n) | F | p | Conclusion |")
    lines.append("|---|---|---|---|---|")
    for char_code, entry in report["anova"].items():
        groups_display = ", ".join(f"{k} (n={v})" for k, v in entry["groups"].items())
        result = entry["result"]
        if result is None:
            lines.append(f"| {CHAR_NAMES[char_code]} | {groups_display} | N/A | N/A | scipy not installed or insufficient data |")
            continue
        f_stat, p_value = result
        conclusion = (
            "Statistically significant difference between groups"
            if p_value < 0.05
            else "No statistically significant difference between groups"
        )
        lines.append(f"| {CHAR_NAMES[char_code]} | {groups_display} | {f_stat:.3f} | {p_value:.4f} | {conclusion} |")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_xlsx(report, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.remove(wb.active)

    for role, data in report["roles"].items():
        ws = wb.create_sheet(role[:31])
        ws.append([f"{role} — n={data['n_respondents']}"])
        ws["A1"].font = Font(bold=True, size=14)
        ws.append([])
        ws.append(["Item Code", "Characteristic", "Item Text", "Mean", "SD", "n", "1", "2", "3", "4", "5", "Interpretation"])
        for cell in ws[3]:
            cell.font = Font(bold=True)
        for row in data["items"]:
            dist = row["distribution"]
            ws.append(
                [
                    row["code"],
                    CHAR_NAMES.get(row["characteristic"], row["characteristic"]),
                    row["text"],
                    round(row["mean"], 2) if row["mean"] is not None else None,
                    round(row["sd"], 2) if row["sd"] is not None else None,
                    row["n"],
                    dist.get(1, 0),
                    dist.get(2, 0),
                    dist.get(3, 0),
                    dist.get(4, 0),
                    dist.get(5, 0),
                    row["interpretation"],
                ]
            )
        ws.append([])
        ws.append(["Characteristic", "Weighted Mean", "Interpretation"])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
        for row in data["characteristics"]:
            ws.append([row["name"], round(row["mean"], 2) if row["mean"] is not None else None, row["interpretation"]])
        ws.append(["Overall", round(data["overall_mean"], 2) if data["overall_mean"] is not None else None, data["overall_interpretation"]])
        ws.column_dimensions["C"].width = 60

    ws = wb.create_sheet("ANOVA")
    ws.append(["Characteristic", "Groups (n)", "F", "p", "Conclusion"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for char_code, entry in report["anova"].items():
        groups_display = ", ".join(f"{k} (n={v})" for k, v in entry["groups"].items())
        result = entry["result"]
        if result is None:
            ws.append([CHAR_NAMES[char_code], groups_display, None, None, "scipy not installed or insufficient data"])
            continue
        f_stat, p_value = result
        conclusion = (
            "Statistically significant difference between groups"
            if p_value < 0.05
            else "No statistically significant difference between groups"
        )
        ws.append([CHAR_NAMES[char_code], groups_display, round(f_stat, 3), round(p_value, 4), conclusion])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["E"].width = 50

    wb.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("responses_csv")
    parser.add_argument("--xlsx", default="docs/uat/analysis.xlsx")
    parser.add_argument("--md", default="docs/uat/analysis.md")
    args = parser.parse_args()

    by_role = read_responses(args.responses_csv)
    if not by_role:
        print("No responses found in the CSV (expected a 'role' column).", file=sys.stderr)
        return 1

    report = analyze(by_role)
    write_markdown(report, args.md)
    print(f"Wrote {args.md}")
    write_xlsx(report, args.xlsx)
    print(f"Wrote {args.xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
