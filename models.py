from datetime import date, datetime
from extensions import db


class FeeStructure(db.Model):
    """One row per class (KG, 1, 2 ... 9). Drives auto fee calculation."""
    __tablename__ = "fee_structures"

    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(10), unique=True, nullable=False)

    admission_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)   # one-time, new admissions only
    tuition_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)     # monthly
    dress_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    book_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    misc_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    def total_for_new_admission(self):
        return float(self.admission_fee) + float(self.tuition_fee) + float(self.dress_fee) \
            + float(self.book_fee) + float(self.misc_fee)

    def total_for_promotion(self):
        """Existing students don't pay admission fee again."""
        return float(self.tuition_fee) + float(self.dress_fee) + float(self.book_fee) + float(self.misc_fee)

    def to_dict(self):
        return {
            "class_name": self.class_name,
            "admission_fee": float(self.admission_fee),
            "tuition_fee": float(self.tuition_fee),
            "dress_fee": float(self.dress_fee),
            "book_fee": float(self.book_fee),
            "misc_fee": float(self.misc_fee),
            "total_new_admission": self.total_for_new_admission(),
            "total_promotion": self.total_for_promotion(),
        }


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    admission_number = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    class_name = db.Column(db.String(10), nullable=False)
    section = db.Column(db.String(5), nullable=False)
    guardian_name = db.Column(db.String(120), nullable=True)
    contact_number = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    admission_date = db.Column(db.Date, nullable=False, default=date.today)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    transactions = db.relationship(
        "Transaction", backref="student", lazy="dynamic",
        cascade="all, delete-orphan", order_by="Transaction.date, Transaction.id"
    )
    notes = db.relationship(
        "StudentNote", backref="student", lazy="dynamic",
        cascade="all, delete-orphan", order_by="StudentNote.created_at.desc()"
    )

    @property
    def balance(self):
        """Positive = amount due. Negative = advance / credit.
        ADJUSTMENT entries let staff apply a discount (negative amount) or an
        extra charge (positive amount) to an individual student at any time."""
        charges = sum(float(t.amount) for t in self.transactions if t.txn_type == "CHARGE")
        payments = sum(float(t.amount) for t in self.transactions if t.txn_type == "PAYMENT")
        adjustments = sum(float(t.amount) for t in self.transactions if t.txn_type == "ADJUSTMENT")
        return round(charges - payments + adjustments, 2)

    @property
    def last_payment_date(self):
        last = (
            self.transactions.filter_by(txn_type="PAYMENT")
            .order_by(Transaction.date.desc(), Transaction.created_at.desc())
            .first()
        )
        return last.date if last else None

    def to_dict(self):
        return {
            "id": self.id,
            "admission_number": self.admission_number,
            "name": self.name,
            "class_name": self.class_name,
            "section": self.section,
            "guardian_name": self.guardian_name,
            "contact_number": self.contact_number,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "balance": self.balance,
            "is_active": self.is_active,
        }


class StudentNote(db.Model):
    """A general remark about a student — e.g. 'requested fee extension',
    not tied to any specific deposit. Shown on the students list and ledger."""
    __tablename__ = "student_notes"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    note = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "note": self.note,
            "created_at": self.created_at.strftime("%d %b %Y") if self.created_at else None,
        }


class Transaction(db.Model):
    """A single ledger entry — either a CHARGE (fee levied) or a PAYMENT (deposit received)."""
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)

    txn_type = db.Column(db.String(10), nullable=False)   # 'CHARGE', 'PAYMENT', or 'ADJUSTMENT'
    category = db.Column(db.String(60), nullable=False)   # e.g. 'Admission Fee', 'Deposit'
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    mode = db.Column(db.String(20), nullable=True)        # Cash / Online / Cheque — for payments
    remarks = db.Column(db.String(255), nullable=True)
    balance_after = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fee_period = db.Column(db.Date, nullable=True)  # first-of-month marker, only set for monthly tuition charges

    def to_dict(self):
        return {
            "id": self.id,
            "txn_type": self.txn_type,
            "category": self.category,
            "amount": float(self.amount),
            "date": self.date.isoformat() if self.date else None,
            "mode": self.mode,
            "remarks": self.remarks,
            "balance_after": float(self.balance_after),
        }
