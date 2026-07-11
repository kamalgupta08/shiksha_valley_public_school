from functools import wraps
from datetime import date
from flask import session, redirect, url_for, flash
from extensions import db
from models import Student, Transaction


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


def recompute_balances(student):
    """Recalculates balance_after for every transaction of a student, in true
    chronological order (by entry date, then by when it was actually recorded).

    This matters because deposits can now be backdated — someone might enter
    today a payment that was actually received last week. Without this, that
    backdated row would show a 'balance after' snapshot that doesn't line up
    with the rows around it. Call this after inserting or changing any
    transaction for a student.
    """
    txns = (
        student.transactions
        .order_by(Transaction.date, Transaction.created_at, Transaction.id)
        .all()
    )
    running = 0.0
    for t in txns:
        if t.txn_type == "CHARGE":
            running += float(t.amount)
        elif t.txn_type == "PAYMENT":
            running -= float(t.amount)
        elif t.txn_type == "ADJUSTMENT":
            running += float(t.amount)
        t.balance_after = round(running, 2)
    db.session.add_all(txns)
