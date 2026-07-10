from functools import wraps
from datetime import date
from flask import session, redirect, url_for, flash
from models import Student


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped


def generate_admission_number():
    """e.g. SVPS2026001, SVPS2026002 ... resets prefix each calendar year."""
    year = date.today().year
    prefix = f"SVPS{year}"
    last = (
        Student.query.filter(Student.admission_number.like(f"{prefix}%"))
        .order_by(Student.id.desc())
        .first()
    )
    if last:
        last_seq = int(last.admission_number.replace(prefix, ""))
        next_seq = last_seq + 1
    else:
        next_seq = 1
    return f"{prefix}{next_seq:03d}"
