from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from grading.models import AssessmentItem, AssessmentTerm, Score
from grading.tests import GradingTestBase, make_user

from .models import Notification
from .services import notify, notify_many


class NotifyServiceTests(TestCase):
    def setUp(self):
        self.user = make_user(User.Role.INSTRUCTOR, "notify_target")

    def test_notify_creates_a_notification(self):
        n = notify(self.user, "Title", message="Body", link="/somewhere/")
        self.assertEqual(n.recipient, self.user)
        self.assertEqual(n.title, "Title")
        self.assertEqual(n.message, "Body")
        self.assertEqual(n.link, "/somewhere/")
        self.assertFalse(n.is_read)

    def test_notify_is_a_noop_for_none_recipient(self):
        """A class's unset instructor FK is None — callers must be able to
        pass that through without a crash."""
        self.assertIsNone(notify(None, "Title"))
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_many_skips_none_recipients_but_creates_the_rest(self):
        other = make_user(User.Role.INSTRUCTOR, "notify_target_2")
        results = notify_many([self.user, None, other], "Batch title")
        self.assertEqual(len(results), 2)
        self.assertEqual(Notification.objects.filter(title="Batch title").count(), 2)


class BellAndNotificationsViewTests(TestCase):
    def setUp(self):
        self.user = make_user(User.Role.INSTRUCTOR, "bell_user")
        self.other_user = make_user(User.Role.INSTRUCTOR, "bell_other")
        self.client.force_login(self.user)

    def test_bell_shows_only_the_logged_in_users_notifications_and_unread_count(self):
        notify(self.user, "Mine, unread")
        read_one = notify(self.user, "Mine, read")
        read_one.is_read = True
        read_one.save(update_fields=["is_read"])
        notify(self.other_user, "Not mine")

        response = self.client.get(reverse("dashboard:bell"))
        self.assertContains(response, "Mine, unread")
        self.assertContains(response, "Mine, read")
        self.assertNotContains(response, "Not mine")
        self.assertEqual(response.context["unread_count"], 1)

    def test_mark_read_marks_the_notification_and_redirects_to_its_link(self):
        n = notify(self.user, "Go here", link="/grading/my-grades/")
        response = self.client.get(reverse("dashboard:mark_read", args=[n.pk]))
        self.assertRedirects(response, "/grading/my-grades/", fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_mark_read_with_no_link_redirects_to_dashboard_home(self):
        n = notify(self.user, "No link")
        response = self.client.get(reverse("dashboard:mark_read", args=[n.pk]))
        self.assertRedirects(response, reverse("dashboard:home"), fetch_redirect_response=False)

    def test_mark_read_404s_for_someone_elses_notification(self):
        n = notify(self.other_user, "Not mine")
        response = self.client.get(reverse("dashboard:mark_read", args=[n.pk]))
        self.assertEqual(response.status_code, 404)
        n.refresh_from_db()
        self.assertFalse(n.is_read)

    def test_mark_all_read_bell_fragment_marks_only_own_notifications(self):
        mine = notify(self.user, "Mine")
        theirs = notify(self.other_user, "Theirs")
        response = self.client.get(reverse("dashboard:mark_all_read"))
        self.assertEqual(response.status_code, 200)
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertTrue(mine.is_read)
        self.assertFalse(theirs.is_read)

    def test_notifications_page_lists_own_notifications(self):
        notify(self.user, "On the list page")
        notify(self.other_user, "Not on the list page")
        response = self.client.get(reverse("dashboard:notifications"))
        self.assertContains(response, "On the list page")
        self.assertNotContains(response, "Not on the list page")

    def test_notifications_mark_all_read_redirects_to_notifications_page(self):
        n = notify(self.user, "Unread")
        response = self.client.get(reverse("dashboard:notifications_mark_all_read"))
        self.assertRedirects(response, reverse("dashboard:notifications"))
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_bell_and_notifications_require_login(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard:bell"))
        self.assertNotEqual(response.status_code, 200)


class DashboardHomeRoutingTests(GradingTestBase):
    """home() dispatches to a different template per role — one smoke test
    per role confirms the right page renders with no server error, plus the
    student dashboard's forecast/warning computations (the most complex
    branch) with real data."""

    def test_admin_sees_admin_dashboard(self):
        admin = make_user(User.Role.ADMIN, "dash_admin")
        self.client.force_login(admin)
        response = self.client.get(reverse("dashboard:home"))
        self.assertTemplateUsed(response, "dashboard/admin_dashboard.html")
        self.assertIn("total_students", response.context)

    def test_program_head_sees_program_head_dashboard(self):
        head = make_user(User.Role.PROGRAM_HEAD, "dash_head")
        self.program.program_head = head
        self.program.save()
        self.client.force_login(head)
        response = self.client.get(reverse("dashboard:home"))
        self.assertTemplateUsed(response, "dashboard/program_head_dashboard.html")

    def test_instructor_sees_instructor_dashboard_with_class_and_student_counts(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("dashboard:home"))
        self.assertTemplateUsed(response, "dashboard/instructor_dashboard.html")
        self.assertEqual(response.context["my_classes_count"], 1)
        self.assertEqual(response.context["total_students"], 1)

    def test_student_sees_student_dashboard_with_a_subject_card(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        self.assertTemplateUsed(response, "dashboard/student_dashboard.html")
        self.assertEqual(response.context["subjects_count"], 1)
        self.assertEqual(len(response.context["cards"]), 1)

    def test_student_dashboard_warns_on_a_failing_running_grade(self):
        from grading.models import AssessmentTerm

        items = self.make_items("Examination", [20], term=AssessmentTerm.MIDTERM)
        self.set_scores(self.roster_entry, items, [2])  # deep in failing territory
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.context["warnings_count"], 1)


class DashboardQueryCountTests(GradingTestBase):
    """Phase 8 part B dashboard query-count pass. Before this pass the
    student dashboard issued ~10-12 queries PER subject (released_entry,
    item/score counts, the unofficial running grade, the forecast card —
    each computed with its own single-entry service call in a loop) — 111
    queries measured against the real seeded demo data (9 subjects). This
    fixture builds a comparably-shaped multi-subject student and asserts
    the page stays flat regardless of subject count."""

    EXTRA_SUBJECTS = 5

    def setUp(self):
        super().setUp()
        from academics.models import ClassOffering, ClassRosterEntry, Subject
        from grading.models import ClassGradingScheme

        self.extra_entries = []
        for i in range(self.EXTRA_SUBJECTS):
            subject = Subject.objects.create(
                code=f"QC{i}", title=f"Query Count Subject {i}", units=Decimal("3.0"), term=self.semester.term
            )
            class_offering = ClassOffering.objects.create(subject=subject, semester=self.semester, instructor=self.instructor)
            class_offering.sections.set([self.section])
            scheme = ClassGradingScheme.get_or_create_default(class_offering)
            scheme_components = {sc.name: sc for sc in scheme.components.all()}

            entry = ClassRosterEntry.objects.create(student=self.student, class_offering=class_offering)
            item = AssessmentItem.objects.create(
                class_offering=class_offering,
                component=scheme_components["Examination"],
                title="Midterm Exam",
                max_score=20,
                term=AssessmentTerm.MIDTERM,
                order=0,
            )
            Score.objects.update_or_create(roster_entry=entry, item=item, defaults={"score": 15 + i % 5})
            self.extra_entries.append(entry)

    def test_student_dashboard_query_count_stays_flat(self):
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(queries), 45, f"Student dashboard issued {len(queries)} queries for {len(self.extra_entries) + 1} subjects."
        )

    def test_my_grades_query_count_stays_flat(self):
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("grading:my_grades"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 35)

    def test_my_progress_query_count_stays_flat(self):
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("grading:my_progress"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 40)

    def test_subject_detail_query_count(self):
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("grading:subject_detail", args=[self.roster_entry.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 35)

    def test_instructor_dashboard_query_count(self):
        self.client.force_login(self.instructor)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 15)

    def test_program_head_dashboard_query_count_stays_flat(self):
        from accounts.models import User as _User

        head = make_user(_User.Role.PROGRAM_HEAD, "qc_program_head")
        self.program.program_head = head
        self.program.save()

        self.client.force_login(head)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(queries), 25, f"Program Head dashboard issued {len(queries)} queries for {len(self.extra_entries) + 1} classes."
        )
