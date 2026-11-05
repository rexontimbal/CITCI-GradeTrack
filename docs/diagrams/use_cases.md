# Use Case Diagrams (per role)

Mermaid has no dedicated UML use-case shape, so each diagram below approximates one: the actor is
a node outside the system boundary, each use case is a stadium/pill shape (`([Use case])`) inside
a `subgraph` standing in for the system boundary.

## Admin

```mermaid
graph LR
    Admin(["👤 Admin"])
    subgraph System["CITCI GradeTrack"]
        UC1(["Manage user accounts<br/>(CRUD, bulk import)"])
        UC2(["Manage academic structure<br/>(years, programs, sections, subjects)"])
        UC3(["Assign Program Heads"])
        UC4(["Manage class offerings<br/>& class lists"])
        UC5(["Configure grading templates"])
        UC6(["Lock/unlock terms"])
        UC7(["Override a teaching assignment<br/>(logged)"])
        UC8(["View Teaching Loads<br/>(all programs)"])
        UC9(["Train/activate forecasting<br/>model versions"])
        UC10(["Import historical data"])
        UC11(["View audit log"])
        UC12(["View system-wide reports"])
        UC13(["Configure institution settings"])
    end
    Admin --- UC1
    Admin --- UC2
    Admin --- UC3
    Admin --- UC4
    Admin --- UC5
    Admin --- UC6
    Admin --- UC7
    Admin --- UC8
    Admin --- UC9
    Admin --- UC10
    Admin --- UC11
    Admin --- UC12
    Admin --- UC13
```

## Program Head

```mermaid
graph LR
    ProgramHead(["👤 Program Head"])
    subgraph System["CITCI GradeTrack"]
        UC1(["View department dashboard"])
        UC2(["Assign/change instructor<br/>per class (teaching load)"])
        UC3(["View Teaching Loads<br/>(own program)"])
        UC4(["Approve or return<br/>a submitted grade sheet"])
        UC5(["Release approved grades"])
        UC6(["View at-risk students<br/>& contributing factors"])
        UC7(["Log an intervention"])
        UC8(["Export department reports"])
    end
    ProgramHead --- UC1
    ProgramHead --- UC2
    ProgramHead --- UC3
    ProgramHead --- UC4
    ProgramHead --- UC5
    ProgramHead --- UC6
    ProgramHead --- UC7
    ProgramHead --- UC8
```

## Instructor

```mermaid
graph LR
    Instructor(["👤 Instructor"])
    subgraph System["CITCI GradeTrack"]
        UC1(["View assigned classes"])
        UC2(["Define grading components<br/>(within template rules)"])
        UC3(["Create assessment items"])
        UC4(["Encode scores<br/>(grid or Excel import)"])
        UC5(["Mark a student INC"])
        UC6(["Submit grade sheet"])
        UC7(["Export grade sheet PDF/Excel"])
        UC8(["View class at-risk list"])
        UC9(["Log an intervention"])
        UC10(["View class reports"])
    end
    Instructor --- UC1
    Instructor --- UC2
    Instructor --- UC3
    Instructor --- UC4
    Instructor --- UC5
    Instructor --- UC6
    Instructor --- UC7
    Instructor --- UC8
    Instructor --- UC9
    Instructor --- UC10
```

## Student

```mermaid
graph LR
    Student(["👤 Student"])
    subgraph System["CITCI GradeTrack"]
        UC1(["View class list subjects"])
        UC2(["View running (unofficial)<br/>grades"])
        UC3(["View released (official)<br/>grades"])
        UC4(["View term & cumulative GWA"])
        UC5(["View progress charts"])
        UC6(["View supportive forecast card<br/>(never a number, never the words at risk)"])
        UC7(["Download Report of Grades PDF"])
        UC8(["View notifications"])
    end
    Student --- UC1
    Student --- UC2
    Student --- UC3
    Student --- UC4
    Student --- UC5
    Student --- UC6
    Student --- UC7
    Student --- UC8
```
