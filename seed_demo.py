"""
Seed CampusOS with demo users, skills, matches, transactions, courses,
and transfer profiles so the app has something to show new visitors.

Usage:
    python seed_demo.py          # seed if demo data is missing (idempotent)
    python seed_demo.py --reset  # wipe demo users (cascades) and reseed

All demo users share the password "demo1234" so reviewers can log in as any
of them. Real (non-demo) accounts are left untouched.
"""

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("CAMPUSOS_DB", "campusos.db")
SCHEMA  = "schema.sql"
DEMO_PASSWORD = "demo1234"

# Marker we look for to decide whether seeding already ran.
SEED_MARKER_USERNAME = "alex_demo"

# ─── Demo content ────────────────────────────────────────────────────────────

USERS = [
    # (username, email, school, bio, avatar_color)
    ("alex_demo",   "alex@demo.edu",    "Snow College",          "CS major, love teaching intro programming and debugging.", "#2d6a4f"),
    ("maya_demo",   "maya@demo.edu",    "Georgia Tech",          "Math + econ double major. Calc tutor, looking to pick up Spanish.", "#1d4ed8"),
    ("jordan_demo", "jordan@demo.edu",  "UT Austin",             "Music performance student. Piano lessons traded for help with stats.", "#7c3aed"),
    ("priya_demo",  "priya@demo.edu",   "UC San Diego",          "Bio pre-med. Strong in chemistry and study habits.", "#db2777"),
    ("sam_demo",    "sam@demo.edu",     "Community College of Denver", "Transfer student aiming for CU Boulder CS. Self-taught web dev.", "#0891b2"),
    ("riley_demo",  "riley@demo.edu",   "Northern Virginia CC",  "English & writing tutor. Editing essays since high school.", "#ea580c"),
]

# (username, type, name, description)
SKILLS = [
    ("alex_demo", "teach", "Python",            "Comfortable with intro CS material — pointers, recursion, basic algorithms."),
    ("alex_demo", "teach", "Intro to Flask",    "Can walk you through building a small Flask app from scratch."),
    ("alex_demo", "teach", "Git & GitHub",      "Branching, merging, resolving conflicts, PR workflow."),
    ("alex_demo", "teach", "Debugging",         "Reading stack traces, using pdb, isolating tricky bugs."),
    ("alex_demo", "learn", "Linear Algebra",    "Need help with eigenvalues and matrix decomposition for ML class."),

    ("maya_demo", "teach", "Calculus I & II",   "Years of tutoring experience. Can help with limits, derivatives, integrals, series."),
    ("maya_demo", "teach", "Microeconomics",    "Intro through intermediate level. Good with consumer/producer theory."),
    ("maya_demo", "teach", "Statistics",        "Probability, hypothesis testing, confidence intervals — comfortable up to intro inference."),
    ("maya_demo", "teach", "Excel for analytics", "Pivot tables, VLOOKUP/XLOOKUP, basic dashboards."),
    ("maya_demo", "learn", "Conversational Spanish", "Want a partner for weekly 30-min chats."),

    ("jordan_demo", "teach", "Piano (beginner-intermediate)", "Classical and pop. Patient with absolute beginners."),
    ("jordan_demo", "teach", "Music theory",    "Diatonic harmony, voice leading, basic counterpoint."),
    ("jordan_demo", "teach", "Ear training",    "Interval recognition, chord quality, simple melodic dictation."),
    ("jordan_demo", "teach", "Sight reading",   "Strategies for reading new music confidently at tempo."),
    ("jordan_demo", "learn", "Statistics",      "Struggling with hypothesis testing in research methods class."),

    ("priya_demo", "teach", "Organic chemistry","Mechanisms, retrosynthesis, study strategies for the dreaded orgo final."),
    ("priya_demo", "teach", "Study habits",     "Spaced repetition + active recall coaching."),
    ("priya_demo", "teach", "Anatomy & physiology", "Systems-based review with mnemonics — happy to quiz you."),
    ("priya_demo", "teach", "MCAT prep strategy", "Schedule planning, content review approach, full-length pacing."),
    ("priya_demo", "learn", "MCAT verbal",      "Looking for a practice partner to review CARS passages."),

    ("sam_demo",   "teach", "HTML/CSS",         "Layout, flexbox, grid. Built a few small portfolio sites."),
    ("sam_demo",   "teach", "JavaScript basics","Variables, functions, DOM, fetch. Up to intro React."),
    ("sam_demo",   "teach", "Portfolio sites",  "From zero to a deployed personal site on Netlify or GitHub Pages."),
    ("sam_demo",   "teach", "Resume review (CS)", "Targeted feedback for tech internships and entry-level roles."),
    ("sam_demo",   "learn", "Data structures",  "Cracking the coding interview prep — arrays, hashmaps, trees."),

    ("riley_demo", "teach", "Essay editing",    "Application essays, lit analysis, research papers."),
    ("riley_demo", "teach", "Grammar coaching", "ESL-friendly. Will explain *why* something reads wrong."),
    ("riley_demo", "teach", "Personal statements", "Brainstorming, structure, voice — for transfer and grad apps."),
    ("riley_demo", "teach", "Citations (APA/MLA)", "In-text citations, works cited pages, common pitfalls."),
    ("riley_demo", "learn", "Public speaking",  "Want to practice for class presentations."),
]

# (requester_username, receiver_username, skill_name, status)
# Skills are looked up by (receiver, name) so they match the right row.
MATCHES = [
    ("maya_demo",   "alex_demo",   "Python",                       "accepted"),
    ("sam_demo",    "alex_demo",   "Intro to Flask",               "accepted"),
    # Pending incoming for alex_demo — so the navbar badge appears for the
    # primary demo user reviewers will log in as.
    ("jordan_demo", "alex_demo",   "Python",                       "pending"),
    ("priya_demo",  "alex_demo",   "Intro to Flask",               "pending"),
    ("alex_demo",   "maya_demo",   "Calculus I & II",              "pending"),
    ("jordan_demo", "maya_demo",   "Microeconomics",               "pending"),
    ("priya_demo",  "riley_demo",  "Essay editing",                "accepted"),
    ("sam_demo",    "riley_demo",  "Grammar coaching",             "pending"),
    ("alex_demo",   "jordan_demo", "Music theory",                 "declined"),
]

# All Phase 2/3 demo data is attached to alex_demo so reviewers can see
# fully-populated dashboards by logging in as that one user.

CATEGORIES = [
    # (name, color)
    ("Food",       "#e63946"),
    ("Rent",       "#1d4ed8"),
    ("Transport",  "#f59e0b"),
    ("Books",      "#7c3aed"),
    ("Fun",        "#10b981"),
    ("Subscriptions", "#6b7280"),
]

# (title, amount, type, days_ago, category_name, note)
TRANSACTIONS = [
    ("Part-time paycheck", 720.00, "income",  3,  None,            "Bi-weekly"),
    ("Scholarship stipend", 500.00, "income", 10, None,            "Monthly"),
    ("Groceries — Trader Joe's",  64.20, "expense", 2,  "Food",      ""),
    ("Chipotle",                  12.75, "expense", 1,  "Food",      ""),
    ("Coffee shop",                4.95, "expense", 0,  "Food",      ""),
    ("Rent — November",          850.00, "expense", 5,  "Rent",      ""),
    ("Bus pass",                  45.00, "expense", 8,  "Transport", "Monthly"),
    ("Uber to airport",           27.50, "expense", 4,  "Transport", ""),
    ("Calc textbook",             82.00, "expense", 12, "Books",     "Used copy"),
    ("Movie night",               18.00, "expense", 6,  "Fun",       ""),
    ("Spotify",                    9.99, "expense", 7,  "Subscriptions", ""),
    # Older weeks to give the z-score anomaly detector something to compare against.
    # Need >=3 weeks of data and tight spread so this week's spike registers as
    # an outlier with z > 2.
    ("Groceries", 58.30, "expense", 9,  "Food", ""),
    ("Groceries", 71.10, "expense", 16, "Food", ""),
    ("Groceries", 49.80, "expense", 23, "Food", ""),
    ("Groceries", 55.00, "expense", 30, "Food", ""),
    ("Groceries", 62.50, "expense", 37, "Food", ""),
    ("Groceries", 60.20, "expense", 44, "Food", ""),
    # A clearly anomalous food spike this week — triggers the AI alert on the budget page
    ("Birthday dinner — group",  185.00, "expense", 0, "Food", "Sushi for 4"),
]

# (name, target_amount, saved_amount, days_until_deadline_or_None)
GOALS = [
    ("Emergency fund",   1000.00, 380.00, None),
    ("New laptop",       1400.00, 220.00, 120),
    ("Spring break trip", 600.00, 600.00, 45),  # already complete
]

# (name, credits, grade, status, semester)
COURSES = [
    ("English 1010",       3.0, "A",  "completed",   "Fall 2023"),
    ("Calculus I",         4.0, "B+", "completed",   "Fall 2023"),
    ("Intro to CS",        3.0, "A",  "completed",   "Fall 2023"),
    ("Calculus II",        4.0, "A-", "completed",   "Spring 2024"),
    ("Data Structures",    3.0, "B",  "completed",   "Spring 2024"),
    ("Linear Algebra",     3.0, "B+", "completed",   "Spring 2024"),
    ("Discrete Math",      3.0, "A",  "completed",   "Fall 2024"),
    ("Operating Systems",  3.0, "A",  "in_progress", "Spring 2025"),
    ("Algorithms",         3.0, "A",  "in_progress", "Spring 2025"),
    ("Compilers",          3.0, "A",  "planned",     "Fall 2025"),
]

# (name, major, days_until_deadline, notes)
TARGET_SCHOOLS = [
    ("Georgia Tech",        "Computer Science", 90,  "Reach school — need 3.7+"),
    ("UC San Diego",        "Computer Science", 120, ""),
    ("CU Boulder",          "Computer Science", 75,  "In-state advantage"),
]

# (school_name, major, gpa, credit_hours, outcome, year)
# Mixed so KNN has real data to chain on for the target schools above.
TRANSFER_PROFILES = [
    ("Georgia Tech", "Computer Science", 3.92, 64, "admitted",   2024),
    ("Georgia Tech", "Computer Science", 3.78, 60, "admitted",   2024),
    ("Georgia Tech", "Computer Science", 3.65, 58, "waitlisted", 2024),
    ("Georgia Tech", "Computer Science", 3.45, 55, "denied",     2023),
    ("Georgia Tech", "Computer Science", 3.20, 50, "denied",     2023),
    ("Georgia Tech", "Mathematics",      3.85, 62, "admitted",   2024),
    ("Georgia Tech", "Computer Science", 3.55, 60, "waitlisted", 2024),

    ("UC San Diego", "Computer Science", 3.80, 65, "admitted",   2024),
    ("UC San Diego", "Computer Science", 3.95, 70, "admitted",   2024),
    ("UC San Diego", "Computer Science", 3.50, 60, "waitlisted", 2023),
    ("UC San Diego", "Biology",          3.70, 62, "admitted",   2024),
    ("UC San Diego", "Computer Science", 3.30, 55, "denied",     2023),

    ("CU Boulder",   "Computer Science", 3.60, 58, "admitted",   2024),
    ("CU Boulder",   "Computer Science", 3.40, 60, "admitted",   2024),
    ("CU Boulder",   "Computer Science", 3.10, 55, "waitlisted", 2024),
    ("CU Boulder",   "Engineering",      3.75, 64, "admitted",   2024),
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn):
    if not os.path.exists(SCHEMA):
        sys.exit(f"Could not find {SCHEMA}. Run from the project root.")
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    # Idempotent migration for DBs that predate the avatar_color column.
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "avatar_color" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_color TEXT")
    conn.commit()


def demo_already_seeded(conn):
    row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (SEED_MARKER_USERNAME,)
    ).fetchone()
    return row is not None


def wipe_demo_users(conn):
    """ON DELETE CASCADE handles skills/matches/transactions/etc."""
    usernames = [u[0] for u in USERS]
    placeholders = ",".join("?" for _ in usernames)
    conn.execute(f"DELETE FROM users WHERE username IN ({placeholders})", usernames)
    # transfer_profiles are owned by users (FK with CASCADE) so they go too.
    conn.commit()


def iso_days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def iso_days_from_now(n):
    return (date.today() + timedelta(days=n)).isoformat()


# ─── Seeding ────────────────────────────────────────────────────────────────

def seed(conn):
    pw_hash = generate_password_hash(DEMO_PASSWORD)

    # Users -----------------------------------------------------------------
    user_ids = {}
    for username, email, school, bio, avatar_color in USERS:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, school, bio, avatar_color) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, email, pw_hash, school, bio, avatar_color)
        )
        user_ids[username] = cur.lastrowid

    # Skills ---------------------------------------------------------------
    # key: (username, skill_name) -> skill_id (for match lookup)
    skill_ids = {}
    for username, stype, name, desc in SKILLS:
        cur = conn.execute(
            "INSERT INTO skills (user_id, name, type, description) VALUES (?, ?, ?, ?)",
            (user_ids[username], name, stype, desc)
        )
        skill_ids[(username, name)] = cur.lastrowid

    # Matches --------------------------------------------------------------
    for requester, receiver, skill_name, status in MATCHES:
        skill_id = skill_ids.get((receiver, skill_name))
        if skill_id is None:
            continue  # silently skip if a referenced skill changed
        conn.execute(
            "INSERT INTO matches (requester_id, receiver_id, skill_id, status) "
            "VALUES (?, ?, ?, ?)",
            (user_ids[requester], user_ids[receiver], skill_id, status)
        )

    # Phase 2 data attached to alex_demo ----------------------------------
    alex_id = user_ids["alex_demo"]

    cat_ids = {}
    for name, color in CATEGORIES:
        cur = conn.execute(
            "INSERT INTO categories (user_id, name, color) VALUES (?, ?, ?)",
            (alex_id, name, color)
        )
        cat_ids[name] = cur.lastrowid

    for title, amount, ttype, days_ago, cat_name, note in TRANSACTIONS:
        cat_id = cat_ids.get(cat_name) if cat_name else None
        conn.execute(
            "INSERT INTO transactions (user_id, category_id, title, amount, type, date, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alex_id, cat_id, title, amount, ttype, iso_days_ago(days_ago), note)
        )

    for name, target, saved, days_out in GOALS:
        deadline = iso_days_from_now(days_out) if days_out is not None else None
        conn.execute(
            "INSERT INTO goals (user_id, name, target_amount, saved_amount, deadline) "
            "VALUES (?, ?, ?, ?, ?)",
            (alex_id, name, target, saved, deadline)
        )

    # Phase 3 data --------------------------------------------------------
    for name, credits, grade, status, semester in COURSES:
        conn.execute(
            "INSERT INTO courses (user_id, name, credits, grade, status, semester) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (alex_id, name, credits, grade, status, semester)
        )

    for name, major, days_out, notes in TARGET_SCHOOLS:
        conn.execute(
            "INSERT INTO target_schools (user_id, name, major, deadline, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (alex_id, name, major, iso_days_from_now(days_out), notes)
        )

    # Spread transfer profiles across demo users so they don't all belong to alex
    demo_user_ids = list(user_ids.values())
    for i, (school, major, gpa, credits, outcome, year) in enumerate(TRANSFER_PROFILES):
        owner_id = demo_user_ids[i % len(demo_user_ids)]
        conn.execute(
            "INSERT INTO transfer_profiles "
            "(user_id, school_name, major, gpa, credit_hours, outcome, year) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner_id, school, major, gpa, credits, outcome, year)
        )

    conn.commit()


# ─── Entrypoint ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed CampusOS with demo data.")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe existing demo users (cascades) and reseed.")
    args = parser.parse_args()

    conn = get_db()
    ensure_schema(conn)

    if demo_already_seeded(conn):
        if args.reset:
            print("Wiping existing demo users...")
            wipe_demo_users(conn)
        else:
            print("Demo data already present. Use --reset to wipe and reseed.")
            conn.close()
            return

    seed(conn)
    conn.close()

    print(f"Seeded {len(USERS)} demo users, {len(SKILLS)} skills, {len(MATCHES)} matches,")
    print(f"plus Phase 2/3 data on '{SEED_MARKER_USERNAME}' and {len(TRANSFER_PROFILES)} transfer profiles.")
    print(f"Log in as any demo user with password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
