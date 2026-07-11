import csv
import io
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, Response
)

from config import Config
from extensions import db
from models import FeeStructure, Student, Transaction, StudentNote
from utils import login_required, generate_admission_number, recompute_balances


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_fee_structure_if_empty()

    register_routes(app)
    _register_template_filters(app)
    return app


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
        "Nursery": dict(admission_fee=1800, tuition_fee=10000, dress_fee=1200, book_fee=1200, misc_fee=800),
        "KG": dict(admission_fee=2000, tuition_fee=12000, dress_fee=1500, book_fee=1500, misc_fee=1000),
        "UKG": dict(admission_fee=2200, tuition_fee=13000, dress_fee=1500, book_fee=1700, misc_fee=1000),
        "1": dict(admission_fee=2500, tuition_fee=14000, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "2": dict(admission_fee=2500, tuition_fee=14000, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "3": dict(admission_fee=2500, tuition_fee=15000, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "4": dict(admission_fee=2500, tuition_fee=15000, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "5": dict(admission_fee=3000, tuition_fee=16000, dress_fee=1500, book_fee=2500, misc_fee=1200),
        "6": dict(admission_fee=3000, tuition_fee=17000, dress_fee=1500, book_fee=2500, misc_fee=1500),
        "7": dict(admission_fee=3000, tuition_fee=17000, dress_fee=1500, book_fee=2800, misc_fee=1500),
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
            class_counts=class_counts,
            recent_payments=recent_payments,
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
                admission_date=date.today(),
            )
            db.session.add(student)
            db.session.flush()  # get student.id before commit

            computed_total = fee_row.total_for_new_admission()
            override_str = request.form.get("override_amount", "").strip()
            is_custom = bool(override_str)
            try:
                charge_amount = float(override_str) if is_custom else computed_total
            except ValueError:
                charge_amount = computed_total
                is_custom = False

            remarks = f"Admission to Class {class_name} {student.section}"
            if is_custom and charge_amount != computed_total:
                remarks += f" (custom fee — standard is Rs {computed_total:,.0f})"

            txn = Transaction(
                student_id=student.id,
                txn_type="CHARGE",
                category="New Admission Fee",
                amount=charge_amount,
                date=date.today(),
                remarks=remarks,
                balance_after=charge_amount,
            )
            db.session.add(txn)
            db.session.flush()
            recompute_balances(student)
            db.session.commit()

            flash(f"{student.name} admitted successfully. Admission No: {student.admission_number}", "success")
            return redirect(url_for("student_ledger", student_id=student.id))

        return render_template(
            "add_student.html",
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

            computed_total = fee_row.total_for_promotion()
            override_str = request.form.get("override_amount", "").strip()
            is_custom = bool(override_str)
            try:
                charge_amount = float(override_str) if is_custom else computed_total
            except ValueError:
                charge_amount = computed_total
                is_custom = False

            remarks = f"Promoted to Class {new_class} {new_section}"
            if is_custom and charge_amount != computed_total:
                remarks += f" (custom fee — standard is Rs {computed_total:,.0f})"

            txn = Transaction(
                student_id=student.id,
                txn_type="CHARGE",
                category=f"Promotion Fee - Class {new_class}",
                amount=charge_amount,
                date=date.today(),
                remarks=remarks,
                balance_after=0,
            )
            db.session.add(txn)
            db.session.flush()
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
