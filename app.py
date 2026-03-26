import os
import json
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from functools import wraps
from datetime import datetime

# Try to import sklearn for AI features; gracefully degrade if unavailable
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

app = Flask(__name__)
app.config["SECRET_KEY"] = "campusos-secret-key-change-in-production"
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

DB_PATH = "campusos.db"


# ─── Database helpers ────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with open("schema.sql") as f:
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

        if not username or not email or not password:
            flash("Username, email, and password are required.", "error")
            return render_template("register.html")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()

        if existing:
            flash("Username or email already taken.", "error")
            db.close()
            return render_template("register.html")

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

    return render_template("register.html")


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
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        flash(f"Welcome back, {username}!", "success")
        return redirect(url_for("feed"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("index"))


# ── Feed ──────────────────────────────────────────────────────────────────────

@app.route("/feed")
@login_required
def feed():
    query  = request.args.get("q", "").strip()
    db     = get_db()

    # Get all "teach" skills (excluding current user's own)
    skills = db.execute("""
        SELECT s.*, u.username, u.school, u.bio
        FROM skills s
        JOIN users u ON s.user_id = u.id
        WHERE s.type = 'teach' AND s.user_id != ?
        ORDER BY s.created_at DESC
    """, (session["user_id"],)).fetchall()

    skills = [dict(s) for s in skills]

    # AI ranking if there's a search query
    if query and AI_AVAILABLE:
        skills = rank_skills_by_relevance(query, skills)
        ai_ranked = True
    else:
        ai_ranked = False

    # Get current user's "learn" skills for the sidebar
    my_wants = db.execute("""
        SELECT * FROM skills WHERE user_id = ? AND type = 'learn'
    """, (session["user_id"],)).fetchall()

    db.close()
    return render_template("feed.html", skills=skills, query=query,
                           ai_ranked=ai_ranked, my_wants=my_wants,
                           ai_available=AI_AVAILABLE)


# ── Skills ────────────────────────────────────────────────────────────────────

@app.route("/skills/add", methods=["GET", "POST"])
@login_required
def add_skill():
    if request.method == "POST":
        name        = request.form.get("name", "").strip()
        skill_type  = request.form.get("type", "teach")
        description = request.form.get("description", "").strip()

        if not name:
            flash("Skill name is required.", "error")
            return render_template("add_skill.html")

        if skill_type not in ("teach", "learn"):
            flash("Invalid skill type.", "error")
            return render_template("add_skill.html")

        db = get_db()
        db.execute(
            "INSERT INTO skills (user_id, name, type, description) VALUES (?, ?, ?, ?)",
            (session["user_id"], name, skill_type, description)
        )
        db.commit()
        db.close()

        flash(f"Skill '{name}' added!", "success")
        return redirect(url_for("profile", username=session["username"]))

    return render_template("add_skill.html")


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


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        init_db()
    app.run(debug=True)
