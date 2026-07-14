import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


def _normalize_db_url(url: str) -> str:
    """Neon/Render/Railway hand out plain 'postgres://' or 'postgresql://' URLs.
    SQLAlchemy needs to know explicitly to use the psycopg3 driver (not the old,
    Python-3.14-incompatible psycopg2), so we rewrite the scheme accordingly.
    SQLite URLs and anything that already specifies a driver pass through untouched.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'school.db')}")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Hard-coded / shared login credentials (no sign-up flow needed)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme123")

    SCHOOL_NAME = os.environ.get("SCHOOL_NAME", "Sekhe Valley Public School")
    SCHOOL_TAGLINE = os.environ.get("SCHOOL_TAGLINE", "Nurturing minds from KG to Class IX")

    # Classes offered — used to drive dropdowns and fee-structure seeding
    CLASS_LIST = ["Nursery", "KG", "UKG", "1", "2", "3", "4", "5", "6", "7"]
    SECTION_LIST = ["A", "B", "C", "D", "E"]
