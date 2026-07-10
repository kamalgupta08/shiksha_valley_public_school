# Sekhe Valley Public School — Website & Fee Management System

A lightweight Flask + jQuery + PostgreSQL app: a public website (home page,
features, testimonials) plus a password-protected staff area for managing
students, class-wise fee structures, deposits, and per-student ledgers.

## What's included

```
school_fee_system/
├── app.py                  # All routes / application logic
├── config.py                # Reads settings from environment variables
├── extensions.py            # SQLAlchemy database instance
├── models.py                 # FeeStructure, Student, Transaction (ledger)
├── utils.py                   # login_required decorator, admission-no generator
├── requirements.txt
├── Procfile                   # Tells the host how to start the app
├── .env.example               # Copy to .env and fill in real values
├── static/
│   ├── css/style.css          # All styling — one design system
│   └── js/                    # jQuery: fee preview, filters, flash messages
└── templates/                 # Jinja2 HTML templates
```

## How the fee logic works

- **Fee Structure page** — set admission fee, tuition, dress, books, and misc
  fee *per class* (KG through 9). This drives everything else automatically.
- **Add Student** — when you admit a student into a class, the system charges
  admission fee + tuition + dress + books + misc for that class. You never
  type the fee amount by hand.
- **Deposit** — record a payment against a student any time. The ledger
  balance updates immediately.
- **Promote** — moving a student to the next class charges that class's fees
  again (minus the admission fee, since that's one-time only).
- **Ledger** — every charge and payment is stored as a row, so nothing is
  ever overwritten — you always have full history.

Every student, section (A–E) and class (KG–9) you mentioned is supported;
just add sections/classes in `config.py` (`CLASS_LIST` / `SECTION_LIST`) if
that ever changes.

## 1. Run it locally first

You'll need Python 3.10+ installed.

```bash
cd school_fee_system
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # then open .env and set your own values
python app.py
```

Open **http://localhost:5000**. The database (SQLite, a single file
`school.db`) and the class-wise fee rows are created automatically the first
time the app runs, with placeholder fee amounts you should edit under
**Fee Structure** once logged in.

Log in with whatever you set `ADMIN_USERNAME` / `ADMIN_PASSWORD` to in `.env`
(defaults to `admin` / `changeme123` if you skip the `.env` file — **do not
leave that as-is once it's public**).

## 2. About the database — you will always own your data

You asked specifically about not losing access if a bill goes unpaid. Two
things address that directly:

1. **SQLite works out of the box with zero cost and zero external service** —
   your entire database is just the `school.db` file sitting next to your
   code. You could run this on hosting that costs a few dollars a month, or
   even on a school office PC, and back up that one file to a USB drive or
   Google Drive weekly. No one can lock you out of a file on your own server.
2. **If you outgrow SQLite** (say, several office staff hitting it
   simultaneously), switching to PostgreSQL is a one-line change: set
   `DATABASE_URL` in `.env`. Render and Railway both offer a free Postgres
   instance to start, and — importantly — both let you export/dump your data
   at any time with a single `pg_dump` command, so even if you eventually
   paid and stopped, you'd export first and never be stuck.

My recommendation given your budget concerns: **start on SQLite hosted on
Render's free web service tier.** It costs nothing, there's no separate
database bill to forget, and you fully own the file. Move to Postgres only
once you have a real reason to (multiple people editing at once, or wanting
managed backups).

## 3. Hosting — step by step (Render, free tier)

1. Create a free account at **render.com**.
2. Put this project in a GitHub repository (Render deploys from Git):
   ```bash
   cd school_fee_system
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin <your-empty-github-repo-url>
   git push -u origin main
   ```
   (The `.gitignore` file already excludes `.env` and the local database, so
   secrets won't be pushed to GitHub.)
3. In Render: **New → Web Service** → connect your GitHub repo.
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
5. Under **Environment**, add these variables (this replaces your local
   `.env` file):
   - `SECRET_KEY` → any long random string
   - `ADMIN_USERNAME` → your chosen login
   - `ADMIN_PASSWORD` → a strong password, shared only with school office staff
   - `SCHOOL_NAME` → `Sekhe Valley Public School`
   - Leave `DATABASE_URL` unset for now — it'll default to SQLite.
6. Click **Create Web Service**. Render builds and deploys automatically;
   you'll get a URL like `sekhe-valley-school.onrender.com`.

**Important free-tier caveat:** Render's free web services spin down after
15 minutes of no traffic and take ~30–60 seconds to wake back up on the next
visit. That's fine for a school office tool used a few times a day, but if
it ever bothers you, Render's cheapest paid tier (~$7/month) keeps it always
on. Also note: on the free tier, the filesystem (and therefore `school.db`)
gets wiped on each redeploy — so once you're relying on this for real data,
either upgrade to a paid instance with a persistent disk, or move to
Postgres (a free Render Postgres instance is enough for a school this size,
and its data survives redeploys independently of the web service).

### Alternative: Railway

Railway's flow is nearly identical — connect the GitHub repo, it detects the
`Procfile` automatically, and you add the same environment variables under
the service's **Variables** tab. Railway's free trial credit runs out after
about a month of light use, after which it's pay-as-you-go (typically a
couple of dollars a month for an app this small).

## 4. Day-to-day use once it's live

- Share the login URL + username/password only with school office staff.
- First thing after deploying: go to **Fee Structure** and set real amounts
  for every class — the seeded values are placeholders.
- **Add New Student** → pick class/section → the fee preview appears
  automatically → submit to admit and create the first charge.
- **Students & Fees** → filter by class/section, search by name or admission
  number, see every student's pending balance at a glance, **Export CSV**
  for offline records or sharing with the accountant.
- Open any student to see their full ledger and record a **Deposit** when a
  parent pays.
- **Promote to Next Class** on a student's ledger page when they move up —
  it automatically charges the new class's fees.

## 5. Reasonable next steps (ask me any time)

- Real testimonials/photos on the home page (currently placeholder text).
- Printable fee receipts (PDF) per deposit.
- Multiple staff logins instead of one shared one, if you outgrow that.
- SMS/WhatsApp reminders for pending balances.

Happy to build any of these into the same codebase whenever you're ready.
