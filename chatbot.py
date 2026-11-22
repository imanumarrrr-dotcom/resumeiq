"""ResumeIQ assistant: intent rules + TF-IDF job search over the real database.

No API key or external service needed. reply() returns
{"text": str, "cards": [{"title", "sub", "url"}], "chips": [str]}.
"""
import re
from collections import Counter

from flask import url_for
from flask_login import current_user
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models import Application, Job, User

# words that describe the request itself, not the job being searched for
FILLER = set(ENGLISH_STOP_WORDS) | {
    "job", "jobs", "find", "search", "show", "looking", "look", "opening", "openings",
    "vacancy", "vacancies", "position", "positions", "role", "roles", "work", "hiring",
    "available", "related", "please", "need", "want", "latest", "new", "open", "any",
    "naukri", "naukriyan", "dhundo", "dhoondo", "mujhe", "mujhay", "koi", "hai", "chahiye",
    "kaam", "mein", "liye", "batao", "dikhao", "ke", "ki", "ka", "ko", "kya"}

CHIPS = {
    "guest": ["Find jobs", "How does scoring work?", "How do I apply?"],
    "applicant": ["Find Python jobs", "My applications", "Improve my resume", "How does scoring work?"],
    "employer": ["My jobs", "Top candidates", "How does scoring work?"],
    "admin": ["Platform stats", "How does scoring work?"],
}


def _out(text, cards=None, chips=None):
    role = current_user.role if current_user.is_authenticated else "guest"
    return {"text": text, "cards": cards or [], "chips": CHIPS[role] if chips is None else chips}


def _has(msg, *phrases):
    return any(re.search(r"\b" + re.escape(p) + r"\b", msg) for p in phrases)


def _job_card(job):
    return {"title": job.title, "sub": ", ".join(job.skill_list[:4]),
            "url": url_for("job_detail", job_id=job.id)}


def search_jobs(query, limit=3):
    """Rank open jobs against the words in the query. Returns (jobs, search_terms)."""
    jobs = Job.query.filter_by(is_open=True).order_by(Job.created_at.desc()).all()
    terms = [w for w in re.findall(r"[a-z0-9+#.]+", query.lower())
             if w not in FILLER and len(w) > 1]
    if not jobs or not terms:
        return jobs[:limit], terms
    docs = [f"{j.title} {j.title} {j.skills} {j.skills} {j.description}".lower() for j in jobs]
    try:
        matrix = TfidfVectorizer(token_pattern=r"[a-z0-9+#.]+").fit_transform(docs + [" ".join(terms)])
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
    except ValueError:
        sims = [0.0] * len(jobs)
    scored = [(sim + 0.25 * sum(t in d for t in terms), j) for sim, d, j in zip(sims, docs, jobs)]
    scored.sort(key=lambda p: -p[0])
    return [j for s, j in scored if s > 0.02][:limit], terms


def _find_jobs(msg):
    jobs, terms = search_jobs(msg)
    if not Job.query.filter_by(is_open=True).count():
        return _out("There are no open jobs right now. Check back soon.")
    if not terms:
        return _out("Here are the newest open jobs:", [_job_card(j) for j in jobs])
    if not jobs:
        return _out(f"I found no open job matching \"{' '.join(terms)}\". "
                    "Try a skill (python, sql) or a job title.")
    return _out(f"I found {len(jobs)} open job{'s' if len(jobs) != 1 else ''} "
                f"matching \"{' '.join(terms)}\":", [_job_card(j) for j in jobs])


def _applicant_status():
    apps = (Application.query.filter_by(applicant_id=current_user.id)
            .order_by(Application.applied_at.desc()).limit(5).all())
    if not apps:
        return _out("You have not applied anywhere yet. Ask me to find jobs that fit your skills.")
    cards = [{"title": a.job.title, "sub": f"{round(a.score)}% match · {a.status}",
              "url": url_for("my_application", app_id=a.id)} for a in apps]
    total = Application.query.filter_by(applicant_id=current_user.id).count()
    return _out(f"You have {total} application{'s' if total != 1 else ''}. Your latest:", cards)


def _resume_tips():
    apps = Application.query.filter_by(applicant_id=current_user.id).all()
    missing = Counter(s for a in apps for s in a.missing_list).most_common(4)
    general = ("Tips: mirror the job's own wording, list tools by name (not just \"programming\"), "
               "and add one measurable result per role.")
    if not missing:
        return _out(general + " You can also test a resume against any job before applying.",
                    [{"title": "Check my resume", "sub": "Score it without applying",
                      "url": url_for("analyzer")}] if current_user.role == "applicant" else None)
    names = ", ".join(s for s, _ in missing)
    return _out(f"Across your applications the skills you are missing most are: {names}. "
                f"If you have them, name them explicitly in your resume. {general}",
                [{"title": "Check my resume", "sub": "Score it without applying",
                  "url": url_for("analyzer")}])


def _employer_jobs(top_only):
    jobs = Job.query.filter_by(employer_id=current_user.id).order_by(Job.created_at.desc()).all()
    if not jobs:
        return _out("You have no jobs yet. Post one to start receiving ranked applicants.",
                    [{"title": "Post a job", "sub": "", "url": url_for("job_new")}])
    cards = []
    for j in jobs[:5]:
        ranked = sorted(j.applications, key=lambda a: -a.score)
        if top_only:
            if ranked:
                cards.append({"title": f"{ranked[0].applicant.name} · {round(ranked[0].score)}%",
                              "sub": j.title, "url": url_for("candidate_detail", app_id=ranked[0].id)})
        else:
            best = f" · best {round(ranked[0].score)}%" if ranked else ""
            cards.append({"title": j.title, "sub": f"{len(ranked)} applicants{best}",
                          "url": url_for("job_applicants", job_id=j.id)})
    if not cards:
        return _out("No applicants yet. Candidates appear here as soon as they apply.")
    return _out("Your top candidate for each job:" if top_only else "Your jobs:", cards)


def _admin_stats():
    users = User.query.filter(User.role != "admin").count()
    open_jobs = Job.query.filter_by(is_open=True).count()
    apps = Application.query.count()
    return _out(f"{users} users, {open_jobs} open of {Job.query.count()} jobs, "
                f"{apps} resumes processed.",
                [{"title": "System dashboard", "sub": "Full overview", "url": url_for("admin_dashboard")},
                 {"title": "Manage users", "sub": "", "url": url_for("admin_users")}])


def reply(message):
    msg = re.sub(r"\s+", " ", message.lower()).strip()
    role = current_user.role if current_user.is_authenticated else "guest"
    if not msg:
        return _out("Type a message and I will help.")

    if len(msg.split()) <= 3 and _has(msg, "hi", "hello", "hey", "salam", "assalamualaikum", "salaam"):
        who = f", {current_user.name.split()[0]}" if current_user.is_authenticated else ""
        return _out(f"Hi{who}! I can search the live job board, explain match scores, "
                    "and track your applications. What do you need?")
    if _has(msg, "thanks", "thank you", "shukriya", "thx"):
        return _out("You're welcome! Anything else?")
    if _has(msg, "help", "what can you do", "who are you", "madad"):
        return _out("I search real open jobs, explain how resumes are scored, give resume tips, "
                    "and show your applications or candidates.")

    if _has(msg, "my applications", "my application", "applied", "status", "shortlisted", "rejected", "pending"):
        if role == "applicant":
            return _applicant_status()
        if role == "guest":
            return _out("Log in as an applicant to see your applications.",
                        [{"title": "Log in", "sub": "", "url": url_for("login")}])
    if role == "employer" and _has(msg, "top", "best", "candidates", "applicants", "ranked"):
        return _employer_jobs(top_only=True)
    if role == "employer" and _has(msg, "my jobs", "my postings", "postings", "jobs i posted"):
        return _employer_jobs(top_only=False)
    if role == "admin" and _has(msg, "stats", "users", "platform", "overview", "total", "dashboard"):
        return _admin_stats()

    if _has(msg, "score", "scoring", "scored", "match score", "calculated", "ranking"):
        return _out("Each resume is scored against the job: 70% wording similarity "
                    "(TF-IDF cosine) plus 30% share of the required skills found in the PDF. "
                    "Above 60% is a strong match, 35-60% partial.")
    if _has(msg, "resume", "cv", "improve", "tips", "ats", "skills gap"):
        return _resume_tips() if role == "applicant" else _out(
            "Tips: mirror the job's wording, name tools explicitly, add measurable results.")
    if _has(msg, "apply", "how to apply", "application process"):
        return _out("Open a job, upload your PDF resume (max 5 MB) and press Apply. "
                    "You get your match score right away.",
                    [{"title": "Browse jobs", "sub": "", "url": url_for("job_board")}])
    return _find_jobs(msg)
