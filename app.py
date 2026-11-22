import os
import uuid
from datetime import timedelta
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from markupsafe import Markup
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from models import Application, Job, User, db, now
import chatbot
from screener import SKILL_WEIGHT, TFIDF_WEIGHT, analyse, extract_text

BASE = os.path.abspath(os.path.dirname(__file__))
DATA = os.environ.get("DATA_DIR", BASE)          # Docker mounts a volume here
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-in-production"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(DATA, "resume_screener.db"),
    UPLOAD_FOLDER=os.path.join(DATA, "uploads"),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,            # 5 MB uploads
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
db.init_app(app)
CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"
app.jinja_env.globals.update(W_TFIDF=round(TFIDF_WEIGHT * 100), W_SKILL=round(SKILL_WEIGHT * 100))
app.jinja_env.globals["csrf_field"] = lambda: Markup(
    f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">')

with app.app_context():
    db.create_all()

HOME = {"applicant": "job_board", "employer": "employer_dashboard", "admin": "admin_dashboard"}
STATUSES = ("Pending", "Shortlisted", "Rejected")


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


@app.template_filter("score_class")
def score_class(score):
    return "good" if score >= 60 else "mid" if score >= 35 else "low"


@app.template_filter("verdict")
def verdict(score):
    return "Strong match" if score >= 60 else "Partial match" if score >= 35 else "Weak match"


def role_required(*roles):
    """Login + role check. Wrong role -> 403, anonymous -> login page."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


@app.before_request
def block_suspended():
    uid = session.get("_user_id")                     # logged-in user suspended mid-session
    if uid and request.endpoint not in ("login", "static"):
        user = db.session.get(User, int(uid))
        if user and user.suspended:
            logout_user()
            flash("Your account has been suspended.", "danger")
            return redirect(url_for("login"))


def go_home():
    return redirect(url_for(HOME[current_user.role]))


# ------------------------------------------------------------------ auth
@app.route("/")
def index():
    if current_user.is_authenticated:
        return go_home()
    stats = {"jobs": Job.query.filter_by(is_open=True).count(), "resumes": Application.query.count(),
             "people": User.query.filter(User.role != "admin").count()}
    return render_template("landing.html", stats=stats)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return go_home()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        if role not in ("applicant", "employer"):       # nobody can self-register as admin
            flash("Choose Applicant or Employer.", "danger")
        elif not name or "@" not in email or len(password) < 6:
            flash("Enter your name, a valid email and a password of 6+ characters.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("This email is already registered.", "danger")
        else:
            user = User(name=name, email=email, role=role,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return go_home()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return go_home()
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if not user or not check_password_hash(user.password_hash, request.form.get("password", "")):
            flash("Wrong email or password.", "danger")
        elif user.suspended:
            flash("This account is suspended. Please contact the admin.", "danger")
        else:
            login_user(user)
            return go_home()
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("login"))


# -------------------------------------------------------------- employer
def owned_job(job_id):
    job = db.get_or_404(Job, job_id)
    if job.employer_id != current_user.id:
        abort(403)
    return job


def read_job_form(job):
    title = request.form.get("title", "").strip()
    desc = request.form.get("description", "").strip()
    skills = ", ".join(s.strip() for s in request.form.get("skills", "").split(",") if s.strip())
    if not (title and desc and skills):
        flash("Title, description and at least one skill are required.", "danger")
        return False
    job.title, job.description, job.skills = title, desc, skills
    return True


@app.route("/employer")
@role_required("employer")
def employer_dashboard():
    jobs = Job.query.filter_by(employer_id=current_user.id).order_by(Job.created_at.desc()).all()
    apps = [x for j in jobs for x in j.applications]
    kpis = {"open": sum(j.is_open for j in jobs), "applicants": len(apps),
            "shortlisted": sum(x.status == "Shortlisted" for x in apps),
            "best": max((x.score for x in apps), default=0)}
    return render_template("employer_dashboard.html", jobs=jobs, kpis=kpis)


@app.route("/employer/jobs/new", methods=["GET", "POST"])
@role_required("employer")
def job_new():
    job = Job(employer_id=current_user.id)
    if request.method == "POST" and read_job_form(job):
        db.session.add(job)
        db.session.commit()
        flash("Job posted.", "success")
        return redirect(url_for("employer_dashboard"))
    return render_template("job_form.html", job=job, editing=False)


@app.route("/employer/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@role_required("employer")
def job_edit(job_id):
    job = owned_job(job_id)
    if request.method == "POST" and read_job_form(job):
        db.session.commit()
        flash("Job updated.", "success")
        return redirect(url_for("employer_dashboard"))
    return render_template("job_form.html", job=job, editing=True)


@app.route("/employer/jobs/<int:job_id>/toggle", methods=["POST"])
@role_required("employer")
def job_toggle(job_id):
    job = owned_job(job_id)
    job.is_open = not job.is_open
    db.session.commit()
    flash("Job is now " + ("open." if job.is_open else "closed."), "success")
    return redirect(url_for("employer_dashboard"))


@app.route("/employer/jobs/<int:job_id>/applicants")
@role_required("employer")
def job_applicants(job_id):
    job = owned_job(job_id)
    min_score = request.args.get("min", 0, type=float)
    apps = (Application.query.filter(Application.job_id == job.id, Application.score >= min_score)
            .order_by(Application.score.desc(), Application.applied_at).all())
    return render_template("job_applicants.html", job=job, apps=apps, min_score=min_score,
                           statuses=STATUSES)


def owned_application(app_id):
    a = db.get_or_404(Application, app_id)
    if a.job.employer_id != current_user.id:
        abort(403)
    return a


@app.route("/employer/applications/<int:app_id>/resume")
@role_required("employer")
def resume_download(app_id):
    a = owned_application(app_id)
    return send_from_directory(app.config["UPLOAD_FOLDER"], a.resume_file, as_attachment=True,
                               download_name=a.original_name)


@app.route("/employer/applications/<int:app_id>")
@role_required("employer")
def candidate_detail(app_id):
    a = owned_application(app_id)
    return render_template("candidate.html", a=a, r=report_for(a), statuses=STATUSES)


@app.route("/employer/applications/<int:app_id>/status", methods=["POST"])
@role_required("employer")
def application_status(app_id):
    a = owned_application(app_id)
    if request.form.get("status") in STATUSES:
        a.status = request.form["status"]
        db.session.commit()
        flash(f"{a.applicant.name} marked as {a.status}.", "success")
    return redirect(url_for("job_applicants", job_id=a.job_id))


# ------------------------------------------------------------- applicant
def report_for(a):
    """Re-score a stored application so detail pages can show the full breakdown."""
    try:
        text = extract_text(os.path.join(app.config["UPLOAD_FOLDER"], a.resume_file))
    except Exception:
        text = ""
    return analyse(text, a.job.description, a.job.skills)


def is_pdf(f):
    head = f.stream.read(5)
    f.stream.seek(0)
    return bool(f.filename) and f.filename.lower().endswith(".pdf") and head == b"%PDF-"


@app.route("/jobs")
def job_board():
    if current_user.is_authenticated and current_user.role != "applicant":
        return go_home()
    q = request.args.get("q", "").strip()
    query = Job.query.filter_by(is_open=True)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Job.title.ilike(like), Job.skills.ilike(like),
                                    Job.description.ilike(like)))
    applied = ({a.job_id for a in Application.query.filter_by(applicant_id=current_user.id)}
               if current_user.is_authenticated else set())
    return render_template("job_board.html", jobs=query.order_by(Job.created_at.desc()).all(),
                           applied=applied, q=q)


@app.route("/jobs/<int:job_id>")
def job_detail(job_id):
    job = db.get_or_404(Job, job_id)
    mine = None
    if current_user.is_authenticated and current_user.role == "applicant":
        mine = Application.query.filter_by(job_id=job.id, applicant_id=current_user.id).first()
    return render_template("job_detail.html", job=job, mine=mine)


@app.route("/jobs/<int:job_id>/apply", methods=["POST"])
@role_required("applicant")
def apply(job_id):
    job = db.get_or_404(Job, job_id)
    back = redirect(url_for("job_detail", job_id=job.id))
    if not job.is_open:
        flash("This job is closed.", "warning")
        return back
    if Application.query.filter_by(job_id=job.id, applicant_id=current_user.id).first():
        flash("You have already applied to this job.", "warning")
        return back

    f = request.files.get("resume")
    if not f or not f.filename:
        flash("Please choose a PDF resume.", "danger")
        return back
    if not is_pdf(f):                                   # extension AND content check
        flash("Only PDF files are accepted.", "danger")
        return back

    stored = uuid.uuid4().hex + ".pdf"
    path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
    f.save(path)
    try:
        text = extract_text(path)
    except Exception:
        os.remove(path)
        flash("We could not read that PDF. Please upload a different file.", "danger")
        return back

    result = analyse(text, job.description, job.skills)
    db.session.add(Application(
        job_id=job.id, applicant_id=current_user.id, resume_file=stored,
        original_name=os.path.basename(f.filename)[:200], score=result["score"],
        matched=",".join(result["matched"]), missing=",".join(result["missing"])))
    try:
        db.session.commit()
    except IntegrityError:                      # database-level duplicate guard
        db.session.rollback()
        os.remove(path)
        flash("You have already applied to this job.", "warning")
        return back
    flash(f"Application sent. Your match score is {result['score']}%.", "success")
    if not text.strip():
        flash("No readable text was found (is the PDF a scan?). Your score is 0%.", "warning")
    return redirect(url_for("my_applications"))


@app.route("/my-applications")
@role_required("applicant")
def my_applications():
    apps = (Application.query.filter_by(applicant_id=current_user.id)
            .order_by(Application.applied_at.desc()).all())
    return render_template("my_applications.html", apps=apps)


@app.route("/my-applications/<int:app_id>")
@role_required("applicant")
def my_application(app_id):
    a = db.get_or_404(Application, app_id)
    if a.applicant_id != current_user.id:
        abort(403)
    return render_template("application_report.html", a=a, r=report_for(a))


@app.route("/analyzer", methods=["GET", "POST"])
@role_required("applicant")
def analyzer():
    """Score a resume against a job without applying. The PDF is deleted straight after."""
    jobs = Job.query.filter_by(is_open=True).order_by(Job.title).all()
    job = report = None
    if request.method == "POST":
        job = db.session.get(Job, request.form.get("job_id", 0, type=int))
        f = request.files.get("resume")
        if not job:
            flash("Choose a job to compare your resume with.", "danger")
        elif not f or not is_pdf(f):
            flash("Please upload a PDF resume.", "danger")
        else:
            tmp = os.path.join(app.config["UPLOAD_FOLDER"], "tmp_" + uuid.uuid4().hex + ".pdf")
            f.save(tmp)
            try:
                report = analyse(extract_text(tmp), job.description, job.skills)
            except Exception:
                flash("We could not read that PDF. Please upload a different file.", "danger")
            finally:
                os.remove(tmp)
    return render_template("analyzer.html", jobs=jobs, job=job, r=report)


# ------------------------------------------------------------------ chat
@app.route("/api/chat", methods=["POST"])
def api_chat():
    message = str((request.get_json(silent=True) or {}).get("message", ""))[:300]
    return jsonify(chatbot.reply(message))


# ----------------------------------------------------------------- admin
def remove_files(apps):
    for a in apps:
        try:
            os.remove(os.path.join(app.config["UPLOAD_FOLDER"], a.resume_file))
        except OSError:
            pass


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    today = now().date()
    days = [today - timedelta(d) for d in range(6, -1, -1)]
    recent = Application.query.filter(Application.applied_at >= now() - timedelta(days=7)).all()
    counts = [sum(1 for a in recent if a.applied_at.date() == d) for d in days]
    by_status = dict(db.session.query(Application.status, func.count()).group_by(Application.status))
    total_apps = Application.query.count()
    pct = lambda k: by_status.get(k, 0) / total_apps * 100 if total_apps else 0
    donut_a = pct("Shortlisted")
    donut_b = donut_a + pct("Pending")
    scores = [s for (s,) in db.session.query(Application.score)]
    buckets = [("Strong, 60%+", sum(s >= 60 for s in scores), "good"),
               ("Partial, 35-60%", sum(35 <= s < 60 for s in scores), "mid"),
               ("Weak, under 35%", sum(s < 35 for s in scores), "low")]
    return render_template(
        "admin_dashboard.html",
        total_users=User.query.filter(User.role != "admin").count(),
        employers=User.query.filter_by(role="employer").count(),
        applicants=User.query.filter_by(role="applicant").count(),
        open_jobs=Job.query.filter_by(is_open=True).count(), total_jobs=Job.query.count(),
        total_apps=total_apps, avg_score=db.session.query(func.avg(Application.score)).scalar() or 0,
        by_status=by_status, donut_a=donut_a, donut_b=donut_b, buckets=buckets,
        top_jobs=sorted(Job.query.all(), key=lambda j: -len(j.applications))[:5],
        new_users=User.query.filter(User.role != "admin").order_by(User.created_at.desc()).limit(6).all(),
        new_apps=Application.query.order_by(Application.applied_at.desc()).limit(6).all(),
        chart=list(zip([d.strftime("%a") for d in days], counts)), peak=max(counts + [1]))


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    query = User.query.filter(User.role != "admin")
    if role in ("applicant", "employer"):
        query = query.filter_by(role=role)
    if q:
        query = query.filter(db.or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    return render_template("admin_users.html", users=query.order_by(User.created_at.desc()).all(),
                           q=q, role=role)


@app.route("/admin/jobs")
@role_required("admin")
def admin_jobs():
    return render_template("admin_jobs.html", jobs=Job.query.order_by(Job.created_at.desc()).all())


@app.route("/admin/applications")
@role_required("admin")
def admin_applications():
    status = request.args.get("status", "")
    query = Application.query
    if status in STATUSES:
        query = query.filter_by(status=status)
    return render_template("admin_applications.html", status=status, statuses=STATUSES,
                           apps=query.order_by(Application.applied_at.desc()).limit(200).all())


def managed_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == "admin":
        abort(403)
    return user


@app.route("/admin/users/<int:user_id>/suspend", methods=["POST"])
@role_required("admin")
def admin_suspend(user_id):
    user = managed_user(user_id)
    user.suspended = not user.suspended
    db.session.commit()
    flash(f"{user.name} {'suspended' if user.suspended else 'reinstated'}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_user(user_id):
    user = managed_user(user_id)
    remove_files(list(user.applications) + [a for j in user.jobs for a in j.applications])
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/jobs/<int:job_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_toggle_job(job_id):
    job = db.get_or_404(Job, job_id)
    job.is_open = not job.is_open
    db.session.commit()
    flash(f"Job is now {'open' if job.is_open else 'closed'}.", "success")
    return redirect(url_for("admin_jobs"))


@app.route("/admin/jobs/<int:job_id>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_job(job_id):
    job = db.get_or_404(Job, job_id)
    remove_files(job.applications)
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "success")
    return redirect(url_for("admin_jobs"))


# ---------------------------------------------------------------- errors
@app.errorhandler(403)
def e403(_):
    return render_template("error.html", code=403, title="Access denied",
                           text="Your account is not allowed to open this page."), 403


@app.errorhandler(404)
def e404(_):
    return render_template("error.html", code=404, title="Page not found",
                           text="That page does not exist."), 404


@app.errorhandler(413)
def e413(_):
    return render_template("error.html", code=413, title="File too large",
                           text="Resumes must be 5 MB or smaller."), 413


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
