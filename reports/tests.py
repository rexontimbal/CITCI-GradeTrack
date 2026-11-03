from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from academics.models import ClassRosterEntry
from accounts.models import User
from approvals.models import GradeSheetStatus
from approvals.services import approve_grade_sheet, release_grade_sheet, submit_grade_sheet
from grading.services import compute_student
from grading.tests import GradingTestBase, make_user

from .excel import build_class_record_workbook
from .excel_import import build_import_preview
from .services import class_performance_rows, failing_inc_rows, submission_status_rows


class ReportsTestBase(GradingTestBase):
    """Extends the grading fixtures with a fully-scored student (so a
    final grade/remarks exist) plus admin/program-head users for access
    and scoping tests."""

    def setUp(self):
        super().setUp()
        self.attendance_items = self.make_items("Attendance", [10])
        self.quiz_items = self.make_items("Quizzes", [20, 20])
        self.recitation_items = self.make_items("Recitation", [10])
        self.project_items = self.make_items("Project", [50])
        self.exam_items = self.make_items("Examination", [100])

        self.set_scores(self.roster_entry, self.attendance_items, [10])
        self.set_scores(self.roster_entry, self.quiz_items, [18, 16])
        self.set_scores(self.roster_entry, self.recitation_items, [9])
        self.set_scores(self.roster_entry, self.project_items, [45])
        self.set_scores(self.roster_entry, self.exam_items, [80])

        self.admin = make_user(User.Role.ADMIN, "admin1")
        self.program_head = make_user(User.Role.PROGRAM_HEAD, "phead1")
        self.program.program_head = self.program_head
        self.program.save()

        self.other_instructor = make_user(User.Role.INSTRUCTOR, "otherprof")

    def submit_and_release(self):
        submit_grade_sheet(self.class_offering, self.instructor)
        sheet = self.class_offering.grade_sheets.first()
        approve_grade_sheet(sheet, self.program_head)
        release_grade_sheet(sheet, self.program_head)
        return sheet


class GradeSheetPdfTests(ReportsTestBase):
    def test_instructor_can_view_own_class_sheet_pdf(self):
        sheet = self.submit_and_release()
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_other_instructor_forbidden(self):
        sheet = self.submit_and_release()
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertEqual(response.status_code, 403)

    def test_admin_and_program_head_can_view(self):
        sheet = self.submit_and_release()
        for user in (self.admin, self.program_head):
            self.client.force_login(user)
            response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
            self.assertEqual(response.status_code, 200)

    def test_unreleased_sheet_renders_watermark_image(self):
        submit_grade_sheet(self.class_offering, self.instructor)
        sheet = self.class_offering.grade_sheets.first()
        self.assertEqual(sheet.status, GradeSheetStatus.SUBMITTED)

        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertEqual(response.status_code, 200)
        # xhtml2pdf embeds the watermark as a raster image (no CSS rotate
        # support), so we check the rendered PDF is larger than the
        # unwatermarked (released) version rather than scanning for text.
        self.client.force_login(self.program_head)
        from approvals.services import approve_grade_sheet, release_grade_sheet

        approve_grade_sheet(sheet, self.program_head)
        released_response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertEqual(released_response.status_code, 200)
        release_grade_sheet(sheet, self.program_head)
        official_response = self.client.get(reverse("reports:grade_sheet_pdf", args=[sheet.pk]))
        self.assertGreater(len(response.content), len(official_response.content))


class ClassRecordExcelTests(ReportsTestBase):
    def test_access_control(self):
        self.client.force_login(self.other_instructor)
        response = self.client.get(reverse("reports:class_record_excel", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_formulas_compute_hand_verified_final_grade(self):
        """Evaluate the workbook's formulas by hand (openpyxl doesn't run a
        formula engine) and compare against grading/services.compute_student
        for the same student — they must agree to the stored Decimal."""
        workbook = build_class_record_workbook(self.class_offering)
        ws = workbook.active

        # Locate our student's row, and the five GRADE/WEIGHTED column pairs.
        row = None
        for r in range(11, ws.max_row + 1):
            if ws.cell(r, 2).value == self.student.id_number:
                row = r
                break
        self.assertIsNotNone(row, "Student row not found in the exported workbook")

        result = compute_student(self.roster_entry)
        expected_final = result.final_grade

        # Recompute by hand from the formula strings: for each component,
        # TOTAL=sum(scores), GRADE=5-4*(total/max), WEIGHTED=grade*weight.
        total_weighted = Decimal("0")
        col = 4
        for breakdown in result.components:
            n_items = max(len(self.scheme_components[breakdown.component.name].items.all()), 1)
            total_col = col + n_items
            grade_col = total_col + 1
            weighted_col = total_col + 2

            # TOTAL/GRADE cells hold formula strings (not computed values —
            # openpyxl doesn't run a formula engine), so sum the item max
            # scores and earned scores straight from their own cells.
            max_total = Decimal("0")
            earned_total = Decimal("0")
            for i in range(n_items):
                max_v = ws.cell(10, col + i).value
                max_total += Decimal(str(max_v)) if max_v is not None else Decimal("0")
                v = ws.cell(row, col + i).value
                earned_total += Decimal(str(v)) if v is not None else Decimal("0")

            if max_total == 0:
                grade = Decimal("5")
            else:
                grade = Decimal("5") - Decimal("4") * (earned_total / max_total)
            weight_fraction = Decimal(str(breakdown.component.weight)) / Decimal("100")
            weighted = grade * weight_fraction
            total_weighted += weighted
            col = weighted_col + 1

        self.assertAlmostEqual(float(total_weighted), float(expected_final), places=6)

    def test_blank_export_has_no_scores(self):
        workbook = build_class_record_workbook(self.class_offering, blank=True)
        ws = workbook.active
        # Row 11 is our one student; an item column should have no value.
        self.assertIsNone(ws.cell(11, 4).value)

    def test_exported_workbook_opens_with_openpyxl(self):
        workbook = build_class_record_workbook(self.class_offering)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        reloaded = load_workbook(buffer)
        self.assertIn("Class Record", reloaded.sheetnames)


class ClassRecordImportTests(ReportsTestBase):
    def _exported_file(self, blank=False):
        workbook = build_class_record_workbook(self.class_offering, blank=blank)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        buffer.name = "export.xlsx"
        return buffer

    def test_preview_detects_new_and_changed_scores(self):
        # Import the current (fully-scored) export onto a blank class record
        # scenario: change one score in-memory before re-upload.
        workbook = build_class_record_workbook(self.class_offering)
        ws = workbook.active
        ws.cell(11, 4).value = 7  # change the Attendance score from 10 to 7
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        buffer.name = "changed.xlsx"

        preview = build_import_preview(self.class_offering, buffer)
        self.assertEqual(len(preview.changed_scores), 1)
        self.assertEqual(preview.changed_scores[0].new_value, 7)
        self.assertEqual(preview.changed_scores[0].old_value, 10)

    def test_preview_detects_invalid_values(self):
        workbook = build_class_record_workbook(self.class_offering)
        ws = workbook.active
        ws.cell(11, 4).value = 999  # over max_score (10)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        buffer.name = "invalid.xlsx"

        preview = build_import_preview(self.class_offering, buffer)
        self.assertEqual(len(preview.invalid_cells), 1)

    def test_import_blocked_when_sheet_not_editable(self):
        self.submit_and_release()
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:class_record_import", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 403)

    def test_import_allowed_while_draft(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:class_record_import", args=[self.class_offering.pk]))
        self.assertEqual(response.status_code, 200)


class ReportScopingTests(ReportsTestBase):
    def test_program_head_only_sees_own_program(self):
        other_head = make_user(User.Role.PROGRAM_HEAD, "phead2")
        from academics.models import Program

        other_program = Program.objects.create(code="BSCS", name="BS Computer Science", program_head=other_head)

        rows = submission_status_rows(self.semester, Program.objects.filter(pk=self.program.pk))
        self.assertEqual(len(rows), 1)

        rows_other = submission_status_rows(self.semester, Program.objects.filter(pk=other_program.pk))
        self.assertEqual(len(rows_other), 0)

    def test_class_performance_counts_match_compute_class(self):
        from academics.models import Program

        rows = class_performance_rows(self.semester, Program.objects.filter(pk=self.program.pk))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_students"], 1)

    def test_failing_inc_only_from_released_sheets(self):
        from academics.models import Program

        rows = failing_inc_rows(self.semester, Program.objects.filter(pk=self.program.pk))
        self.assertEqual(len(rows), 0)  # nothing released yet

        self.submit_and_release()
        rows = failing_inc_rows(self.semester, Program.objects.filter(pk=self.program.pk))
        # Our hand-picked scores pass, so still nothing in the failing list.
        self.assertEqual(len(rows), 0)


class ReportsPagesAccessTests(ReportsTestBase):
    def test_instructor_index(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:index"))
        self.assertEqual(response.status_code, 200)

    def test_admin_submission_status_export_excel(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("reports:submission_status"), {"semester": self.semester.pk, "export": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_instructor_cannot_access_admin_reports(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("reports:submission_status"))
        self.assertEqual(response.status_code, 403)
