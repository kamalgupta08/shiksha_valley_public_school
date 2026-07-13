from functools import wraps
from calendar import monthrange
from datetime import date
from flask import session, redirect, url_for, flash
from extensions import db
from models import Student, Transaction, FeeStructure


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


def add_months(source_date, months):
    """Adds a whole number of calendar months to a date, clamping the day
    to the target month's length (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def generate_monthly_tuition_charges(student, upto_date=None):
    """Ensures a tuition charge exists for every month from the student's
    admission month through upto_date (default: today), using their CURRENT
    class's monthly tuition rate. Idempotent — safe to call as often as you
    like; it only ever fills in missing months, never duplicates a month.

    Backward-compatibility note: a tuition charge recorded before per-month
    tracking existed (fee_period is null) is treated as covering the
    admission month, so upgrading doesn't double-charge that first month.

    Returns how many new charges were created.
    """
    upto_date = upto_date or date.today()
    if not student.is_active or not student.admission_date:
        return 0

    fee_row = FeeStructure.query.filter_by(class_name=student.class_name).first()
    if not fee_row or float(fee_row.tuition_fee) == 0:
        return 0

    all_charges = [t for t in student.transactions if t.txn_type == "CHARGE"]
    existing_periods = {t.fee_period for t in all_charges if t.fee_period is not None}

    admission_period = date(student.admission_date.year, student.admission_date.month, 1)
    if admission_period not in existing_periods:
        has_legacy_tuition_charge = any(
            t.fee_period is None and "Tuition" in (t.category or "") for t in all_charges
        )
        if has_legacy_tuition_charge:
            existing_periods.add(admission_period)

    period = admission_period
    last_period = date(upto_date.year, upto_date.month, 1)
    created = 0
    while period <= last_period:
        if period not in existing_periods:
            charge_date = student.admission_date if period == admission_period else period
            db.session.add(Transaction(
                student_id=student.id,
                txn_type="CHARGE",
                category=f"Tuition Fee — {period.strftime('%b %Y')}",
                amount=float(fee_row.tuition_fee),
                date=charge_date,
                remarks="Auto-generated monthly tuition",
                balance_after=0,
                fee_period=period,
            ))
            created += 1
        period = add_months(period, 1)

    if created:
        db.session.flush()
    return created


def generate_all_due_monthly_fees():
    """Runs generate_monthly_tuition_charges for every active student and
    commits once at the end. Returns (total_charges_created, students_affected)."""
    students = Student.query.filter_by(is_active=True).all()
    total_created = 0
    students_affected = 0
    for student in students:
        created = generate_monthly_tuition_charges(student)
        if created:
            recompute_balances(student)
            total_created += created
            students_affected += 1
    if total_created:
        db.session.commit()
    return total_created, students_affected
