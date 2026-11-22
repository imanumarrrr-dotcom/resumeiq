"""Create (or reset) the admin account:  python create_admin.py"""
import getpass
from werkzeug.security import generate_password_hash
from app import app
from models import User, db

import os
# Docker: set ADMIN_EMAIL / ADMIN_PASSWORD (and optionally ADMIN_NAME) to skip the prompts
name = os.environ.get("ADMIN_NAME") or ("Admin" if os.environ.get("ADMIN_EMAIL") else input("Admin name: ").strip() or "Admin")
email = (os.environ.get("ADMIN_EMAIL") or input("Admin email: ")).strip().lower()
password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password (min 6 chars): ")
if "@" not in email or len(password) < 6:
    raise SystemExit("Invalid email or password too short.")

with app.app_context():
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(name=name, email=email, role="admin", password_hash="")
        db.session.add(user)
    user.role, user.name, user.suspended = "admin", name, False
    user.password_hash = generate_password_hash(password)
    db.session.commit()
    print("Admin ready:", email)
