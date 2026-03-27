
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 3 — TRANSFER PLANNER
# ═══════════════════════════════════════════════════════════════════════════

# Grade point values
GRADE_POINTS = {
    'A+': 4.0, 'A': 4.0, 'A-': 3.7,
    'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'C-': 1.7,
    'D+': 1.3, 'D': 1.0, 'D-': 0.7,
    'F': 0.0
}


def calculate_gpa(courses):
    """Calculate GPA from a list of completed courses."""
    completed = [c for c in courses if c['status'] == 'completed' and c['grade'] in GRADE_POINTS]
    if not completed:
        return 0.0
    total_points  = sum(GRADE_POINTS[c['grade']] * c['credits'] for c in completed)
    total_credits = sum(c['credits'] for c in completed)
    return round(total_points / total_credits, 2) if total_credits > 0 else 0.0


def predict_transfer_chance(db, school_name, gpa, credit_hours):
    """
    KNN transfer probability estimator.
    Looks at past transfer_profiles for this school and finds
    the k nearest neighbors by GPA + credit_hours distance.
    Returns (probability, sample_size).
    """
    profiles = db.execute("""
        SELECT gpa, credit_hours, outcome FROM transfer_profiles
        WHERE school_name = ?
    """, (school_name,)).fetchall()

    if not profiles:
        return None, 0

    profiles = [dict(p) for p in profiles]
    k = min(5, len(profiles))

    # Euclidean distance weighted: GPA matters more than credits
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

    # Run KNN for each target school
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

        if not name or not credits:
            flash("Course name and credits are required.", "error")
            return render_template("add_course.html", grades=GRADE_POINTS.keys())

        try:
            credits = float(credits)
        except ValueError:
            flash("Credits must be a number.", "error")
            return render_template("add_course.html", grades=GRADE_POINTS.keys())

        db = get_db()
        db.execute("""
            INSERT INTO courses (user_id, name, credits, grade, status, semester)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session["user_id"], name, credits, grade, status, semester))
        db.commit()
        db.close()
        flash(f"Course '{name}' added!", "success")
        return redirect(url_for("planner"))

    return render_template("add_course.html", grades=GRADE_POINTS.keys())


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

    if request.method == "POST":
        school_name  = request.form.get("school_name", "").strip()
        major        = request.form.get("major", "").strip()
        gpa          = request.form.get("gpa", "")
        credit_hours = request.form.get("credit_hours", "")
        outcome      = request.form.get("outcome", "admitted")
        year         = request.form.get("year", "").strip()
        notes        = request.form.get("notes", "").strip()

        if not school_name or not gpa or not credit_hours:
            flash("School, GPA, and credit hours are required.", "error")
        else:
            try:
                gpa          = float(gpa)
                credit_hours = float(credit_hours)
                year         = int(year) if year else None
                db.execute("""
                    INSERT INTO transfer_profiles
                    (user_id, school_name, major, gpa, credit_hours, outcome, year, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (session["user_id"], school_name, major, gpa, credit_hours,
                      outcome, year, notes))
                db.commit()
                flash("Transfer data shared — thank you!", "success")
            except ValueError:
                flash("GPA and credit hours must be numbers.", "error")

    # Community stats by school
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

    # Recent profiles
    recent = db.execute("""
        SELECT tp.*, u.username, u.school as from_school
        FROM transfer_profiles tp
        JOIN users u ON tp.user_id = u.id
        ORDER BY tp.created_at DESC
        LIMIT 30
    """).fetchall()

    db.close()
    return render_template("transfer_community.html",
                           school_stats=school_stats, recent=recent)
