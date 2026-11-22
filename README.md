# ResumeIQ: Smart Resume Screener & Job Board

Flask + SQLite + Bootstrap 5 + scikit-learn.

## Run

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
python create_admin.py         # creates the admin account (asks name, email, password)
python seed_demo.py            # optional: demo jobs, users and scored resumes (password: demo123)
python app.py                  # open http://127.0.0.1:5000
```

Set a real secret before deploying:  `set SECRET_KEY=your-long-random-string`

## Roles and access

| Role | Pages |
|---|---|
| Guest | landing page, browse jobs, chatbot, login, register |
| Applicant | job board, job details + apply (PDF), my applications with match breakdown, resume checker (score without applying) |
| Employer | my jobs, new/edit job, open/close, ranked applicants, candidate match details, download resume, change status |
| Admin | sidebar dashboard: overview (stats, 7-day chart, status, match quality), users (search/filter, suspend/delete), jobs (open/close/delete), applications (filter by status) |

Every route is protected on the server by `@role_required(...)` (wrong role -> 403, not logged in -> login page).
Admin accounts cannot be registered from the website, only through `create_admin.py`.

## Chatbot (chatbot.py, static/chat.js)

A floating assistant on every page, served by `POST /api/chat`. It reads the real database (no API key needed):
searches open jobs with TF-IDF ranking, explains scoring, gives resume tips from your missing skills, lists an
applicant's applications, an employer's jobs and top candidates, and admin platform stats. Answers depend on the role.
To use an LLM later, replace the fallback at the end of `reply()` with an API call.

## How scoring works (screener.py)

1. Extract text from the PDF (PyPDF2).
2. Lowercase and strip punctuation from the resume and from (job description + required skills).
3. TF-IDF vectors + cosine similarity give the wording similarity.
4. Skill match = share of required skills found in the resume.
5. Final score = 70% TF-IDF + 30% skill match (change `TFIDF_WEIGHT` / `SKILL_WEIGHT` at the top of the file).
   Matched and missing skills are saved and shown to the employer.

## Security already included

- Passwords hashed (Werkzeug), never stored in plain text
- CSRF protection on every form (Flask-WTF)
- PDF checked by extension AND file header, 5 MB limit, random file names on disk
- One application per applicant per job (checked in code and by a database UNIQUE constraint)
- Employers can only open/download their own jobs' applicants
- Suspended users cannot log in and are logged out immediately

## Ideas to extend (AI)

Semantic score with `sentence-transformers`, LLM resume feedback, auto-generated job descriptions, email on status change.

## Docker

```bash
cp .env.example .env            # then put a long random SECRET_KEY inside
docker compose up -d --build    # open http://localhost:8000

# create the admin account (non-interactive)
docker compose exec -e ADMIN_EMAIL=you@example.com -e ADMIN_PASSWORD=strongpass web python create_admin.py
# optional demo data (password demo123)
docker compose exec web python seed_demo.py
```
Data lives in the `appdata` volume (`/data`). Back it up with `docker run --rm -v resume_screener_appdata:/d -v $PWD:/b alpine tar czf /b/backup.tgz -C /d .`

Push to Docker Hub:
```bash
docker build -t YOUR_USER/resumeiq:1.0 .
docker login && docker push YOUR_USER/resumeiq:1.0
```
Run the pushed image with: `docker run -d -p 8000:8000 -e SECRET_KEY=... -v resumeiq:/data YOUR_USER/resumeiq:1.0`
