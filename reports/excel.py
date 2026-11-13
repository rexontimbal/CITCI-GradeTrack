"""Excel exports (openpyxl). The class record export mirrors
grading-system.xlsx's structure (institution header, No./Name, per-
component item columns + TOTAL/GRADE/WEIGHTED, FINAL GRADE, REMARKS) with
real formulas — not pre-computed values — so faculty can open it and
recompute by hand. One deviation from the original sheet: an ID Number
column is added (the real CITCI sheet has none) so a re-imported export
round-trips reliably by ID rather than by fragile name matching alone.
"""

import io

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from academics.models import ClassRosterEntry
from grading.models import ClassGradingScheme, ComponentCategory, Score
from grading.services import item_short_label, ordered_items_by_component

from .models import InstitutionSettings

THIN = Side(style="thin", color="999999")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="E8E8E8")
MAX_ROW_FILL = PatternFill("solid", fgColor="F5F5F5")
FINAL_GRADE_FILL = PatternFill("solid", fgColor="FCE7F3")

# Same category -> color mapping as the Class Record screen's header
# bands (grading.services.COMPONENT_COLOR_CLASSES), as hex fills instead
# of Tailwind classes -- so the exported file looks like the screen.
COMPONENT_FILLS = {
    ComponentCategory.ATTENDANCE: PatternFill("solid", fgColor="FEF3C7"),
    ComponentCategory.QUIZ: PatternFill("solid", fgColor="DBEAFE"),
    ComponentCategory.RECITATION: PatternFill("solid", fgColor="FFEDD5"),
    ComponentCategory.PROJECT: PatternFill("solid", fgColor="CFFAFE"),
    ComponentCategory.EXAM: PatternFill("solid", fgColor="DCFCE7"),
    ComponentCategory.OTHER: HEADER_FILL,
}


def workbook_response(workbook, filename):
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def build_class_record_workbook(class_offering, blank=False):
    inst = InstitutionSettings.get_solo()
    scheme = ClassGradingScheme.get_or_create_default(class_offering)
    components = list(scheme.components.order_by("order", "id"))
    # Same shared term -> date -> creation ordering the Class Record screen
    # uses (grading.services._term_ordered_items_qs) -- the export's column
    # order can never drift from what Setup/the screen show.
    component_items = ordered_items_by_component(scheme)

    wb = Workbook()
    ws = wb.active
    ws.title = "Class Record"

    # --- Column layout: A=No. B=ID Number C=Name, then per component
    # [items..., TOTAL, GRADE, WEIGHTED], then FINAL GRADE, REMARKS. ---
    col = 4
    component_ranges = []
    for component in components:
        items = component_items.get(component.id, [])
        first_item_col = col
        last_item_col = first_item_col + max(len(items), 1) - 1
        total_col, grade_col, weighted_col = last_item_col + 1, last_item_col + 2, last_item_col + 3
        component_ranges.append((component, items, first_item_col, last_item_col, total_col, grade_col, weighted_col))
        col = weighted_col + 1
    final_grade_col = col
    remarks_col = col + 1
    last_col = remarks_col

    def merged(row, start_col, end_col, value, bold=False, size=None):
        ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
        cell = ws.cell(row, start_col, value)
        cell.alignment = Alignment(horizontal="center")
        if bold:
            cell.font = Font(bold=True, size=size or 11)
        return cell

    merged(1, 1, last_col, inst.school_name, bold=True, size=14)
    if inst.sub_line:
        merged(2, 1, last_col, inst.sub_line)
    if inst.address:
        merged(3, 1, last_col, inst.address)

    section_names = ", ".join(str(s) for s in class_offering.sections.all())
    merged(5, 1, last_col, f"CLASS RECORD: {class_offering.subject.code} · {class_offering.subject.title}", bold=True, size=12)
    instructor_name = class_offering.instructor.full_name if class_offering.instructor else "Unassigned"
    merged(6, 1, last_col, f"{section_names} · {class_offering.semester} · Instructor: {instructor_name}")

    header_row1, header_row2, max_row, first_data_row = 8, 9, 10, 11

    def header_cell(row1, row2, col_start, col_end, value):
        ws.merge_cells(start_row=row1, start_column=col_start, end_row=row2, end_column=col_end)
        cell = ws.cell(row1, col_start, value)
        return cell

    header_cell(header_row1, header_row2, 1, 1, "No.")
    header_cell(header_row1, header_row2, 2, 2, "ID Number")
    header_cell(header_row1, header_row2, 3, 3, "Name of Students")
    ws.cell(max_row, 3, "MAX SCORE")

    component_fills = {}
    for component, items, first_item_col, last_item_col, total_col, grade_col, weighted_col in component_ranges:
        ws.merge_cells(start_row=header_row1, start_column=first_item_col, end_row=header_row1, end_column=weighted_col)
        ws.cell(header_row1, first_item_col, f"{component.name} ({component.weight}%)")
        fill = COMPONENT_FILLS.get(component.category, HEADER_FILL)
        for c in range(first_item_col, weighted_col + 1):
            component_fills[c] = fill

        if items:
            for i, item in enumerate(items):
                label_cell = ws.cell(header_row2, first_item_col + i, item_short_label(component, item, i + 1))
                label_cell.comment = Comment(
                    f"{item.title} · {item.get_term_display()}" + (f" · {item.date}" if item.date else ""),
                    "CITCI GradeTrack",
                )
                ws.cell(max_row, first_item_col + i, float(item.max_score))
            item_range = f"{get_column_letter(first_item_col)}{max_row}:{get_column_letter(last_item_col)}{max_row}"
            ws.cell(max_row, total_col, f"=SUM({item_range})")
        else:
            ws.cell(header_row2, first_item_col, "(no items)")
            ws.cell(max_row, total_col, 0)

        ws.cell(header_row2, total_col, "TOTAL")
        ws.cell(header_row2, grade_col, "GRADE")
        ws.cell(header_row2, weighted_col, "WEIGHTED")

    header_cell(header_row1, header_row2, final_grade_col, final_grade_col, "FINAL GRADE")
    header_cell(header_row1, header_row2, remarks_col, remarks_col, "REMARKS")

    component_fills[final_grade_col] = FINAL_GRADE_FILL

    for row in (header_row1, header_row2, max_row):
        for c in range(1, last_col + 1):
            cell = ws.cell(row, c)
            cell.font = Font(bold=(row != max_row))
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if row == max_row:
                cell.fill = MAX_ROW_FILL
            else:
                cell.fill = component_fills.get(c, HEADER_FILL)
            cell.border = BORDER

    # --- Student rows ---
    roster_entries = list(
        class_offering.roster_entries.select_related("student").order_by(
            "status", "student__last_name", "student__first_name"
        )
    )
    scores_lookup = {}
    if not blank:
        item_ids = [item.id for items in component_items.values() for item in items]
        if item_ids:
            for s in Score.objects.filter(roster_entry__class_offering=class_offering, item_id__in=item_ids):
                scores_lookup[(s.roster_entry_id, s.item_id)] = s.score

    row_num = first_data_row
    for idx, entry in enumerate(roster_entries, start=1):
        ws.cell(row_num, 1, idx)
        ws.cell(row_num, 2, entry.student.id_number or "")
        middle_initial = f" {entry.student.middle_name[0]}." if entry.student.middle_name else ""
        ws.cell(row_num, 3, f"{entry.student.last_name}, {entry.student.first_name}{middle_initial}")

        weighted_refs = []
        for component, items, first_item_col, last_item_col, total_col, grade_col, weighted_col in component_ranges:
            for i, item in enumerate(items):
                value = scores_lookup.get((entry.id, item.id))
                if value is not None:
                    ws.cell(row_num, first_item_col + i, float(value))

            max_total_ref = f"${get_column_letter(total_col)}${max_row}"
            if items:
                item_range = f"{get_column_letter(first_item_col)}{row_num}:{get_column_letter(last_item_col)}{row_num}"
                ws.cell(row_num, total_col, f"=SUM({item_range})")
            else:
                ws.cell(row_num, total_col, 0)

            total_ref = f"{get_column_letter(total_col)}{row_num}"
            ws.cell(row_num, grade_col, f"=IF({max_total_ref}=0,5,5-4*({total_ref}/{max_total_ref}))")

            grade_ref = f"{get_column_letter(grade_col)}{row_num}"
            weight_fraction = float(component.weight) / 100
            ws.cell(row_num, weighted_col, f"={grade_ref}*{weight_fraction}")
            weighted_refs.append(f"{get_column_letter(weighted_col)}{row_num}")

        if weighted_refs:
            ws.cell(row_num, final_grade_col, f"=SUM({','.join(weighted_refs)})")
        else:
            ws.cell(row_num, final_grade_col, 0)

        if entry.status == ClassRosterEntry.Status.DROPPED:
            ws.cell(row_num, remarks_col, "DROPPED")
        elif entry.is_incomplete:
            ws.cell(row_num, remarks_col, "INC")
        else:
            final_ref = f"{get_column_letter(final_grade_col)}{row_num}"
            ws.cell(row_num, remarks_col, f'=IF({final_ref}<=3,"PASSED","FAILED")')

        for c in range(1, last_col + 1):
            cell = ws.cell(row_num, c)
            cell.border = BORDER
            if c >= 4:
                cell.alignment = Alignment(horizontal="center")
            grade_cols = {gc for _, _, _, _, _, gc, _ in component_ranges}
            if c in grade_cols or c == final_grade_col:
                cell.number_format = "0.00"
        row_num += 1

    ws.freeze_panes = ws.cell(first_data_row, 4).coordinate
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 26
    for c in range(4, last_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = 9

    return wb


def build_submission_status_workbook(semester, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Submission Status"
    ws.append(["Class", "Instructor", "Status", "Submitted", "Approved", "Released"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    for row in rows:
        ws.append(
            [
                str(row["class_offering"]),
                row["instructor"].full_name if row["instructor"] else "Unassigned",
                row["status_display"],
                row["submitted_at"].strftime("%Y-%m-%d %H:%M") if row["submitted_at"] else "",
                row["approved_at"].strftime("%Y-%m-%d %H:%M") if row["approved_at"] else "",
                row["released_at"].strftime("%Y-%m-%d %H:%M") if row["released_at"] else "",
            ]
        )
    for col, width in zip("ABCDEF", [42, 24, 14, 18, 18, 18]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    return wb


def build_class_performance_workbook(semester, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Class Performance"
    ws.append(["Class", "Students", "Passed", "Failed", "INC", "Dropped", "Average", "Pass Rate %"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    for row in rows:
        ws.append(
            [
                str(row["class_offering"]),
                row["total_students"],
                row["counts"]["PASSED"],
                row["counts"]["FAILED"],
                row["counts"]["INC"],
                row["counts"]["DROPPED"],
                float(row["average"]) if row["average"] is not None else None,
                float(row["pass_rate"]) if row["pass_rate"] is not None else None,
            ]
        )
    for col, width in zip("ABCDEFGH", [42, 10, 10, 10, 8, 10, 10, 12]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    return wb


def build_failing_inc_workbook(semester, entries):
    wb = Workbook()
    ws = wb.active
    ws.title = "Failing-INC"
    ws.append(["Student", "Program", "Major", "Year", "Subject", "Grade", "Remarks", "Instructor"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    from academics.models import SectionMembership

    for entry in entries:
        student = entry.roster_entry.student
        profile = getattr(student, "student_profile", None)
        class_offering = entry.sheet.class_offering
        membership = SectionMembership.objects.filter(student=student, semester=class_offering.semester).select_related("section").first()
        ws.append(
            [
                student.full_name,
                profile.program.code if profile and profile.program else "",
                profile.major.code if profile and profile.major else "",
                membership.section.get_year_level_display() if membership else "",
                class_offering.subject.code,
                float(entry.final_grade) if entry.final_grade is not None else None,
                entry.get_remarks_display(),
                class_offering.instructor.full_name if class_offering.instructor else "",
            ]
        )
    for col, width in zip("ABCDEFGH", [28, 10, 10, 10, 12, 10, 10, 24]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    return wb
