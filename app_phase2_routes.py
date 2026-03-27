
# ═══════════════════════════════════════════════════════════════════════════
#  PHASE 2 — BUDGET BUDDY
# ═══════════════════════════════════════════════════════════════════════════

import math
from datetime import date, datetime, timedelta


def get_spending_anomalies(db, user_id):
    """
    Z-score anomaly detection.
    For each category, flag any week where spending > mean + 2*stdev.
    Returns a list of warning strings.
    """
    warnings = []
    rows = db.execute("""
        SELECT c.name as cat, t.date, t.amount
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND t.type = 'expense'
        ORDER BY t.date
    """, (user_id,)).fetchall()

    # Group by category -> weekly buckets
    from collections import defaultdict
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

    # Totals
    totals = db.execute("""
        SELECT type, SUM(amount) as total
        FROM transactions WHERE user_id = ?
        GROUP BY type
    """, (session["user_id"],)).fetchall()
    income  = next((r["total"] for r in totals if r["type"] == "income"),  0) or 0
    expense = next((r["total"] for r in totals if r["type"] == "expense"), 0) or 0
    balance = income - expense

    # Recent transactions
    recent = db.execute("""
        SELECT t.*, c.name as cat_name, c.color as cat_color
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.date DESC, t.created_at DESC
        LIMIT 20
    """, (session["user_id"],)).fetchall()

    # Spending by category (for chart)
    by_cat = db.execute("""
        SELECT c.name as cat, c.color, SUM(t.amount) as total
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = ? AND t.type = 'expense'
        GROUP BY t.category_id
        ORDER BY total DESC
    """, (session["user_id"],)).fetchall()

    # Goals
    goals = db.execute(
        "SELECT * FROM goals WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()

    # AI anomaly warnings
    anomalies = get_spending_anomalies(db, session["user_id"])

    # Categories for dropdown
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

        if not title or not amount or not date_val:
            flash("Title, amount, and date are required.", "error")
            db.close()
            return render_template("add_transaction.html", categories=categories)

        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            db.close()
            return render_template("add_transaction.html", categories=categories)

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
                           categories=categories,
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
