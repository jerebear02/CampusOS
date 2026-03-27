-- ADD THESE TABLES TO THE BOTTOM OF YOUR EXISTING schema.sql

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    credits REAL NOT NULL,
    grade TEXT NOT NULL,  -- 'A', 'A-', 'B+', 'B', etc.
    status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('completed', 'in_progress', 'planned')),
    semester TEXT,        -- e.g. 'Fall 2024'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS target_schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    major TEXT,
    deadline TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transfer_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    school_name TEXT NOT NULL,
    major TEXT,
    gpa REAL NOT NULL,
    credit_hours REAL NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('admitted', 'denied', 'waitlisted')),
    year INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_courses_user ON courses(user_id);
CREATE INDEX IF NOT EXISTS idx_target_schools_user ON target_schools(user_id);
CREATE INDEX IF NOT EXISTS idx_transfer_profiles_school ON transfer_profiles(school_name);
