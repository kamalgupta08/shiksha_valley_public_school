import csv
import io
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, Response
)
from sqlalchemy import inspect, text

from config import Config
from extensions import db
from models import FeeStructure, Student, Transaction, StudentNote
from utils import (
    login_required, generate_admission_number, recompute_balances,
    generate_monthly_tuition_charges, generate_all_due_monthly_fees,
)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _ensure_schema_migrations()
        _seed_fee_structure_if_empty()

    register_routes(app)
    _register_template_filters(app)
    return app


def _ensure_schema_migrations():
    """db.create_all() only creates tables that don't exist yet — it never adds
    columns to a table that's already there. This patches existing databases
    (e.g. already-deployed ones) with columns added by later versions of the app,
    without touching any existing data."""
    inspector = inspect(db.engine)
    if "transactions" not in inspector.get_table_names():
        return  # fresh database — create_all already built it with every column
    existing_cols = {c["name"] for c in inspector.get_columns("transactions")}
    if "fee_period" not in existing_cols:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN fee_period DATE"))
            conn.commit()


def _register_template_filters(app):
    @app.template_filter("ist")
    def ist_filter(dt):
        """Renders a stored UTC timestamp as 'DD Mon YYYY, HH:MM AM/PM' in India time,
        so the ledger shows when a deposit actually happened, regardless of where the
        server itself is hosted."""
        if dt is None:
            return "—"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
        return local_dt.strftime("%d %b %Y, %I:%M %p")

    @app.template_global("class_label")
    def class_label(class_name):
        """'Nursery', 'KG', 'UKG' display as-is; numeric classes get a 'Class' prefix."""
        if class_name and class_name.isdigit():
            return f"Class {class_name}"
        return class_name


def _seed_fee_structure_if_empty():
    """Ensures every class in CLASS_LIST has at least a placeholder fee row.
    Only ADDS rows for classes that don't exist yet — never touches or removes
    a class you've already customized, so this is safe to run on every
    deploy/restart, even after you've edited real fee amounts."""
    defaults = {
        "Nursery": dict(admission_fee=1800, tuition_fee=800, dress_fee=1200, book_fee=1200, misc_fee=800),
        "KG": dict(admission_fee=2000, tuition_fee=1000, dress_fee=1500, book_fee=1500, misc_fee=1000),
        "UKG": dict(admission_fee=2200, tuition_fee=1100, dress_fee=1500, book_fee=1700, misc_fee=1000),
        "1": dict(admission_fee=2500, tuition_fee=1200, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "2": dict(admission_fee=2500, tuition_fee=1200, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "3": dict(admission_fee=2500, tuition_fee=1250, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "4": dict(admission_fee=2500, tuition_fee=1250, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "5": dict(admission_fee=3000, tuition_fee=1300, dress_fee=1500, book_fee=2500, misc_fee=1200),
        "6": dict(admission_fee=3000, tuition_fee=1400, dress_fee=1500, book_fee=2500, misc_fee=1500),
        "7": dict(admission_fee=3000, tuition_fee=1400, dress_fee=1500, book_fee=2800, misc_fee=1500),
    }
    existing_classes = {row.class_name for row in FeeStructure.query.all()}
    added = False
    for class_name, fees in defaults.items():
        if class_name not in existing_classes:
            db.session.add(FeeStructure(class_name=class_name, **fees))
            added = True
    if added:
        db.session.commit()


def register_routes(app):

    @app.before_request
    def _auto_generate_monthly_fees():
        if request.endpoint in (None, "static") or not session.get("logged_in"):
            return
        today_str = date.today().isoformat()
        if session.get("fees_generated_on") == today_str:
            return
        session["fees_generated_on"] = today_str
        total_created, students_affected = generate_all_due_monthly_fees()
        if total_created:
            flash(
                f"Generated {total_created} monthly tuition charge(s) for {students_affected} student(s) "
                f"who were due.", "info"
            )

    # ---------- Public site ----------
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if username == app.config["ADMIN_USERNAME"] and password == app.config["ADMIN_PASSWORD"]:
                session["logged_in"] = True
                session["username"] = username
                flash("Logged in successfully.", "success")
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/admin/generate-monthly-fees", methods=["POST"])
    @login_required
    def manual_generate_monthly_fees():
        total_created, students_affected = generate_all_due_monthly_fees()
        if total_created:
            flash(f"Generated {total_created} monthly tuition charge(s) for {students_affected} student(s).", "success")
        else:
            flash("Everyone is already up to date on monthly tuition.", "info")
        return redirect(url_for("dashboard"))

    # ---------- Dashboard ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        students = Student.query.filter_by(is_active=True).all()
        total_students = len(students)
        total_pending = round(sum(s.balance for s in students if s.balance > 0), 2)
        total_collected = round(
            sum(float(t.amount) for t in Transaction.query.filter_by(txn_type="PAYMENT").all()), 2
        )

        # "Today's Collection" is based on the payment date staff selected when
        # recording the deposit — NOT when it was typed into the system. That
        # way, entering last month's payment today doesn't inflate today's total.
        todays_payments = Transaction.query.filter(
            Transaction.txn_type == "PAYMENT",
            Transaction.date == date.today(),
        ).all()
        todays_collection = round(sum(float(t.amount) for t in todays_payments), 2)
        todays_collection_count = len(todays_payments)

        class_counts = {}
        for s in students:
            class_counts[s.class_name] = class_counts.get(s.class_name, 0) + 1

        recent_payments = (
            Transaction.query.filter_by(txn_type="PAYMENT")
            .order_by(Transaction.created_at.desc())
            .limit(8)
            .all()
        )

        return render_template(
            "dashboard.html",
            total_students=total_students,
            total_pending=total_pending,
            total_collected=total_collected,
            todays_collection=todays_collection,
            todays_collection_count=todays_collection_count,
            class_counts=class_counts,
            recent_payments=recent_payments,
            today=date.today().isoformat(),
        )

    @app.route("/reports/daily-collection")
    @login_required
    def daily_collection_report():
        date_str = request.args.get("date", "").strip()
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
        except ValueError:
            report_date = date.today()

        payments = (
            Transaction.query.filter_by(txn_type="PAYMENT", date=report_date)
            .order_by(Transaction.created_at)
            .all()
        )

        mode_totals = {}
        grand_total = 0.0
        for t in payments:
            mode = t.mode or "Other"
            mode_totals[mode] = mode_totals.get(mode, 0.0) + float(t.amount)
            grand_total += float(t.amount)

        return render_template(
            "daily_collection_report.html",
            report_date=report_date,
            payments=payments,
            mode_totals=mode_totals,
            grand_total=round(grand_total, 2),
            today=date.today().isoformat(),
        )

    @app.route("/reports/daily-collection/export")
    @login_required
    def export_daily_collection():
        date_str = request.args.get("date", "").strip()
        try:
            report_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
        except ValueError:
            report_date = date.today()

        payments = (
            Transaction.query.filter_by(txn_type="PAYMENT", date=report_date)
            .order_by(Transaction.created_at)
            .all()
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Admission No", "Student", "Class", "Mode", "Amount (Rs)", "Entered On", "Remarks"])
        grand_total = 0.0
        for t in payments:
            writer.writerow([
                t.student.admission_number,
                t.student.name,
                f"{t.student.class_name} - {t.student.section}",
                t.mode or "",
                float(t.amount),
                t.created_at.strftime("%d %b %Y %I:%M %p") if t.created_at else "",
                t.remarks or "",
            ])
            grand_total += float(t.amount)
        writer.writerow([])
        writer.writerow(["", "", "", "TOTAL", grand_total, "", ""])

        output = buffer.getvalue()
        filename = f"daily_collection_{report_date.isoformat()}.csv"
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ---------- Students ----------
    @app.route("/students/add", methods=["GET", "POST"])
    @login_required
    def add_student():
        if request.method == "POST":
            class_name = request.form.get("class_name")
            fee_row = FeeStructure.query.filter_by(class_name=class_name).first()
            if not fee_row:
                flash("No fee structure found for that class. Set it up under Fee Structure first.", "danger")
                return redirect(url_for("add_student"))

            dob_str = request.form.get("dob")
            dob_val = datetime.strptime(dob_str, "%Y-%m-%d").date() if dob_str else None

            admission_date_str = request.form.get("admission_date", "").strip()
            try:
                admission_date_val = (
                    datetime.strptime(admission_date_str, "%Y-%m-%d").date()
                    if admission_date_str else date.today()
                )
            except ValueError:
                admission_date_val = date.today()

            student = Student(
                admission_number=generate_admission_number(),
                name=request.form.get("name", "").strip(),
                dob=dob_val,
                gender=request.form.get("gender"),
                class_name=class_name,
                section=request.form.get("section"),
                guardian_name=request.form.get("guardian_name", "").strip(),
                contact_number=request.form.get("contact_number", "").strip(),
                address=request.form.get("address", "").strip(),
                admission_date=admission_date_val,
            )
            db.session.add(student)
            db.session.flush()  # get student.id before commit

            def line_amount(field_name, default):
                raw = request.form.get(field_name, "").strip()
                try:
                    return float(raw) if raw else float(default)
                except ValueError:
                    return float(default)

            # One-time charges only here. Tuition is handled separately below by
            # generate_monthly_tuition_charges, which also covers the admission
            # month itself and recurs automatically every month after.
            line_items = [
                ("Admission Fee", line_amount("admission_fee", fee_row.admission_fee)),
                ("Dress Fee", line_amount("dress_fee", fee_row.dress_fee)),
                ("Book Fee", line_amount("book_fee", fee_row.book_fee)),
                ("Misc. Fee", line_amount("misc_fee", fee_row.misc_fee)),
            ]
            for category, amount in line_items:
                if amount == 0:
                    continue
                db.session.add(Transaction(
                    student_id=student.id,
                    txn_type="CHARGE",
                    category=category,
                    amount=amount,
                    date=admission_date_val,
                    remarks=f"New admission — Class {class_name} {student.section}",
                    balance_after=0,
                ))

            db.session.flush()
            # Backdated admissions correctly back-fill every owed month up to today.
            generate_monthly_tuition_charges(student, upto_date=date.today())
            recompute_balances(student)
            db.session.commit()

            flash(f"{student.name} admitted successfully. Admission No: {student.admission_number}", "success")
            return redirect(url_for("student_ledger", student_id=student.id))

        return render_template(
            "add_student.html",
            classes=app.config["CLASS_LIST"],
            sections=app.config["SECTION_LIST"],
            today=date.today().isoformat(),
        )

    @app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_student(student_id):
        student = Student.query.get_or_404(student_id)

        if request.method == "POST":
            dob_str = request.form.get("dob")
            student.name = request.form.get("name", "").strip()
            student.gender = request.form.get("gender")
            student.dob = datetime.strptime(dob_str, "%Y-%m-%d").date() if dob_str else None
            student.class_name = request.form.get("class_name")
            student.section = request.form.get("section")
            student.guardian_name = request.form.get("guardian_name", "").strip()
            student.contact_number = request.form.get("contact_number", "").strip()
            student.address = request.form.get("address", "").strip()
            db.session.commit()
            flash(f"{student.name}'s details updated.", "success")
            return redirect(url_for("student_ledger", student_id=student.id))

        return render_template(
            "edit_student.html",
            student=student,
            classes=app.config["CLASS_LIST"],
            sections=app.config["SECTION_LIST"],
        )

    @app.route("/students")
    @login_required
    def students_list():
        class_filter = request.args.get("class_name", "")
        section_filter = request.args.get("section", "")
        search = request.args.get("q", "").strip()

        query = Student.query.filter_by(is_active=True)
        if class_filter:
            query = query.filter_by(class_name=class_filter)
        if section_filter:
            query = query.filter_by(section=section_filter)
        if search:
            like = f"%{search}%"
            query = query.filter(
                db.or_(Student.name.ilike(like), Student.admission_number.ilike(like))
            )

        students = query.order_by(Student.class_name, Student.section, Student.name).all()
        return render_template(
            "students_list.html",
            students=students,
            classes=app.config["CLASS_LIST"],
            sections=app.config["SECTION_LIST"],
            class_filter=class_filter,
            section_filter=section_filter,
            search=search,
            today=date.today().isoformat(),
        )

    @app.route("/students/export")
    @login_required
    def export_students():
        class_filter = request.args.get("class_name", "")
        section_filter = request.args.get("section", "")

        query = Student.query.filter_by(is_active=True)
        if class_filter:
            query = query.filter_by(class_name=class_filter)
        if section_filter:
            query = query.filter_by(section=section_filter)
        students = query.order_by(Student.class_name, Student.section, Student.name).all()

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "Admission No", "Name", "Class", "Section", "Guardian",
            "Contact", "Admission Date", "Balance Due (Rs)"
        ])
        for s in students:
            writer.writerow([
                s.admission_number, s.name, s.class_name, s.section,
                s.guardian_name or "", s.contact_number or "",
                s.admission_date.isoformat() if s.admission_date else "",
                s.balance,
            ])

        output = buffer.getvalue()
        filename = f"students_export_{date.today().isoformat()}.csv"
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ---------- Student ledger / deposits ----------
    @app.route("/students/<int:student_id>")
    @login_required
    def student_ledger(student_id):
        student = Student.query.get_or_404(student_id)
        transactions = student.transactions.order_by(Transaction.date, Transaction.created_at, Transaction.id).all()
        return render_template(
            "student_ledger.html",
            student=student,
            transactions=transactions,
            today=date.today().isoformat(),
        )

    @app.route("/students/<int:student_id>/deposit", methods=["POST"])
    @login_required
    def deposit_fee(student_id):
        student = Student.query.get_or_404(student_id)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        if amount <= 0:
            if is_ajax:
                return jsonify({"ok": False, "error": "Enter a valid deposit amount."}), 400
            flash("Enter a valid deposit amount.", "danger")
            return redirect(url_for("student_ledger", student_id=student.id))

        date_str = request.form.get("date", "").strip()
        try:
            txn_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
        except ValueError:
            txn_date = date.today()
        if txn_date > date.today():
            txn_date = date.today()  # no future-dating

        txn = Transaction(
            student_id=student.id,
            txn_type="PAYMENT",
            category="Deposit",
            amount=amount,
            date=txn_date,
            mode=request.form.get("mode", "Cash"),
            remarks=request.form.get("remarks", ""),
            balance_after=0,  # placeholder — recompute_balances sets the real value below
        )
        db.session.add(txn)
        db.session.flush()
        recompute_balances(student)
        db.session.commit()

        if is_ajax:
            return jsonify({
                "ok": True,
                "balance": student.balance,
                "message": f"Deposit of Rs {amount:,.2f} recorded for {student.name}.",
            })

        flash(f"Deposit of Rs {amount:,.2f} recorded for {student.name}.", "success")
        return redirect(url_for("student_ledger", student_id=student.id))

    @app.route("/students/<int:student_id>/note", methods=["POST"])
    @login_required
    def add_student_note(student_id):
        student = Student.query.get_or_404(student_id)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        note_text = request.form.get("note", "").strip()

        if not note_text:
            if is_ajax:
                return jsonify({"ok": False, "error": "Remark can't be empty."}), 400
            flash("Remark can't be empty.", "danger")
            return redirect(url_for("student_ledger", student_id=student.id))

        note = StudentNote(student_id=student.id, note=note_text)
        db.session.add(note)
        db.session.commit()

        if is_ajax:
            return jsonify({"ok": True, "note": note.note, "created_at": note.created_at.strftime("%d %b %Y")})

        flash("Remark added.", "success")
        return redirect(url_for("student_ledger", student_id=student.id))

    @app.route("/students/<int:student_id>/adjust", methods=["POST"])
    @login_required
    def adjust_fee(student_id):
        student = Student.query.get_or_404(student_id)
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        if amount == 0:
            flash("Enter a non-zero adjustment amount.", "danger")
            return redirect(url_for("student_ledger", student_id=student.id))

        reason = request.form.get("reason", "").strip() or "Fee adjustment"
        category = "Discount" if amount < 0 else "Extra Charge"

        txn = Transaction(
            student_id=student.id,
            txn_type="ADJUSTMENT",
            category=category,
            amount=amount,
            date=date.today(),
            remarks=reason,
            balance_after=0,
        )
        db.session.add(txn)
        db.session.flush()
        recompute_balances(student)
        db.session.commit()

        verb = "reduced" if amount < 0 else "increased"
        flash(f"{student.name}'s fee {verb} by Rs {abs(amount):,.2f}.", "success")
        return redirect(url_for("student_ledger", student_id=student.id))

    @app.route("/transactions/<int:txn_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_transaction(txn_id):
        txn = Transaction.query.get_or_404(txn_id)
        student = txn.student

        if request.method == "POST":
            try:
                amount = float(request.form.get("amount", 0))
            except ValueError:
                amount = float(txn.amount)

            date_str = request.form.get("date", "").strip()
            try:
                if date_str:
                    txn.date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                pass

            txn.amount = amount
            txn.remarks = request.form.get("remarks", "").strip()
            if txn.txn_type == "PAYMENT":
                txn.mode = request.form.get("mode", txn.mode)

            db.session.flush()
            recompute_balances(student)
            db.session.commit()
            flash("Entry updated.", "success")
            return redirect(url_for("student_ledger", student_id=student.id))

        return render_template("edit_transaction.html", txn=txn, student=student, today=date.today().isoformat())

    @app.route("/transactions/<int:txn_id>/delete", methods=["POST"])
    @login_required
    def delete_transaction(txn_id):
        txn = Transaction.query.get_or_404(txn_id)
        student = txn.student
        student_id = student.id
        db.session.delete(txn)
        db.session.flush()
        recompute_balances(student)
        db.session.commit()
        flash("Entry deleted.", "success")
        return redirect(url_for("student_ledger", student_id=student_id))

    @app.route("/students/<int:student_id>/promote", methods=["GET", "POST"])
    @login_required
    def promote_student(student_id):
        student = Student.query.get_or_404(student_id)

        if request.method == "POST":
            new_class = request.form.get("class_name")
            new_section = request.form.get("section")
            fee_row = FeeStructure.query.filter_by(class_name=new_class).first()
            if not fee_row:
                flash("No fee structure for that class yet.", "danger")
                return redirect(url_for("promote_student", student_id=student.id))

            student.class_name = new_class
            student.section = new_section

            def line_amount(field_name, default):
                raw = request.form.get(field_name, "").strip()
                try:
                    return float(raw) if raw else float(default)
                except ValueError:
                    return float(default)

            # No admission fee on promotion, and no immediate tuition charge either —
            # generate_monthly_tuition_charges (below) picks up the new class's rate
            # automatically starting from whatever month isn't already billed.
            line_items = [
                ("Dress Fee", line_amount("dress_fee", fee_row.dress_fee)),
                ("Book Fee", line_amount("book_fee", fee_row.book_fee)),
                ("Misc. Fee", line_amount("misc_fee", fee_row.misc_fee)),
            ]
            for category, amount in line_items:
                if amount == 0:
                    continue
                db.session.add(Transaction(
                    student_id=student.id,
                    txn_type="CHARGE",
                    category=f"{category} — Class {new_class}",
                    amount=amount,
                    date=date.today(),
                    remarks=f"Promoted to Class {new_class} {new_section}",
                    balance_after=0,
                ))

            db.session.flush()
            generate_monthly_tuition_charges(student, upto_date=date.today())
            recompute_balances(student)
            db.session.commit()
            flash(f"{student.name} promoted to Class {new_class} {new_section}.", "success")
            return redirect(url_for("student_ledger", student_id=student.id))

        return render_template(
            "promote_student.html",
            student=student,
            classes=app.config["CLASS_LIST"],
            sections=app.config["SECTION_LIST"],
        )

    # ---------- Fee structure ----------
    @app.route("/fee-structure", methods=["GET", "POST"])
    @login_required
    def fee_structure():
        if request.method == "POST":
            class_name = request.form.get("class_name")
            row = FeeStructure.query.filter_by(class_name=class_name).first()
            if not row:
                row = FeeStructure(class_name=class_name)
                db.session.add(row)
            row.admission_fee = float(request.form.get("admission_fee", 0))
            row.tuition_fee = float(request.form.get("tuition_fee", 0))
            row.dress_fee = float(request.form.get("dress_fee", 0))
            row.book_fee = float(request.form.get("book_fee", 0))
            row.misc_fee = float(request.form.get("misc_fee", 0))
            db.session.commit()
            flash(f"Fee structure for Class {class_name} updated.", "success")
            return redirect(url_for("fee_structure"))

        rows = {r.class_name: r for r in FeeStructure.query.all()}
        ordered = [rows.get(c) for c in app.config["CLASS_LIST"] if rows.get(c)]
        return render_template("fee_structure.html", fee_rows=ordered, classes=app.config["CLASS_LIST"])

    # ---------- Small JSON API used by jQuery for live fee preview ----------
    @app.route("/api/fee-structure/<class_name>")
    @login_required
    def api_fee_structure(class_name):
        row = FeeStructure.query.filter_by(class_name=class_name).first()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row.to_dict())


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
