# CampusOS
### CS50x Final Project — A College Student Super-App

CampusOS is a full-stack web application that combines three tools every college student needs into a single platform: a peer skill exchange network, a personal finance tracker, and a transfer planning system.

---

## Video Demo

<!-- Replace this link with your actual CS50 video submission URL -->
[Watch the demo](https://youtu.be/REPLACE_WITH_YOUR_LINK)

---

## Description

CampusOS was built as a CS50x final project to demonstrate every major concept covered in the course — C foundations, Python, SQL, Flask, HTML/CSS/JS — with an added machine learning layer that makes the app smarter as more students use it.

The app is organized into three phases, each of which is independently useful:

### Phase 1 — Campus Skills Exchange
A community platform where students post skills they can teach and skills they want to learn, then send match requests to connect with peers. The feed is powered by a **TF-IDF + cosine similarity** model (scikit-learn) that ranks results by relevance when you search — so if you search "Python", the most relevant tutors surface first rather than just the newest posts.

**Key features:**
- User registration and login with hashed passwords (Werkzeug)
- Skill posting (teach or learn) with descriptions
- AI-ranked feed with search
- Match request system (send, accept, decline)
- User profiles

### Phase 2 — Budget Buddy
A personal finance dashboard attached to each user's account. Students log income and expenses, categorize their spending, set savings goals, and visualize their finances with a doughnut chart. A **z-score anomaly detection** model flags unusual spending — if you normally spend $50/week on food and spend $200 one week, the app surfaces a warning.

**Key features:**
- Income and expense tracking
- Custom spending categories with color coding
- Savings goals with progress bars
- Spending breakdown chart (Chart.js)
- AI-powered anomaly detection

### Phase 3 — Transfer Planner
A course tracker and transfer planning tool for community college students. Students log completed, in-progress, and planned courses to calculate their GPA automatically. They can add target schools and get an AI admission probability estimate powered by a **K-Nearest Neighbors classifier** trained on crowdsourced transfer outcome data submitted by the community.

**Key features:**
- Course tracker with GPA calculator (weighted by credits and grade)
- Target school tracker with deadlines
- KNN-based transfer probability estimator
- Community data page where students share and browse transfer outcomes

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask, Flask-Session |
| Database | SQLite |
| Frontend | Jinja2, HTML, CSS, vanilla JavaScript |
| AI / ML | scikit-learn (TF-IDF, cosine similarity, KNN), NumPy |
| Auth | Werkzeug password hashing |
| Charts | Chart.js |

---

## File Structure

```
campusos/
├── app.py              # Main Flask application — all routes and AI logic
├── schema.sql          # SQLite schema — 6 tables across 3 phases
├── requirements.txt    # Python dependencies
├── static/
│   └── style.css       # Full stylesheet
└── templates/
    ├── layout.html           # Base layout with navbar
    ├── index.html            # Landing page
    ├── register.html         # Registration
    ├── login.html            # Login
    ├── feed.html             # Skills feed (Phase 1)
    ├── profile.html          # User profile (Phase 1)
    ├── add_skill.html        # Add skill form (Phase 1)
    ├── matches.html          # Match requests (Phase 1)
    ├── budget.html           # Budget dashboard (Phase 2)
    ├── add_transaction.html  # Add transaction (Phase 2)
    ├── categories.html       # Manage categories (Phase 2)
    ├── goals.html            # Savings goals (Phase 3)
    ├── planner.html          # Transfer planner dashboard (Phase 3)
    ├── add_course.html       # Add course (Phase 3)
    └── transfer_community.html  # Community transfer data (Phase 3)
```

---

## Design Decisions

**One app, not three.** All three phases share a single Flask app, a single SQLite database, and a single user authentication system. Each phase adds tables and routes on top of the existing foundation rather than being a separate project. This mirrors how real production apps are built.

**AI that degrades gracefully.** All three AI components (TF-IDF ranking, z-score detection, KNN classifier) are wrapped in try/except blocks and conditional checks. If scikit-learn is not installed or there is insufficient data, the app falls back to default behavior rather than crashing.

**SQL over ORM.** All database queries are written in raw SQL using sqlite3 rather than an ORM like SQLAlchemy. This was a deliberate choice to stay close to the SQL concepts taught in CS50 and to keep the codebase readable.

**No external APIs.** All AI features are implemented locally with scikit-learn — no OpenAI API key or external service required. This keeps the app self-contained and free to run.

---

## How to Run

```bash
pip install -r requirements.txt
python app.py
```

The database is created automatically on first run.

---

## Author

Built by [jerebear02](https://github.com/jerebear02) for CS50x.
