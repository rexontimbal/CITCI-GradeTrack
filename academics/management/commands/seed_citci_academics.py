import json
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.management.guards import add_force_demo_argument, ensure_demo_allowed
from academics.models import (
    AcademicYear,
    ClassOffering,
    ClassRosterEntry,
    Major,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
    Term,
)

DEMO_PASSWORD = "Demo@1234"

# The existing demo `instructor` login is repurposed to represent this real
# instructor, so the instructor-role demo shows real classes/students.
DEMO_INSTRUCTOR_NAME = "Mr. Honrejas"

FIRST_NAMES = [
    "Juan", "Maria", "Jose", "Angela", "Mark", "Kristine", "Paolo", "Camille",
    "Ronnel", "Jasmine", "Christian", "Angelica", "Michael", "Shaira", "Jerome",
]
LAST_NAMES = [
    "Dela Cruz", "Santos", "Reyes", "Bautista", "Gonzales", "Ramos", "Mendoza",
    "Torres", "Flores", "Villanueva", "Castillo", "Garcia", "Aquino", "Pascual", "Marquez",
]

STUDENTS_PER_SECTION = 10


def slugify_username(instructor_name, taken):
    """username from surname, e.g. 'Mr. Garibay' -> 'garibay' (or 'garibay2'
    if that's already taken by a different person)."""
    surname = instructor_name.split()[-1]
    base = re.sub(r"[^a-z0-9]", "", surname.lower()) or "instructor"
    username = base
    n = 2
    while username in taken:
        username = f"{base}{n}"
        n += 1
    taken.add(username)
    return username


class Command(BaseCommand):
    help = (
        "Seeds real CITCI A.Y. 2026-2027 BSED/TCP offerings from "
        "docs/source/citci_offerings_2026_2027.json (run import_offerings_docx first). Idempotent."
    )

    def add_arguments(self, parser):
        add_force_demo_argument(parser)

    def handle(self, *args, **options):
        ensure_demo_allowed(options.get("force_demo"))
        force_demo = options.get("force_demo")
        json_path = Path(settings.BASE_DIR) / "docs" / "source" / "citci_offerings_2026_2027.json"
        if not json_path.exists():
            raise CommandError(
                f"{json_path} not found. Run "
                "`python manage.py import_offerings_docx docs/source/all_subject_per_major.docx` first."
            )
        classes_data = json.loads(json_path.read_text(encoding="utf-8"))

        academic_year, first_sem, second_sem = self._seed_terms()
        program_head = User.objects.filter(username="program_head").first()
        bsed, tcp = self._seed_programs(program_head)
        eng_major, ss_major = self._seed_majors(bsed)
        sections = self._seed_sections(bsed, tcp, eng_major, ss_major, academic_year)
        instructors = self._seed_instructors(classes_data)
        subjects = self._seed_subjects(classes_data, bsed, eng_major, ss_major)
        classes = self._seed_classes(classes_data, subjects, sections, instructors, first_sem, second_sem)
        students = self._seed_students(bsed, tcp, eng_major, ss_major, sections)
        self._seed_rosters(students, sections, classes)
        call_command("seed_grading_demo", force_demo=force_demo)
        call_command("seed_student_portal_demo", force_demo=force_demo)
        call_command("seed_forecasting_demo", force_demo=force_demo)

        self.stdout.write(self.style.SUCCESS("\nCITCI academic data ready."))

    def _seed_terms(self):
        academic_year, _ = AcademicYear.objects.get_or_create(start_year=2026)
        first_sem, _ = Semester.objects.get_or_create(
            academic_year=academic_year, term=Term.FIRST, defaults={"is_active": True}
        )
        if not first_sem.is_active:
            first_sem.is_active = True
            first_sem.save()
        second_sem, _ = Semester.objects.get_or_create(academic_year=academic_year, term=Term.SECOND)
        self.stdout.write(self.style.SUCCESS(f"Academic year + semesters ready ({academic_year})."))
        return academic_year, first_sem, second_sem

    def _seed_programs(self, program_head):
        bsed, _ = Program.objects.update_or_create(
            code="BSED",
            defaults={"name": "Bachelor of Secondary Education", "program_head": program_head},
        )
        tcp, _ = Program.objects.update_or_create(
            code="TCP", defaults={"name": "Teacher Certificate Program", "program_head": program_head}
        )
        self.stdout.write(self.style.SUCCESS("Programs ready (BSED, TCP), both headed by the demo program head."))
        return bsed, tcp

    def _seed_majors(self, bsed):
        eng, _ = Major.objects.get_or_create(program=bsed, code="ENG", defaults={"name": "English"})
        ss, _ = Major.objects.get_or_create(program=bsed, code="SS", defaults={"name": "Social Studies"})
        self.stdout.write(self.style.SUCCESS("Majors ready (BSED-ENG, BSED-SS)."))
        return eng, ss

    def _seed_sections(self, bsed, tcp, eng_major, ss_major, academic_year):
        sections = {}
        for major, major_key in ((eng_major, "English"), (ss_major, "Social Studies")):
            for year in range(1, 5):
                section, _ = Section.objects.get_or_create(
                    program=bsed, major=major, academic_year=academic_year, year_level=year, name=""
                )
                sections[(bsed.code, major_key, year)] = section
        tcp_section, _ = Section.objects.get_or_create(
            program=tcp, major=None, academic_year=academic_year, year_level=None, name=""
        )
        sections[("TCP", None, None)] = tcp_section
        self.stdout.write(self.style.SUCCESS(f"{len(sections)} sections ready (BSED-ENG/SS 1-4, TCP)."))
        return sections

    def _seed_instructors(self, classes_data):
        names = sorted({c["instructor"] for c in classes_data if c["instructor"]})
        taken_usernames = set(User.objects.values_list("username", flat=True))
        mapping = {}

        demo_instructor = User.objects.filter(username="instructor").first()
        if demo_instructor and DEMO_INSTRUCTOR_NAME in names:
            demo_instructor.last_name = DEMO_INSTRUCTOR_NAME
            demo_instructor.first_name = ""
            demo_instructor.must_change_password = False
            demo_instructor.save()
            mapping[DEMO_INSTRUCTOR_NAME] = demo_instructor
            taken_usernames.discard("instructor")  # it's already taken by itself, fine either way

        for name in names:
            if name in mapping:
                continue

            # Match an instructor already seeded by a previous run before
            # generating a new username — otherwise re-running this command
            # creates suffixed duplicates (garibay2, garibay3, ...) instead
            # of reusing the account from the last run.
            existing = (
                User.objects.filter(role=User.Role.INSTRUCTOR, first_name="", last_name=name)
                .exclude(username="instructor")
                .first()
            )
            if existing:
                mapping[name] = existing
                continue

            username = slugify_username(name, taken_usernames)
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": "",
                    "last_name": name,
                    "role": User.Role.INSTRUCTOR,
                    "is_active": True,
                    "must_change_password": False,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            mapping[name] = user

        self.stdout.write(self.style.SUCCESS(f"{len(mapping)} instructor accounts ready (password {DEMO_PASSWORD})."))
        return mapping

    def _seed_subjects(self, classes_data, bsed, eng_major, ss_major):
        subjects = {}
        for c in classes_data:
            code = c["code"]
            if code in subjects:
                continue
            code_upper = code.upper()
            if code_upper.startswith("EL"):
                program, major = bsed, eng_major
            elif code_upper.startswith("SSE"):
                program, major = bsed, ss_major
            else:
                program, major = None, None

            year_level = next((s["year_level"] for s in c["sections"] if s["year_level"]), None)
            term = Term.FIRST if c["semester"] == "FIRST" else Term.SECOND

            try:
                units = Decimal(c["units"])
            except Exception:
                units = Decimal("3.0")

            subject, _ = Subject.objects.update_or_create(
                code=code,
                defaults={
                    "title": c["description"] or code,
                    "units": units,
                    "program": program,
                    "major": major,
                    "year_level": year_level,
                    "term": term,
                },
            )
            subjects[code] = subject
        self.stdout.write(self.style.SUCCESS(f"{len(subjects)} subjects ready."))
        return subjects

    def _seed_classes(self, classes_data, subjects, sections, instructors, first_sem, second_sem):
        created_classes = []
        for c in classes_data:
            subject = subjects[c["code"]]
            semester = first_sem if c["semester"] == "FIRST" else second_sem
            instructor = instructors.get(c["instructor"])

            class_offering = ClassOffering.objects.filter(
                subject=subject, semester=semester, room=c["room"], schedule=c["schedule"]
            ).first()
            if class_offering is None:
                class_offering = ClassOffering.objects.create(
                    subject=subject, semester=semester, instructor=instructor, room=c["room"], schedule=c["schedule"]
                )
            else:
                class_offering.instructor = instructor
                class_offering.save(update_fields=["instructor"])

            section_objs = []
            for s in c["sections"]:
                key = ("TCP", None, None) if s["program"] == "TCP" else (s["program"], s["major"], s["year_level"])
                section = sections.get(key)
                if section:
                    section_objs.append(section)
            class_offering.sections.set(section_objs)
            created_classes.append(class_offering)

        self.stdout.write(self.style.SUCCESS(f"{len(created_classes)} classes ready."))
        return created_classes

    def _seed_students(self, bsed, tcp, eng_major, ss_major, sections):
        students_by_section = {}
        counter = 1

        existing_student = User.objects.filter(username="student").first()
        eng1 = sections[(bsed.code, "English", 1)]
        if existing_student:
            existing_student.must_change_password = False
            existing_student.save(update_fields=["must_change_password"])
            StudentProfile.objects.update_or_create(
                user=existing_student,
                defaults={"program": bsed, "major": eng_major, "year_level": 1, "section": eng1},
            )
            students_by_section.setdefault(eng1.pk, []).append(existing_student)

        section_list = [sections[(bsed.code, "English", y)] for y in range(1, 5)]
        section_list += [sections[(bsed.code, "Social Studies", y)] for y in range(1, 5)]
        section_list += [sections[("TCP", None, None)]]

        for section in section_list:
            for _ in range(STUDENTS_PER_SECTION):
                first = FIRST_NAMES[(counter - 1) % len(FIRST_NAMES)]
                last = LAST_NAMES[((counter - 1) * 4) % len(LAST_NAMES)]  # coprime step for more variety
                username = f"student{counter:03d}"
                id_number = f"2026-{counter:04d}"
                user, _ = User.objects.update_or_create(
                    username=username,
                    defaults={
                        "first_name": first,
                        "last_name": last,
                        "role": User.Role.STUDENT,
                        "id_number": id_number,
                        "is_active": True,
                        "must_change_password": False,
                    },
                )
                user.set_password(DEMO_PASSWORD)
                user.save()
                StudentProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "program": section.program,
                        "major": section.major,
                        "year_level": section.year_level,
                        "section": section,
                    },
                )
                students_by_section.setdefault(section.pk, []).append(user)
                counter += 1

        total = sum(len(v) for v in students_by_section.values())
        self.stdout.write(self.style.SUCCESS(f"{total} students ready across {len(section_list)} sections (password {DEMO_PASSWORD})."))
        return students_by_section

    def _seed_rosters(self, students_by_section, sections, classes):
        created = 0
        for class_offering in classes:
            for section in class_offering.sections.all():
                for student in students_by_section.get(section.pk, []):
                    _, was_created = ClassRosterEntry.objects.get_or_create(
                        student=student, class_offering=class_offering
                    )
                    created += was_created
        self.stdout.write(self.style.SUCCESS(f"Class list entries ready ({created} newly created)."))
