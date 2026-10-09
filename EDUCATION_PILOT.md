# VICAM Education pilot — v2.8.0

The working school workspace is at `/admin/education`. It uses your existing Python/FastAPI backend, administrator sign-in, CSRF checks, audit trail and SQLite database. It does not require an external AI service.

## Start with PowerShell

Install Python 3.12 or newer. Extract the ZIP and open PowerShell in `VICAM_Backend`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.manage init
.\.venv\Scripts\python.exe -m app.manage create-admin --email YOUR_EMAIL
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Replace YOUR_EMAIL with your email and choose your own password at the prompt. There is no default password. Existing administrators can keep their accounts. Open `http://127.0.0.1:8000/admin/education` in a browser.

## Use the pilot

1. Create a school and select a review target percentage. The default 50% is an editable planning threshold, not an official curriculum grade.
2. Add students with unique school codes, names and classes. Add subjects.
3. Create an assessment with subject, class, date, maximum marks and optional topic.
4. Select the assessment. Enter marks and save. Blank means missing; zero means a recorded zero. Each page saves up to 200 students; save before changing pages.
5. Review Progress & support, filter by class and discuss flagged subjects with the teacher.
6. Download a JSON progress report if needed. It contains student records and belongs in the school's authorized record-sharing process.

Student names/codes and marks can be corrected. Clearing a mark and saving removes that result from calculations. Students with recorded results cannot be removed through this pilot. Class transfers after results exist need a reviewed transfer workflow and are not included. Assessment metadata is immutable; to correct an incorrectly created assessment, clear its marks and create the corrected assessment.

## Calculations

A percentage is `score / maximum × 100`. Each subject uses the latest recorded result ordered by assessment date, then creation order (ID breaks a tie). The learner average is an equal-weight mean of those latest subject percentages. Missing results are excluded. A learner with no results has no average, not zero.

Change compares the two latest recorded assessments in a subject, in percentage points. Difficulty and topics can differ: this is descriptive, not proof of learning gain. A latest percentage below the school's chosen target is flagged for teacher review. Suggestions refer to the latest assessment topic, or subject if no topic is supplied. This is not an AI diagnosis, validated mastery model or official grade.

## Access and deployment

Only existing staff accounts with the `admin` role can use these APIs. Schools belong to the administrator who creates them. Other administrators, support and finance roles cannot access those school records. Teacher, parent and student accounts, shared school membership, bulk imports and class transfers are not included.

The public education marketing page and lesson illustration remain demonstrations. The live static VICAM website cannot execute this Python backend. Run this source package locally or deploy it on a backend server to use the school workspace. See README.md for online production configuration: HTTPS, origin, secrets and persistent database storage. Evaluate with synthetic records before introducing school-authorized student data.

SQLite is retained for this single-server pilot. PostgreSQL has not been implemented. A shared school product needs a reviewed database migration, school memberships, teacher permissions, retention rules, imports and restore procedures before a wider rollout.

## Upgrade

Back up your database first. Preserve `.env` and `DATABASE_PATH`. Install the new requirements and run `python -m app.manage init`. The additive migration raises the schema to version 8; older schema-7 code must not run against this updated database. Whole-database backups include the school tables. Existing client-only exports do not export school records.

## Tests

Install requirements-dev.txt and run `python -m pytest tests/test_education.py`. Tests cover access/owner isolation, role restrictions, CSRF, atomic writes, score bounds, cross-school links, missing and zero marks, percentage changes, review targets and repeatable migration.
