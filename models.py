from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)          # applicant | employer | admin
    suspended = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now)

    jobs = db.relationship("Job", backref="employer", cascade="all, delete-orphan")
    applications = db.relationship("Application", backref="applicant", cascade="all, delete-orphan")

    @property
    def is_active(self):                                      # Flask-Login uses this
        return not self.suspended


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    skills = db.Column(db.Text, nullable=False)               # comma-separated
    is_open = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now)

    applications = db.relationship("Application", backref="job", cascade="all, delete-orphan")

    @property
    def skill_list(self):
        return [s.strip() for s in self.skills.split(",") if s.strip()]


class Application(db.Model):
    __table_args__ = (db.UniqueConstraint("job_id", "applicant_id", name="one_application_per_job"),)
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False)
    applicant_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    resume_file = db.Column(db.String(100), nullable=False)   # random name on disk
    original_name = db.Column(db.String(200), nullable=False)
    score = db.Column(db.Float, default=0.0, nullable=False)
    matched = db.Column(db.Text, default="")
    missing = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="Pending", nullable=False)
    applied_at = db.Column(db.DateTime, default=now)

    @property
    def matched_list(self):
        return [s for s in (self.matched or "").split(",") if s]

    @property
    def missing_list(self):
        return [s for s in (self.missing or "").split(",") if s]
