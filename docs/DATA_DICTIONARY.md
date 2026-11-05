# CITCI GradeTrack — Data Dictionary

Generated from the Django models (`tools/generate_erd.py`). A `.docx` twin lives alongside this file for pasting into the paper.

| App | Model | Field | Type | Null? | Description |
|---|---|---|---|---|---|
| accounts | User | id | bigint (PK) | no |  |
| accounts | User | password | varchar | no |  |
| accounts | User | last_login | timestamptz | yes |  |
| accounts | User | is_superuser | boolean | no | Designates that this user has all permissions without explicitly assigning them. |
| accounts | User | username | varchar | no | Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only. |
| accounts | User | first_name | varchar | no |  |
| accounts | User | last_name | varchar | no |  |
| accounts | User | email | varchar | no |  |
| accounts | User | is_staff | boolean | no | Designates whether the user can log into this admin site. |
| accounts | User | is_active | boolean | no | Designates whether this user should be treated as active. Unselect this instead of deleting accounts. |
| accounts | User | date_joined | timestamptz | no |  |
| accounts | User | role | varchar | no | choices: ['ADMIN', 'PROGRAM_HEAD', 'INSTRUCTOR', 'STUDENT'] |
| accounts | User | middle_name | varchar | no |  |
| accounts | User | id_number | varchar | yes | Student number or employee number. |
| accounts | User | must_change_password | boolean | no |  |
| accounts | User | privacy_consent_at | timestamptz | yes | When the user acknowledged the Data Privacy notice (RA 10173). |
| accounts | User | groups | bigint | no | many-to-many -> Group |
| accounts | User | user_permissions | bigint | no | many-to-many -> Permission |
| accounts | AuditLog | id | bigint (PK) | no |  |
| accounts | AuditLog | created_at | timestamptz | no |  |
| accounts | AuditLog | updated_at | timestamptz | no |  |
| accounts | AuditLog | actor_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| accounts | AuditLog | action | varchar | no | choices: ['USER_CREATED', 'USER_UPDATED', 'USER_DEACTIVATED', 'USER_REACTIVATED', 'PASSWORD_RESET', 'ACCOUNT_UNLOCKED', 'ACCOUNT_LOCKED_OUT'] |
| accounts | AuditLog | target_user_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| accounts | AuditLog | details | jsonb | no |  |
| academics | AcademicYear | id | bigint (PK) | no |  |
| academics | AcademicYear | created_at | timestamptz | no |  |
| academics | AcademicYear | updated_at | timestamptz | no |  |
| academics | AcademicYear | start_year | int (unsigned) | no |  |
| academics | AcademicYear | end_year | int (unsigned) | no |  |
| academics | Semester | id | bigint (PK) | no |  |
| academics | Semester | created_at | timestamptz | no |  |
| academics | Semester | updated_at | timestamptz | no |  |
| academics | Semester | academic_year_id | bigint (FK) | no | -> AcademicYear (on_delete=PROTECT) |
| academics | Semester | term | varchar | no | choices: ['FIRST', 'SECOND', 'SUMMER'] |
| academics | Semester | start_date | date | yes |  |
| academics | Semester | end_date | date | yes |  |
| academics | Semester | is_active | boolean | no |  |
| academics | Program | id | bigint (PK) | no |  |
| academics | Program | created_at | timestamptz | no |  |
| academics | Program | updated_at | timestamptz | no |  |
| academics | Program | code | varchar | no |  |
| academics | Program | name | varchar | no |  |
| academics | Program | program_head_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| academics | Program | is_active | boolean | no |  |
| academics | Major | id | bigint (PK) | no |  |
| academics | Major | created_at | timestamptz | no |  |
| academics | Major | updated_at | timestamptz | no |  |
| academics | Major | program_id | bigint (FK) | no | -> Program (on_delete=PROTECT) |
| academics | Major | code | varchar | no | e.g. ENG, SS |
| academics | Major | name | varchar | no |  |
| academics | Major | is_active | boolean | no |  |
| academics | Section | id | bigint (PK) | no |  |
| academics | Section | created_at | timestamptz | no |  |
| academics | Section | updated_at | timestamptz | no |  |
| academics | Section | program_id | bigint (FK) | no | -> Program (on_delete=PROTECT) |
| academics | Section | major_id | bigint (FK) | yes | -> Major (on_delete=PROTECT) |
| academics | Section | academic_year_id | bigint (FK) | no | -> AcademicYear (on_delete=PROTECT) |
| academics | Section | year_level | smallint (unsigned) | yes | choices: [1, 2, 3, 4] |
| academics | Section | name | varchar | no |  |
| academics | Subject | id | bigint (PK) | no |  |
| academics | Subject | created_at | timestamptz | no |  |
| academics | Subject | updated_at | timestamptz | no |  |
| academics | Subject | code | varchar | no |  |
| academics | Subject | title | varchar | no |  |
| academics | Subject | units | decimal | no |  |
| academics | Subject | program_id | bigint (FK) | yes | -> Program (on_delete=PROTECT) |
| academics | Subject | major_id | bigint (FK) | yes | -> Major (on_delete=PROTECT) |
| academics | Subject | year_level | smallint (unsigned) | yes | choices: [1, 2, 3, 4] |
| academics | Subject | term | varchar | no | Recommended term. choices: ['FIRST', 'SECOND', 'SUMMER'] |
| academics | Subject | is_active | boolean | no |  |
| academics | StudentProfile | id | bigint (PK) | no |  |
| academics | StudentProfile | created_at | timestamptz | no |  |
| academics | StudentProfile | updated_at | timestamptz | no |  |
| academics | StudentProfile | user_id | bigint (FK) | no | -> User (on_delete=CASCADE) |
| academics | StudentProfile | program_id | bigint (FK) | yes | -> Program (on_delete=PROTECT) |
| academics | StudentProfile | major_id | bigint (FK) | yes | -> Major (on_delete=PROTECT) |
| academics | StudentProfile | year_level | smallint (unsigned) | yes | choices: [1, 2, 3, 4] |
| academics | StudentProfile | section_id | bigint (FK) | yes | -> Section (on_delete=SET_NULL) |
| academics | ClassOffering | id | bigint (PK) | no |  |
| academics | ClassOffering | created_at | timestamptz | no |  |
| academics | ClassOffering | updated_at | timestamptz | no |  |
| academics | ClassOffering | subject_id | bigint (FK) | no | -> Subject (on_delete=PROTECT) |
| academics | ClassOffering | semester_id | bigint (FK) | no | -> Semester (on_delete=PROTECT) |
| academics | ClassOffering | instructor_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| academics | ClassOffering | schedule | varchar | no |  |
| academics | ClassOffering | room | varchar | no |  |
| academics | ClassOffering | is_active | boolean | no |  |
| academics | ClassOffering | sections | bigint | no | many-to-many -> Section |
| academics | ClassRosterEntry | id | bigint (PK) | no |  |
| academics | ClassRosterEntry | created_at | timestamptz | no |  |
| academics | ClassRosterEntry | updated_at | timestamptz | no |  |
| academics | ClassRosterEntry | student_id | bigint (FK) | no | -> User (on_delete=PROTECT) |
| academics | ClassRosterEntry | class_offering_id | bigint (FK) | no | -> ClassOffering (on_delete=PROTECT) |
| academics | ClassRosterEntry | status | varchar | no | choices: ['ACTIVE', 'DROPPED'] |
| academics | ClassRosterEntry | date_added | date | no |  |
| academics | ClassRosterEntry | date_dropped | date | yes |  |
| academics | ClassRosterEntry | is_incomplete | boolean | no | Instructor marks INC (Incomplete) for this class manually. |
| academics | ClassRosterEntry | incomplete_reason | varchar | no |  |
| academics | TeachingAssignmentLog | id | bigint (PK) | no |  |
| academics | TeachingAssignmentLog | created_at | timestamptz | no |  |
| academics | TeachingAssignmentLog | updated_at | timestamptz | no |  |
| academics | TeachingAssignmentLog | class_offering_id | bigint (FK) | no | -> ClassOffering (on_delete=CASCADE) |
| academics | TeachingAssignmentLog | old_instructor_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| academics | TeachingAssignmentLog | new_instructor_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| academics | TeachingAssignmentLog | changed_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| academics | TeachingAssignmentLog | is_admin_override | boolean | no |  |
| academics | TeachingAssignmentLog | reason | varchar | no |  |
| grading | GradingTemplate | id | bigint (PK) | no |  |
| grading | GradingTemplate | created_at | timestamptz | no |  |
| grading | GradingTemplate | updated_at | timestamptz | no |  |
| grading | GradingTemplate | name | varchar | no |  |
| grading | GradingTemplate | description | varchar | no |  |
| grading | GradingTemplate | is_default | boolean | no |  |
| grading | GradingTemplate | is_active | boolean | no |  |
| grading | GradingComponent | id | bigint (PK) | no |  |
| grading | GradingComponent | created_at | timestamptz | no |  |
| grading | GradingComponent | updated_at | timestamptz | no |  |
| grading | GradingComponent | template_id | bigint (FK) | no | -> GradingTemplate (on_delete=CASCADE) |
| grading | GradingComponent | name | varchar | no |  |
| grading | GradingComponent | category | varchar | no | choices: ['ATTENDANCE', 'QUIZ', 'RECITATION', 'PROJECT', 'EXAM', 'OTHER'] |
| grading | GradingComponent | weight | int (unsigned) | no | Whole-number percent, e.g. 30 for 30%. |
| grading | GradingComponent | is_locked | boolean | no | School-fixed weight (e.g. Examination 40%) — instructors can't rename, recategorize, or reweight a locked component in their class, only the unlocked ones. |
| grading | GradingComponent | order | smallint (unsigned) | no |  |
| grading | ClassGradingScheme | id | bigint (PK) | no |  |
| grading | ClassGradingScheme | created_at | timestamptz | no |  |
| grading | ClassGradingScheme | updated_at | timestamptz | no |  |
| grading | ClassGradingScheme | class_offering_id | bigint (FK) | no | -> ClassOffering (on_delete=CASCADE) |
| grading | ClassGradingScheme | source_template_id | bigint (FK) | yes | -> GradingTemplate (on_delete=PROTECT) |
| grading | SchemeComponent | id | bigint (PK) | no |  |
| grading | SchemeComponent | created_at | timestamptz | no |  |
| grading | SchemeComponent | updated_at | timestamptz | no |  |
| grading | SchemeComponent | scheme_id | bigint (FK) | no | -> ClassGradingScheme (on_delete=CASCADE) |
| grading | SchemeComponent | name | varchar | no |  |
| grading | SchemeComponent | category | varchar | no | choices: ['ATTENDANCE', 'QUIZ', 'RECITATION', 'PROJECT', 'EXAM', 'OTHER'] |
| grading | SchemeComponent | weight | int (unsigned) | no | Whole-number percent, e.g. 30 for 30%. |
| grading | SchemeComponent | is_locked | boolean | no | School-fixed — this instructor can't rename/recategorize/reweight it. |
| grading | SchemeComponent | order | smallint (unsigned) | no |  |
| grading | AssessmentItem | id | bigint (PK) | no |  |
| grading | AssessmentItem | created_at | timestamptz | no |  |
| grading | AssessmentItem | updated_at | timestamptz | no |  |
| grading | AssessmentItem | class_offering_id | bigint (FK) | no | -> ClassOffering (on_delete=CASCADE) |
| grading | AssessmentItem | component_id | bigint (FK) | no | -> SchemeComponent (on_delete=PROTECT) |
| grading | AssessmentItem | title | varchar | no |  |
| grading | AssessmentItem | max_score | int (unsigned) | no | Whole numbers only — matches CITCI's class record. |
| grading | AssessmentItem | term | varchar | no | Grading period this item belongs to — also drives forecasting checkpoints later. choices: ['PRELIM', 'MIDTERM', 'SEMIFINAL', 'FINAL'] |
| grading | AssessmentItem | date | date | yes |  |
| grading | AssessmentItem | order | smallint (unsigned) | no |  |
| grading | Score | id | bigint (PK) | no |  |
| grading | Score | created_at | timestamptz | no |  |
| grading | Score | updated_at | timestamptz | no |  |
| grading | Score | roster_entry_id | bigint (FK) | no | -> ClassRosterEntry (on_delete=CASCADE) |
| grading | Score | item_id | bigint (FK) | no | -> AssessmentItem (on_delete=CASCADE) |
| grading | Score | score | int (unsigned) | yes | Whole numbers only. |
| grading | Score | updated_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| grading | SchemeComponentChangeLog | id | bigint (PK) | no |  |
| grading | SchemeComponentChangeLog | scheme_id | bigint (FK) | no | -> ClassGradingScheme (on_delete=CASCADE) |
| grading | SchemeComponentChangeLog | action | varchar | no | choices: ['ADDED', 'EDITED', 'DELETED'] |
| grading | SchemeComponentChangeLog | component_name | varchar | no |  |
| grading | SchemeComponentChangeLog | before | jsonb | yes |  |
| grading | SchemeComponentChangeLog | after | jsonb | yes |  |
| grading | SchemeComponentChangeLog | changed_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| grading | SchemeComponentChangeLog | changed_at | timestamptz | no |  |
| grading | ScoreChangeLog | id | bigint (PK) | no |  |
| grading | ScoreChangeLog | score_id | bigint (FK) | no | -> Score (on_delete=CASCADE) |
| grading | ScoreChangeLog | old_value | int (unsigned) | yes |  |
| grading | ScoreChangeLog | new_value | int (unsigned) | yes |  |
| grading | ScoreChangeLog | changed_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| grading | ScoreChangeLog | changed_at | timestamptz | no |  |
| approvals | GradeSheet | id | bigint (PK) | no |  |
| approvals | GradeSheet | created_at | timestamptz | no |  |
| approvals | GradeSheet | updated_at | timestamptz | no |  |
| approvals | GradeSheet | class_offering_id | bigint (FK) | no | -> ClassOffering (on_delete=CASCADE) |
| approvals | GradeSheet | period | varchar | no | choices: ['FINAL', 'MIDTERM'] |
| approvals | GradeSheet | status | varchar | no | choices: ['DRAFT', 'SUBMITTED', 'RETURNED', 'APPROVED', 'RELEASED', 'LOCKED'] |
| approvals | GradeSheet | submitted_at | timestamptz | yes |  |
| approvals | GradeSheet | submitted_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| approvals | GradeSheet | approved_at | timestamptz | yes |  |
| approvals | GradeSheet | approved_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| approvals | GradeSheet | released_at | timestamptz | yes |  |
| approvals | GradeSheet | released_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| approvals | GradeSheet | locked_at | timestamptz | yes |  |
| approvals | GradeSheet | locked_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| approvals | GradeSheet | return_remarks | text | no |  |
| approvals | GradeSheetEntry | id | bigint (PK) | no |  |
| approvals | GradeSheetEntry | created_at | timestamptz | no |  |
| approvals | GradeSheetEntry | updated_at | timestamptz | no |  |
| approvals | GradeSheetEntry | sheet_id | bigint (FK) | no | -> GradeSheet (on_delete=CASCADE) |
| approvals | GradeSheetEntry | roster_entry_id | bigint (FK) | no | -> ClassRosterEntry (on_delete=PROTECT) |
| approvals | GradeSheetEntry | final_grade | decimal | yes |  |
| approvals | GradeSheetEntry | remarks | varchar | no | choices: ['PASSED', 'FAILED', 'INC', 'DROPPED'] |
| approvals | GradeSheetEntry | inc_reason | varchar | no |  |
| approvals | GradeSheetEntry | components_json | jsonb | no |  |
| approvals | GradeSheetTransition | id | bigint (PK) | no |  |
| approvals | GradeSheetTransition | created_at | timestamptz | no |  |
| approvals | GradeSheetTransition | updated_at | timestamptz | no |  |
| approvals | GradeSheetTransition | sheet_id | bigint (FK) | no | -> GradeSheet (on_delete=CASCADE) |
| approvals | GradeSheetTransition | from_status | varchar | no | choices: ['DRAFT', 'SUBMITTED', 'RETURNED', 'APPROVED', 'RELEASED', 'LOCKED'] |
| approvals | GradeSheetTransition | to_status | varchar | no | choices: ['DRAFT', 'SUBMITTED', 'RETURNED', 'APPROVED', 'RELEASED', 'LOCKED'] |
| approvals | GradeSheetTransition | actor_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| approvals | GradeSheetTransition | remarks | text | no |  |
| approvals | GradeCorrection | id | bigint (PK) | no |  |
| approvals | GradeCorrection | created_at | timestamptz | no |  |
| approvals | GradeCorrection | updated_at | timestamptz | no |  |
| approvals | GradeCorrection | entry_id | bigint (FK) | no | -> GradeSheetEntry (on_delete=CASCADE) |
| approvals | GradeCorrection | old_grade | decimal | yes |  |
| approvals | GradeCorrection | new_grade | decimal | yes |  |
| approvals | GradeCorrection | old_remarks | varchar | no |  |
| approvals | GradeCorrection | new_remarks | varchar | no |  |
| approvals | GradeCorrection | reason | text | no |  |
| approvals | GradeCorrection | corrected_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| forecasting | MlModelVersion | id | bigint (PK) | no |  |
| forecasting | MlModelVersion | created_at | timestamptz | no |  |
| forecasting | MlModelVersion | updated_at | timestamptz | no |  |
| forecasting | MlModelVersion | checkpoint | varchar | no | choices: ['PRELIM', 'MIDTERM'] |
| forecasting | MlModelVersion | trained_at | timestamptz | no |  |
| forecasting | MlModelVersion | training_source | varchar | no | choices: ['SYNTHETIC', 'HISTORICAL', 'MIXED'] |
| forecasting | MlModelVersion | n_samples | int (unsigned) | no |  |
| forecasting | MlModelVersion | positive_rate | decimal | no |  |
| forecasting | MlModelVersion | threshold | decimal | no |  |
| forecasting | MlModelVersion | metrics_json | jsonb | no | accuracy/precision/recall/f1/roc_auc + 95% bootstrap CIs |
| forecasting | MlModelVersion | cv_json | jsonb | no | 5-fold stratified CV mean +/- SD per metric |
| forecasting | MlModelVersion | confusion_matrix_json | jsonb | no |  |
| forecasting | MlModelVersion | coefficients_json | jsonb | no | [{feature, coefficient, odds_ratio}, ...] |
| forecasting | MlModelVersion | feature_list | jsonb | no | feature names/order + imputation medians used at train time |
| forecasting | MlModelVersion | is_active | boolean | no |  |
| forecasting | MlModelVersion | model_file | varchar | no | joblib path under MEDIA_ROOT/models/ — not committed to git. |
| forecasting | Prediction | id | bigint (PK) | no |  |
| forecasting | Prediction | created_at | timestamptz | no |  |
| forecasting | Prediction | updated_at | timestamptz | no |  |
| forecasting | Prediction | roster_entry_id | bigint (FK) | no | -> ClassRosterEntry (on_delete=CASCADE) |
| forecasting | Prediction | checkpoint | varchar | no | choices: ['PRELIM', 'MIDTERM'] |
| forecasting | Prediction | model_version_id | bigint (FK) | no | -> MlModelVersion (on_delete=PROTECT) |
| forecasting | Prediction | probability | decimal | no |  |
| forecasting | Prediction | label | varchar | no | choices: ['AT_RISK', 'NOT_AT_RISK'] |
| forecasting | Prediction | contributions_json | jsonb | no | per-feature contribution + plain-language reasons, sorted by impact |
| forecasting | Prediction | computed_at | timestamptz | no |  |
| forecasting | Prediction | instructor_notified_at | timestamptz | yes |  |
| forecasting | Prediction | student_notified_at | timestamptz | yes |  |
| forecasting | HistoricalImportBatch | id | bigint (PK) | no |  |
| forecasting | HistoricalImportBatch | created_at | timestamptz | no |  |
| forecasting | HistoricalImportBatch | updated_at | timestamptz | no |  |
| forecasting | HistoricalImportBatch | uploaded_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| forecasting | HistoricalImportBatch | file_count | int (unsigned) | no |  |
| forecasting | HistoricalImportBatch | row_count | int (unsigned) | no |  |
| forecasting | HistoricalImportBatch | positive_count | int (unsigned) | no |  |
| forecasting | HistoricalImportBatch | term_assignment_note | text | no |  |
| forecasting | HistoricalImportBatch | skipped_rows_json | jsonb | no | [{file, row, reason}, ...] |
| forecasting | HistoricalRecord | id | bigint (PK) | no |  |
| forecasting | HistoricalRecord | masked_id | varchar | no |  |
| forecasting | HistoricalRecord | semester_label | varchar | no |  |
| forecasting | HistoricalRecord | subject_code | varchar | no |  |
| forecasting | HistoricalRecord | checkpoint | varchar | no | choices: ['PRELIM', 'MIDTERM'] |
| forecasting | HistoricalRecord | features_json | jsonb | no |  |
| forecasting | HistoricalRecord | label | smallint (unsigned) | no | 1 = at risk, 0 = not at risk |
| forecasting | HistoricalRecord | batch_id | bigint (FK) | no | -> HistoricalImportBatch (on_delete=CASCADE) |
| forecasting | Intervention | id | bigint (PK) | no |  |
| forecasting | Intervention | created_at | timestamptz | no |  |
| forecasting | Intervention | updated_at | timestamptz | no |  |
| forecasting | Intervention | roster_entry_id | bigint (FK) | no | -> ClassRosterEntry (on_delete=CASCADE) |
| forecasting | Intervention | created_by_id | bigint (FK) | yes | -> User (on_delete=SET_NULL) |
| forecasting | Intervention | date | date | no |  |
| forecasting | Intervention | type | varchar | no | choices: ['CONSULTATION', 'REMEDIAL', 'REFERRAL', 'PARENT_CONTACT', 'OTHER'] |
| forecasting | Intervention | notes | text | no |  |
| forecasting | Intervention | follow_up_date | date | yes |  |
| forecasting | Intervention | outcome | varchar | no | choices: ['PENDING', 'IMPROVED', 'NO_CHANGE'] |
| reports | InstitutionSettings | id | bigint (PK) | no |  |
| reports | InstitutionSettings | created_at | timestamptz | no |  |
| reports | InstitutionSettings | updated_at | timestamptz | no |  |
| reports | InstitutionSettings | school_name | varchar | no |  |
| reports | InstitutionSettings | sub_line | varchar | no |  |
| reports | InstitutionSettings | address | varchar | no |  |
| reports | InstitutionSettings | department | varchar | no |  |
| reports | InstitutionSettings | logo | filefield | no | Leave blank to use the default CITCI seal (static/img/citci-seal-256.png). |
| reports | InstitutionSettings | dean_name | varchar | no |  |
| reports | InstitutionSettings | dean_title | varchar | no |  |
| reports | InstitutionSettings | academic_head_name | varchar | no |  |
| reports | InstitutionSettings | academic_head_title | varchar | no |  |
| reports | InstitutionSettings | registrar_name | varchar | no | Signatory on a student's own Report of Grades PDF. |
| reports | InstitutionSettings | registrar_title | varchar | no |  |
| reports | InstitutionSettings | show_unofficial_scores_to_students | boolean | no | When off, a student's in-progress (not yet released) subjects show only "Grades not yet released" — no running score/grade at all. |
| reports | InstitutionSettings | show_forecasts_to_students | boolean | no | Off by default while active forecast models are trained on synthetic data — turn on once a real, masked-historical model is active. When off, students see no forecast card/section at all (never probability or the words "at risk" either way). |
| reports | InstitutionSettings | privacy_notice_text | text | no | Shown on both the login page's Data Privacy Notice modal and the forced first-login consent page — one editable source for both, System → Settings. Paragraphs separated by a blank line. |
| reports | InstitutionSettings | data_privacy_officer_contact | varchar | no | Who/how to contact about data privacy concerns — shown at the end of the Data Privacy Notice. |
| dashboard | Notification | id | bigint (PK) | no |  |
| dashboard | Notification | recipient_id | bigint (FK) | no | -> User (on_delete=CASCADE) |
| dashboard | Notification | title | varchar | no |  |
| dashboard | Notification | message | text | no |  |
| dashboard | Notification | link | varchar | no |  |
| dashboard | Notification | is_read | boolean | no |  |
| dashboard | Notification | created_at | timestamptz | no |  |
