from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import User
from academics.models import (
    AcademicYear,
    ClassOffering,
    Enrollment,
    Program,
    Section,
    Semester,
    StudentProfile,
    Subject,
    Term,
)

DEMO_PASSWORD = "Demo@1234"

SUBJECTS = [
    # code, title, lec, lab, program (True = BSIT, False = Gen Ed / no program)
    ("IT101", "Introduction to Computing", "3.0", "0.0", True),
    ("IT102", "Computer Programming 1", "2.0", "1.0", True),
    ("CS101", "Discrete Mathematics", "3.0", "0.0", True),
    ("GE101", "Understanding the Self", "3.0", "0.0", False),
    ("GE102", "Mathematics in the Modern World", "3.0", "0.0", False),
    ("PE101", "Physical Education 1: PATH Fit", "2.0", "0.0", False),
]

NEW_INSTRUCTORS = [
    {"username": "instructor2", "first_name": "Marvin", "last_name": "Cailles", "id_number": "EMP-0004"},
    {"username": "instructor3", "first_name": "Lourdes", "last_name": "Patangan", "id_number": "EMP-0005"},
]

STUDENT_NAMES = [
    ("Juan", "Dela Cruz"), ("Maria", "Santos"), ("Jose", "Reyes"), ("Angela", "Bautista"),
    ("Mark", "Gonzales"), ("Kristine", "Ramos"), ("Paolo", "Mendoza"), ("Camille", "Torres"),
    ("Ronnel", "Flores"), ("Jasmine", "Villanueva"), ("Christian", "Castillo"), ("Angelica", "Garcia"),
    ("Michael", "Aquino"), ("Shaira", "Del Rosario"), ("Jerome", "Pascual"), ("Nicole", "Marquez"),
    ("Rodel", "Navarro"), ("Precious", "Salazar"), ("Vincent", "Ocampo"), ("Charmaine", "Domingo"),
    ("Aldrin", "Fernandez"), ("Rizza", "Manalo"), ("Julius", "Panganiban"), ("Vanessa", "Rosario"),
    ("Dennis", "Cruz"), ("Jennylyn", "Agustin"), ("Edward", "Lazaro"), ("Kimberly", "Soriano"),
    ("Francis", "Valdez"), ("Grace", "Padilla"),
]


class Command(BaseCommand):
    help = "Seeds a demo academic structure (A.Y., semesters, BSIT program, sections, subjects, classes, 30 students, enrollments). Safe to re-run."

    def handle(self, *args, **options):
        academic_year, program, instructors, section_a = self._seed_core()
        subjects = self._seed_subjects(program)
        classes = self._seed_classes(subjects, section_a, instructors)
        students = self._seed_students(program, section_a)
        self._seed_enrollments(students, classes)

        self.stdout.write(self.style.SUCCESS("\nDemo academic data ready."))

    def _seed_core(self):
        academic_year, _ = AcademicYear.objects.get_or_create(start_year=2026)

        first_sem, _ = Semester.objects.get_or_create(
            academic_year=academic_year, term=Term.FIRST, defaults={"is_active": True}
        )
        if not first_sem.is_active:
            first_sem.is_active = True
            first_sem.save()
        Semester.objects.get_or_create(academic_year=academic_year, term=Term.SECOND)
        self.stdout.write(self.style.SUCCESS(f"Academic year + semesters ready ({academic_year})."))

        program_head = User.objects.filter(username="program_head").first()
        program, _ = Program.objects.update_or_create(
            code="BSIT",
            defaults={"name": "Bachelor of Science in Information Technology", "program_head": program_head},
        )
        self.stdout.write(self.style.SUCCESS(f"Program ready ({program.code})."))

        section_a, _ = Section.objects.get_or_create(
            program=program, academic_year=academic_year, year_level=1, name="A"
        )
        Section.objects.get_or_create(program=program, academic_year=academic_year, year_level=1, name="B")
        self.stdout.write(self.style.SUCCESS("Sections BSIT 1-A and BSIT 1-B ready."))

        instructor1 = User.objects.filter(username="instructor").first()
        instructors = [instructor1]
        for data in NEW_INSTRUCTORS:
            user, _ = User.objects.update_or_create(
                username=data["username"],
                defaults={
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "role": User.Role.INSTRUCTOR,
                    "id_number": data["id_number"],
                    "is_active": True,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            instructors.append(user)
        self.stdout.write(self.style.SUCCESS("Instructors ready (1 existing + 2 new)."))

        return academic_year, program, instructors, section_a

    def _seed_subjects(self, program):
        subjects = []
        for code, title, lec, lab, is_bsit in SUBJECTS:
            subject, _ = Subject.objects.update_or_create(
                code=code,
                defaults={
                    "title": title,
                    "lec_units": Decimal(lec),
                    "lab_units": Decimal(lab),
                    "program": program if is_bsit else None,
                    "year_level": 1,
                    "term": Term.FIRST,
                },
            )
            subjects.append(subject)
        self.stdout.write(self.style.SUCCESS(f"{len(subjects)} subjects ready."))
        return subjects

    def _seed_classes(self, subjects, section_a, instructors):
        active_semester = Semester.objects.get(term=Term.FIRST, academic_year__start_year=2026)
        instructor_for = instructors[0:1] * 3 + instructors[1:2] * 2 + instructors[2:3] * 1
        classes = []
        for subject, instructor in zip(subjects, instructor_for):
            class_offering, _ = ClassOffering.objects.update_or_create(
                subject=subject,
                section=section_a,
                semester=active_semester,
                defaults={"instructor": instructor},
            )
            classes.append(class_offering)
        self.stdout.write(self.style.SUCCESS(f"{len(classes)} classes ready for BSIT 1-A."))
        return classes

    def _seed_students(self, program, section_a):
        students = []

        existing_student = User.objects.filter(username="student").first()
        if existing_student:
            existing_student.must_change_password = False
            existing_student.save(update_fields=["must_change_password"])
            StudentProfile.objects.update_or_create(
                user=existing_student, defaults={"program": program, "year_level": 1, "section": section_a}
            )
            students.append(existing_student)

        for i, (first_name, last_name) in enumerate(STUDENT_NAMES, start=1):
            username = f"student{i:03d}"
            id_number = f"2026-{i:04d}"
            user, _ = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": User.Role.STUDENT,
                    "id_number": id_number,
                    "is_active": True,
                    "must_change_password": False,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            StudentProfile.objects.update_or_create(
                user=user, defaults={"program": program, "year_level": 1, "section": section_a}
            )
            students.append(user)

        self.stdout.write(self.style.SUCCESS(f"{len(students)} students ready in BSIT 1-A (password {DEMO_PASSWORD})."))
        return students

    def _seed_enrollments(self, students, classes):
        created = 0
        for student in students:
            for class_offering in classes:
                _, was_created = Enrollment.objects.get_or_create(student=student, class_offering=class_offering)
                created += was_created
        self.stdout.write(self.style.SUCCESS(f"Enrollments ready ({created} newly created)."))
