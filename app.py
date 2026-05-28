import os
import json
import math
import secrets
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps

import numpy as np
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash

# Try to import sklearn for AI features; gracefully degrade if unavailable
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

app = Flask(__name__)
# SECRET_KEY: required in prod (set as env var on Render). In dev, generate a
# random one so the app boots — but sessions won't survive a restart.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

DB_PATH = os.environ.get("CAMPUSOS_DB", "campusos.db")


# ─── Database helpers ────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with open("schema.sql", encoding="utf-8") as f:
        conn = get_db()
        conn.executescript(f.read())
        conn.commit()
        conn.close()


# ─── Auth decorator ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─── Template globals ────────────────────────────────────────────────────────

@app.context_processor
def inject_nav_badges():
    """Expose pending incoming match count to every template (for the navbar badge)."""
    user_id = session.get("user_id")
    if not user_id:
        return {"pending_match_count": 0}
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM matches WHERE receiver_id = ? AND status = 'pending'",
        (user_id,)
    ).fetchone()
    db.close()
    return {"pending_match_count": row["n"] if row else 0}


# ─── AI: Skill Match Ranker ──────────────────────────────────────────────────

def rank_skills_by_relevance(query, skills):
    """Rank teach-skills by cosine similarity to the user's query."""
    if not AI_AVAILABLE or not skills or not query.strip():
        return skills

    docs = [query] + [f"{s['name']} {s['description'] or ''}" for s in skills]
    try:
        tfidf = TfidfVectorizer(stop_words="english")
        matrix = tfidf.fit_transform(docs)
        scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
        ranked = sorted(zip(scores, skills), key=lambda x: x[0], reverse=True)
        return [s for _, s in ranked]
    except Exception:
        return skills


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("feed"))
    return render_template("index.html")


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        school   = request.form.get("school", "").strip()
        bio      = request.form.get("bio", "").strip()

        form_data = {"username": username, "email": email, "school": school, "bio": bio}

        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
            return render_template("register.html", form=form_data)

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()

        if existing:
            flash("Username or email already taken.", "error")
            db.close()
            return render_template("register.html", form=form_data)

        pw_hash = generate_password_hash(password)
        db.execute(
            "INSERT INTO users (username, email, password_hash, school, bio) VALUES (?, ?, ?, ?, ?)",
            (username, email, pw_hash, school, bio)
        )
        db.commit()
        user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        db.close()

        session["user_id"] = user["id"]
        session["username"] = username
        flash(f"Welcome to CampusOS, {username}!", "success")
        return redirect(url_for("feed"))

    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        db.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html", form={"username": username})

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        flash(f"Welcome back, {username}!", "success")
        return redirect(url_for("feed"))

    return render_template("login.html", form={})


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("index"))


# ── Feed ──────────────────────────────────────────────────────────────────────

FEED_PAGE_SIZE = 12


@app.route("/feed")
@login_required
def feed():
    query         = request.args.get("q", "").strip()
    school_filter = request.args.get("school", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    db = get_db()

    # Build the skills query with optional school filter applied at SQL level.
    sql = """
        SELECT s.*, u.username, u.school, u.bio
        FROM skills s
        JOIN users u ON s.user_id = u.id
        WHERE s.type = 'teach' AND s.user_id != ?
    """
    params = [session["user_id"]]
    if school_filter:
        sql += " AND u.school = ?"
        params.append(school_filter)
    sql += " ORDER BY s.created_at DESC"

    skills = [dict(s) for s in db.execute(sql, params).fetchall()]

    # AI ranking runs on the full filtered set so relevance is global, not per-page.
    if query and AI_AVAILABLE:
        skills = rank_skills_by_relevance(query, skills)
        ai_ranked = True
    else:
        ai_ranked = False

    # Paginate in Python after ranking.
    total       = len(skills)
    total_pages = max(1, (total + FEED_PAGE_SIZE - 1) // FEED_PAGE_SIZE)
    page        = min(page, total_pages)
    start       = (page - 1) * FEED_PAGE_SIZE
    page_skills = skills[start:start + FEED_PAGE_SIZE]
    showing_from = start + 1 if total else 0
    showing_to   = start + len(page_skills)

    # Distinct non-empty schools (excluding current user) for the filter dropdown.
    school_rows = db.execute("""
        SELECT DISTINCT u.school FROM users u
        JOIN skills s ON s.user_id = u.id
        WHERE s.type = 'teach' AND u.id != ?
          AND u.school IS NOT NULL AND TRIM(u.school) != ''
        ORDER BY u.school
    """, (session["user_id"],)).fetchall()
    schools = [r["school"] for r in school_rows]

    my_wants = db.execute(
        "SELECT * FROM skills WHERE user_id = ? AND type = 'learn'",
        (session["user_id"],)
    ).fetchall()

    db.close()
    return render_template("feed.html",
                           skills=page_skills, query=query,
                           school_filter=school_filter, schools=schools,
                           ai_ranked=ai_ranked, my_wants=my_wants,
                           ai_available=AI_AVAILABLE,
                           page=page, total_pages=total_pages, total=total,
                           showing_from=showing_from, showing_to=showing_to)


# ── Skills ────────────────────────────────────────────────────────────────────

@app.route("/skills/add", methods=["GET", "POST"])
@login_required
def add_skill():
    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        skill_type  = request.form.get("type", "teach")
        description = request.form.get("description", "").strip()

        form_data = {"name": name, "type": skill_type, "description": description}

        if not name:
            flash("Skill name is required.", "error")
            return render_template("add_skill.html", form=form_data)

        if skill_type not in ("teach", "learn"):
            flash("Invalid skill type.", "error")
            return render_template("add_skill.html", form=form_data)

        db = get_db()
        db.execute(
            "INSERT INTO skills (user_id, name, type, description) VALUES (?, ?, ?, ?)",
            (session["user_id"], name, skill_type, description)
        )
        db.commit()
        db.close()

        flash(f"Skill '{name}' added!", "success")
        return redirect(url_for("profile", username=session["username"]))

    return render_template("add_skill.html", form={"type": "teach"})


@app.route("/skills/delete/<int:skill_id>", methods=["POST"])
@login_required
def delete_skill(skill_id):
    db = get_db()
    skill = db.execute(
        "SELECT * FROM skills WHERE id = ? AND user_id = ?",
        (skill_id, session["user_id"])
    ).fetchone()

    if not skill:
        flash("Skill not found.", "error")
        db.close()
        return redirect(url_for("profile", username=session["username"]))

    db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    db.commit()
    db.close()
    flash("Skill removed.", "success")
    return redirect(url_for("profile", username=session["username"]))


# ── Profile ───────────────────────────────────────────────────────────────────

@app.route("/profile/<username>")
@login_required
def profile(username):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    if not user:
        flash("User not found.", "error")
        db.close()
        return redirect(url_for("feed"))

    teach_skills = db.execute(
        "SELECT * FROM skills WHERE user_id = ? AND type = 'teach' ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()

    learn_skills = db.execute(
        "SELECT * FROM skills WHERE user_id = ? AND type = 'learn' ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()

    # Check if current user already sent a match to this profile
    pending_match_ids = set()
    if user["id"] != session["user_id"]:
        sent = db.execute("""
            SELECT skill_id FROM matches
            WHERE requester_id = ? AND receiver_id = ? AND status = 'pending'
        """, (session["user_id"], user["id"])).fetchall()
        pending_match_ids = {r["skill_id"] for r in sent}

    db.close()
    is_own_profile = (user["id"] == session["user_id"])
    return render_template("profile.html", user=user,
                           teach_skills=teach_skills,
                           learn_skills=learn_skills,
                           is_own_profile=is_own_profile,
                           pending_match_ids=pending_match_ids)


# ── Matches ───────────────────────────────────────────────────────────────────

@app.route("/match/request/<int:skill_id>", methods=["POST"])
@login_required
def request_match(skill_id):
    db    = get_db()
    skill = db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()

    if not skill:
        flash("Skill not found.", "error")
        db.close()
        return redirect(url_for("feed"))

    if skill["user_id"] == session["user_id"]:
        flash("You can't match with yourself.", "error")
        db.close()
        return redirect(url_for("feed"))

    # Prevent duplicates
    existing = db.execute("""
        SELECT id FROM matches
        WHERE requester_id = ? AND receiver_id = ? AND skill_id = ? AND status = 'pending'
    """, (session["user_id"], skill["user_id"], skill_id)).fetchone()

    if existing:
        flash("You already sent a match request for this skill.", "error")
        db.close()
        return redirect(url_for("feed"))

    db.execute("""
        INSERT INTO matches (requester_id, receiver_id, skill_id, status)
        VALUES (?, ?, ?, 'pending')
    """, (session["user_id"], skill["user_id"], skill_id))
    db.commit()
    db.close()

    flash("Match request sent!", "success")
    return redirect(request.referrer or url_for("feed"))


@app.route("/matches")
@login_required
def matches():
    db = get_db()

    incoming = db.execute("""
        SELECT m.*, s.name as skill_name, s.description as skill_desc,
               u.username as requester_name, u.school as requester_school
        FROM matches m
        JOIN skills s ON m.skill_id = s.id
        JOIN users u ON m.requester_id = u.id
        WHERE m.receiver_id = ? AND m.status = 'pending'
        ORDER BY m.created_at DESC
    """, (session["user_id"],)).fetchall()

    outgoing = db.execute("""
        SELECT m.*, s.name as skill_name,
               u.username as receiver_name, u.school as receiver_school
        FROM matches m
        JOIN skills s ON m.skill_id = s.id
        JOIN users u ON m.receiver_id = u.id
        WHERE m.requester_id = ?
        ORDER BY m.created_at DESC
    """, (session["user_id"],)).fetchall()

    accepted = db.execute("""
        SELECT m.*, s.name as skill_name,
               CASE WHEN m.requester_id = ? THEN u2.username ELSE u1.username END as partner_name
        FROM matches m
        JOIN skills s ON m.skill_id = s.id
        JOIN users u1 ON m.requester_id = u1.id
        JOIN users u2 ON m.receiver_id = u2.id
        WHERE (m.requester_id = ? OR m.receiver_id = ?) AND m.status = 'accepted'
        ORDER BY m.created_at DESC
    """, (session["user_id"], session["user_id"], session["user_id"])).fetchall()

    db.close()
    return render_template("matches.html", incoming=incoming,
                           outgoing=outgoing, accepted=accepted)


@app.route("/match/respond/<int:match_id>", methods=["POST"])
@login_required
def respond_match(match_id):
    action = request.form.get("action")
    if action not in ("accepted", "declined"):
        flash("Invalid action.", "error")
        return redirect(url_for("matches"))

    db = get_db()
    match = db.execute(
        "SELECT * FROM matches WHERE id = ? AND receiver_id = ?",
        (match_id, session["user_id"])
    ).fetchone()

    if not match:
        flash("Match not found.", "error")
        db.close()
        return redirect(url_for("matches"))

    db.execute("UPDATE matches SET status = ? WHERE id = ?", (action, match_id))
    db.commit()
    db.close()

    msg = "Match accepted! You're connected." if action == "accepted" else "Match declined."
    flash(msg, "success" if action == "accepted" else "error")
    return redirect(url_for("matches"))


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 2 — BUDGET BUDDY
# ═══════════════════════════════════════════════════════════════════════════

def get_spending_anomalies(db, user_id):
    """Z-score anomaly detection: flag any week where category spending > mean + 2σ."""
    warnings = []
    rows = db.execute("""
        SELECT c.name as cat, t.date, t.amount
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND t.type = 'expense'
        ORDER BY t.date
    """, (user_id,)).fetchall()

    cat_weeks = defaultdict(lambda: defaultdict(float))
    for row in rows:
        try:
            d = datetime.strptime(row["date"], "%Y-%m-%d")
            week = d.strftime("%Y-W%W")
            cat_weeks[row["cat"] or "Uncategorized"][week] += row["amount"]
        except Exception:
            continue

    for cat, weeks in cat_weeks.items():
        amounts = list(weeks.values())
        if len(amounts) < 3:
            continue
        mean = sum(amounts) / len(amounts)
        variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
        stdev = math.sqrt(variance)
        if stdev == 0:
            continue
        latest_week = sorted(weeks.keys())[-1]
        latest_amt = weeks[latest_week]
        z = (latest_amt - mean) / stdev
        if z > 2:
            warnings.append(
                f"⚠️ Unusual spending in <strong>{cat}</strong> this week "
                f"(${latest_amt:.2f} vs your usual ${mean:.2f})"
            )

    return warnings


# ── Budget dashboard ──────────────────────────────────────────────────────────

@app.route("/budget")
@login_required
def budget():
    db = get_db()

    totals = db.execute("""
        SELECT type, SUM(amount) as total
        FROM transactions WHERE user_id = ?
        GROUP BY type
    """, (session["user_id"],)).fetchall()
    income  = next((r["total"] for r in totals if r["type"] == "income"),  0) or 0
    expense = next((r["total"] for r in totals if r["type"] == "expense"), 0) or 0
    balance = income - expense

    recent = db.execute("""
        SELECT t.*, c.name as cat_name, c.color as cat_color
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.date DESC, t.created_at DESC
        LIMIT 20
    """, (session["user_id"],)).fetchall()

    by_cat = db.execute("""
        SELECT c.name as cat, c.color, SUM(t.amount) as total
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND t.type = 'expense'
        GROUP BY t.category_id
        ORDER BY total DESC
    """, (session["user_id"],)).fetchall()

    goals = db.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()

    anomalies = get_spending_anomalies(db, session["user_id"])

    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()

    db.close()
    return render_template("budget.html",
        income=income, expense=expense, balance=balance,
        recent=recent, by_cat=by_cat, goals=goals,
        anomalies=anomalies, categories=categories)


# ── Add transaction ───────────────────────────────────────────────────────────

@app.route("/budget/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    db = get_db()
    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()

    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        amount      = request.form.get("amount", "")
        ttype       = request.form.get("type", "expense")
        date_val    = request.form.get("date", "")
        category_id = request.form.get("category_id") or None
        note        = request.form.get("note", "").strip()

        form_data = {
            "title": title, "amount": amount, "type": ttype,
            "date": date_val, "category_id": category_id, "note": note,
        }

        if not title or not amount or not date_val:
            flash("Title, amount, and date are required.", "error")
            db.close()
            return render_template("add_transaction.html",
                                   categories=categories, form=form_data,
                                   today=date.today().isoformat())

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            db.close()
            return render_template("add_transaction.html",
                                   categories=categories, form=form_data,
                                   today=date.today().isoformat())

        db.execute("""
            INSERT INTO transactions (user_id, category_id, title, amount, type, date, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session["user_id"], category_id, title, amount, ttype, date_val, note))
        db.commit()
        db.close()
        flash(f"Transaction '{title}' added!", "success")
        return redirect(url_for("budget"))

    db.close()
    return render_template("add_transaction.html",
                           categories=categories, form={"type": "expense"},
                           today=date.today().isoformat())


# ── Delete transaction ────────────────────────────────────────────────────────

@app.route("/budget/delete/<int:txn_id>", methods=["POST"])
@login_required
def delete_transaction(txn_id):
    db = get_db()
    db.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?",
        (txn_id, session["user_id"])
    )
    db.commit()
    db.close()
    flash("Transaction deleted.", "success")
    return redirect(url_for("budget"))


# ── Categories ────────────────────────────────────────────────────────────────

@app.route("/budget/categories", methods=["GET", "POST"])
@login_required
def manage_categories():
    db = get_db()
    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        color = request.form.get("color", "#2d6a4f")
        if name:
            db.execute(
                "INSERT INTO categories (user_id, name, color) VALUES (?, ?, ?)",
                (session["user_id"], name, color)
            )
            db.commit()
            flash(f"Category '{name}' added!", "success")

    categories = db.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return render_template("categories.html", categories=categories)


@app.route("/budget/categories/delete/<int:cat_id>", methods=["POST"])
@login_required
def delete_category(cat_id):
    db = get_db()
    db.execute(
        "DELETE FROM categories WHERE id = ? AND user_id = ?",
        (cat_id, session["user_id"])
    )
    db.commit()
    db.close()
    flash("Category deleted.", "success")
    return redirect(url_for("manage_categories"))


# ── Goals ─────────────────────────────────────────────────────────────────────

@app.route("/budget/goals", methods=["GET", "POST"])
@login_required
def goals():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            name          = request.form.get("name", "").strip()
            target_amount = request.form.get("target_amount", "")
            deadline      = request.form.get("deadline") or None
            if name and target_amount:
                try:
                    target_amount = float(target_amount)
                    db.execute("""
                        INSERT INTO goals (user_id, name, target_amount, deadline)
                        VALUES (?, ?, ?, ?)
                    """, (session["user_id"], name, target_amount, deadline))
                    db.commit()
                    flash(f"Goal '{name}' created!", "success")
                except ValueError:
                    flash("Target amount must be a number.", "error")

        elif action == "contribute":
            goal_id = request.form.get("goal_id")
            amount  = request.form.get("amount", "")
            try:
                amount = float(amount)
                db.execute("""
                    UPDATE goals SET saved_amount = MIN(saved_amount + ?, target_amount)
                    WHERE id = ? AND user_id = ?
                """, (amount, goal_id, session["user_id"]))
                db.commit()
                flash(f"${amount:.2f} added to your goal!", "success")
            except ValueError:
                flash("Invalid amount.", "error")

        elif action == "delete":
            goal_id = request.form.get("goal_id")
            db.execute(
                "DELETE FROM goals WHERE id = ? AND user_id = ?",
                (goal_id, session["user_id"])
            )
            db.commit()
            flash("Goal deleted.", "success")

        db.close()
        return redirect(url_for("goals"))

    all_goals = db.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return render_template("goals.html", goals=all_goals, today=date.today().isoformat())


# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 3 — TRANSFER PLANNER
# ═══════════════════════════════════════════════════════════════════════════

GRADE_POINTS = {
    'A+': 4.0, 'A': 4.0, 'A-': 3.7,
    'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'C-': 1.7,
    'D+': 1.3, 'D': 1.0, 'D-': 0.7,
    'F': 0.0
}


def calculate_gpa(courses):
    """GPA weighted by credits, completed courses only."""
    completed = [c for c in courses if c['status'] == 'completed' and c['grade'] in GRADE_POINTS]
    if not completed:
        return 0.0
    total_points  = sum(GRADE_POINTS[c['grade']] * c['credits'] for c in completed)
    total_credits = sum(c['credits'] for c in completed)
    return round(total_points / total_credits, 2) if total_credits > 0 else 0.0


def predict_transfer_chance(db, school_name, gpa, credit_hours):
    """KNN transfer probability — k=5, GPA weighted heavier than credits."""
    profiles = db.execute("""
        SELECT gpa, credit_hours, outcome FROM transfer_profiles
        WHERE school_name = ?
    """, (school_name,)).fetchall()

    if not profiles:
        return None, 0

    profiles = [dict(p) for p in profiles]
    k = min(5, len(profiles))

    def distance(p):
        return ((p['gpa'] - gpa) * 2) ** 2 + ((p['credit_hours'] - credit_hours) / 30) ** 2

    neighbors = sorted(profiles, key=distance)[:k]
    admitted  = sum(1 for n in neighbors if n['outcome'] == 'admitted')
    prob      = round(admitted / k * 100)
    return prob, len(profiles)


# ── Planner dashboard ─────────────────────────────────────────────────────────

@app.route("/planner")
@login_required
def planner():
    db = get_db()

    courses = db.execute("""
        SELECT * FROM courses WHERE user_id = ?
        ORDER BY status DESC, semester, name
    """, (session["user_id"],)).fetchall()
    courses = [dict(c) for c in courses]

    gpa             = calculate_gpa(courses)
    completed       = [c for c in courses if c['status'] == 'completed']
    in_progress     = [c for c in courses if c['status'] == 'in_progress']
    planned         = [c for c in courses if c['status'] == 'planned']
    total_credits   = sum(c['credits'] for c in completed)

    target_schools = db.execute("""
        SELECT * FROM target_schools WHERE user_id = ?
        ORDER BY created_at DESC
    """, (session["user_id"],)).fetchall()

    schools_with_prediction = []
    for school in target_schools:
        prob, sample_size = predict_transfer_chance(db, school['name'], gpa, total_credits)
        schools_with_prediction.append({**dict(school), 'prob': prob, 'sample_size': sample_size})

    db.close()
    return render_template("planner.html",
        courses=courses, gpa=gpa,
        completed=completed, in_progress=in_progress, planned=planned,
        total_credits=total_credits,
        target_schools=schools_with_prediction)


# ── Add course ────────────────────────────────────────────────────────────────

@app.route("/planner/courses/add", methods=["GET", "POST"])
@login_required
def add_course():
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        credits  = request.form.get("credits", "")
        grade    = request.form.get("grade", "A")
        status   = request.form.get("status", "completed")
        semester = request.form.get("semester", "").strip()

        form_data = {
            "name": name, "credits": credits, "grade": grade,
            "status": status, "semester": semester,
        }

        if not name or not credits:
            flash("Course name and credits are required.", "error")
            return render_template("add_course.html", grades=GRADE_POINTS.keys(), form=form_data)

        try:
            credits = float(credits)
        except ValueError:
            flash("Credits must be a number.", "error")
            return render_template("add_course.html", grades=GRADE_POINTS.keys(), form=form_data)

        db = get_db()
        db.execute("""
            INSERT INTO courses (user_id, name, credits, grade, status, semester)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session["user_id"], name, credits, grade, status, semester))
        db.commit()
        db.close()
        flash(f"Course '{name}' added!", "success")
        return redirect(url_for("planner"))

    return render_template("add_course.html", grades=GRADE_POINTS.keys(),
                           form={"grade": "A", "status": "completed"})


@app.route("/planner/courses/delete/<int:course_id>", methods=["POST"])
@login_required
def delete_course(course_id):
    db = get_db()
    db.execute("DELETE FROM courses WHERE id = ? AND user_id = ?",
               (course_id, session["user_id"]))
    db.commit()
    db.close()
    flash("Course removed.", "success")
    return redirect(url_for("planner"))


# ── Target schools ────────────────────────────────────────────────────────────

@app.route("/planner/schools/add", methods=["POST"])
@login_required
def add_school():
    name     = request.form.get("name", "").strip()
    major    = request.form.get("major", "").strip()
    deadline = request.form.get("deadline") or None
    notes    = request.form.get("notes", "").strip()

    if not name:
        flash("School name is required.", "error")
        return redirect(url_for("planner"))

    db = get_db()
    db.execute("""
        INSERT INTO target_schools (user_id, name, major, deadline, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (session["user_id"], name, major, deadline, notes))
    db.commit()
    db.close()
    flash(f"{name} added to your target schools!", "success")
    return redirect(url_for("planner"))


@app.route("/planner/schools/delete/<int:school_id>", methods=["POST"])
@login_required
def delete_school(school_id):
    db = get_db()
    db.execute("DELETE FROM target_schools WHERE id = ? AND user_id = ?",
               (school_id, session["user_id"]))
    db.commit()
    db.close()
    flash("School removed.", "success")
    return redirect(url_for("planner"))


# ── Community transfer data ───────────────────────────────────────────────────

@app.route("/planner/community", methods=["GET", "POST"])
@login_required
def transfer_community():
    db = get_db()

    form_data = {"outcome": "admitted"}

    if request.method == "POST":
        school_name  = request.form.get("school_name", "").strip()
        major        = request.form.get("major", "").strip()
        gpa          = request.form.get("gpa", "")
        credit_hours = request.form.get("credit_hours", "")
        outcome      = request.form.get("outcome", "admitted")
        year         = request.form.get("year", "").strip()
        notes        = request.form.get("notes", "").strip()

        form_data = {
            "school_name": school_name, "major": major, "gpa": gpa,
            "credit_hours": credit_hours, "outcome": outcome,
            "year": year, "notes": notes,
        }

        submission_ok = False
        if not school_name or not gpa or not credit_hours:
            flash("School, GPA, and credit hours are required.", "error")
        else:
            try:
                gpa_f          = float(gpa)
                credit_hours_f = float(credit_hours)
                year_i         = int(year) if year else None
                db.execute("""
                    INSERT INTO transfer_profiles
                    (user_id, school_name, major, gpa, credit_hours, outcome, year, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (session["user_id"], school_name, major, gpa_f, credit_hours_f,
                      outcome, year_i, notes))
                db.commit()
                flash("Transfer data shared — thank you!", "success")
                submission_ok = True
            except ValueError:
                flash("GPA, credit hours, and year must be numbers.", "error")

        # Clear the form after a successful submission
        if submission_ok:
            form_data = {"outcome": "admitted"}

    school_stats = db.execute("""
        SELECT school_name,
               COUNT(*) as total,
               AVG(gpa) as avg_gpa,
               AVG(credit_hours) as avg_credits,
               SUM(CASE WHEN outcome='admitted' THEN 1 ELSE 0 END) as admitted,
               SUM(CASE WHEN outcome='denied'   THEN 1 ELSE 0 END) as denied,
               SUM(CASE WHEN outcome='waitlisted' THEN 1 ELSE 0 END) as waitlisted
        FROM transfer_profiles
        GROUP BY school_name
        ORDER BY total DESC
    """).fetchall()

    recent = db.execute("""
        SELECT tp.*, u.username, u.school as from_school
        FROM transfer_profiles tp
        JOIN users u ON tp.user_id = u.id
        ORDER BY tp.created_at DESC
        LIMIT 30
    """).fetchall()

    db.close()
    return render_template("transfer_community.html",
                           school_stats=school_stats, recent=recent, form=form_data)


# ─── Bootstrap ───────────────────────────────────────────────────────────────

# Init the DB on import so the schema exists under gunicorn too (not just
# when running `python app.py`). CREATE TABLE IF NOT EXISTS makes this safe
# to call every boot.
if not os.path.exists(DB_PATH):
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
