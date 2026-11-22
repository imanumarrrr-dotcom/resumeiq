"""Fill the database with demo data so the dashboards and chatbot have something to show.

    python seed_demo.py          # adds demo accounts, jobs and scored applications
All demo accounts use the password  demo123
"""
import random
import textwrap
import uuid
from datetime import timedelta

from werkzeug.security import generate_password_hash

from app import app
from models import Application, Job, User, db, now
from screener import analyse, extract_text

PASSWORD = "demo123"
JOBS = [
    ("Backend Developer", "Build and maintain REST APIs and background jobs for our hiring platform. Work with databases and deploy services.", "python, flask, sql, docker, git"),
    ("Data Analyst", "Turn raw hiring data into dashboards and reports. Clean data, run analysis and present insights to managers.", "python, pandas, sql, excel, statistics"),
    ("Frontend Developer", "Build responsive interfaces with modern JavaScript. Work with designers and consume REST APIs.", "javascript, react, html, css, git"),
    ("UI UX Designer", "Design user flows, wireframes and prototypes for web and mobile products. Run usability tests.", "figma, wireframing, prototyping, user research"),
    ("Machine Learning Engineer", "Train and ship models for resume ranking and text analysis. Own the pipeline from data to production.", "python, machine learning, scikit-learn, nlp, sql"),
]
PEOPLE = [
    ("Ayesha Khan", "Python developer with 3 years of experience building REST APIs in Flask. Strong SQL and Git skills. Deployed services with Docker."),
    ("Bilal Ahmed", "Data analyst. Python, pandas and SQL for reporting. Built Excel and dashboard reports. Statistics background."),
    ("Sara Malik", "Frontend engineer. JavaScript, React, HTML and CSS. Built responsive interfaces and used Git daily."),
    ("Hamza Ali", "Machine learning enthusiast. Python, scikit-learn and NLP projects. Some SQL. Final year project on text classification."),
    ("Zainab Noor", "Designer with Figma, wireframing and prototyping experience. Ran user research interviews and usability tests."),
    ("Usman Tariq", "Fresh graduate. Basic Python and HTML. Looking for a first role in software."),
]


def make_pdf(text):
    """Smallest valid text PDF, enough for PyPDF2 to read back."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 11 Tf 50 740 Td 15 TL " + " ".join(f"({esc(l)}) Tj T*" for l in textwrap.wrap(text, 85)) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


def user(name, email, role):
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(name=name, email=email, role=role, password_hash=generate_password_hash(PASSWORD))
        db.session.add(u)
        db.session.commit()
    return u


with app.app_context():
    random.seed(7)
    user("Demo Admin", "admin@demo.com", "admin")
    boss = user("Talent Team", "employer@demo.com", "employer")
    jobs = []
    for title, desc, skills in JOBS:
        j = Job.query.filter_by(title=title, employer_id=boss.id).first()
        if not j:
            j = Job(employer_id=boss.id, title=title, description=desc, skills=skills)
            db.session.add(j)
            db.session.commit()
        jobs.append(j)
    for name, resume in PEOPLE:
        u = user(name, name.split()[0].lower() + "@demo.com", "applicant")
        for j in random.sample(jobs, 3):
            if Application.query.filter_by(job_id=j.id, applicant_id=u.id).first():
                continue
            stored = uuid.uuid4().hex + ".pdf"
            path = f"{app.config['UPLOAD_FOLDER']}/{stored}"
            open(path, "wb").write(make_pdf(f"{name}. {resume}"))
            r = analyse(extract_text(path), j.description, j.skills)
            db.session.add(Application(
                job_id=j.id, applicant_id=u.id, resume_file=stored, original_name=f"{name}.pdf",
                score=r["score"], matched=",".join(r["matched"]), missing=",".join(r["missing"]),
                status=random.choice(["Pending", "Pending", "Shortlisted", "Rejected"]),
                applied_at=now() - timedelta(days=random.randint(0, 6), hours=random.randint(0, 20))))
    db.session.commit()
    print("Demo data ready. Log in with password", PASSWORD)
    print("  admin:     admin@demo.com\n  employer:  employer@demo.com\n  applicant: ayesha@demo.com")
