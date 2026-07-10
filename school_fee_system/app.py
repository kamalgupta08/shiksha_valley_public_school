import csv
import io
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, Response
)

from config import Config
from extensions import db
from models import FeeStructure, Student, Transaction
from utils import login_required, generate_admission_number


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_fee_structure_if_empty()

    register_routes(app)
    return app


def _seed_fee_structure_if_empty():
    """Creates a placeholder fee row per class the first time the app runs, so the
    Fee Structure page always has something to edit instead of starting blank."""
    if FeeStructure.query.count() > 0:
        return
    defaults = {
        "KG": dict(admission_fee=2000, tuition_fee=12000, dress_fee=1500, book_fee=1500, misc_fee=1000),
        "1": dict(admission_fee=2500, tuition_fee=14000, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "2": dict(admission_fee=2500, tuition_fee=14000, dress_fee=1500, book_fee=2000, misc_fee=1000),
        "3": dict(admission_fee=2500, tuition_fee=15000, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "4": dict(admission_fee=2500, tuition_fee=15000, dress_fee=1500, book_fee=2200, misc_fee=1200),
        "5": dict(admission_fee=3000, tuition_fee=16000, dress_fee=1500, book_fee=2500, misc_fee=1200),
        "6": dict(admission_fee=3000, tuition_fee=17000, dress_fee=1500, book_fee=2500, misc_fee=1500),
        "7": dict(admission_fee=3000, tuition_fee=17000, dress_fee=1500, book_fee=2800, misc_fee=1500),
        "8": dict(admission_fee=3500, tuition_fee=18000, dress_fee=1500, book_fee=2800, misc_fee=1500),
        "9": dict(admission_fee=3500, tuition_fee=19000, dress_fee=1500, book_fee=3000, misc_fee=1800),
    }
    for class_name, fees in defaults.items():
        db.session.add(FeeStructure(class_name=class_name, **fees))
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

            charge_amount = fee_row.total_for_new_admission()
            txn = Transaction(
                student_id=student.id,
                txn_type="CHARGE",
                category="New Admission Fee",
                amount=charge_amount,
                date=date.today(),
                remarks=f"Admission to Class {class_name} {student.section}",
                balance_after=charge_amount,
            )
            db.session.add(txn)
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
        transactions = student.transactions.order_by(Transaction.date, Transaction.id).all()
        return render_template("student_ledger.html", student=student, transactions=transactions)

    @app.route("/students/<int:student_id>/deposit", methods=["POST"])
    @login_required
    def deposit_fee(student_id):
        student = Student.query.get_or_404(student_id)
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0

        if amount <= 0:
            flash("Enter a valid deposit amount.", "danger")
            return redirect(url_for("student_ledger", student_id=student.id))

        new_balance = student.balance - amount
        txn = Transaction(
            student_id=student.id,
            txn_type="PAYMENT",
            category="Deposit",
            amount=amount,
            date=date.today(),
            mode=request.form.get("mode", "Cash"),
            remarks=request.form.get("remarks", ""),
            balance_after=new_balance,
        )
        db.session.add(txn)
        db.session.commit()
        flash(f"Deposit of Rs {amount:,.2f} recorded for {student.name}.", "success")
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

            charge_amount = fee_row.total_for_promotion()
            new_balance = student.balance + charge_amount
            txn = Transaction(
                student_id=student.id,
                txn_type="CHARGE",
                category=f"Promotion Fee - Class {new_class}",
                amount=charge_amount,
                date=date.today(),
                remarks=f"Promoted to Class {new_class} {new_section}",
                balance_after=new_balance,
            )
            db.session.add(txn)
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
