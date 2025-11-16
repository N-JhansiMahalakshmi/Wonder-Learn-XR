import os
import sqlite3
import json
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, g, render_template, request, redirect, url_for, session, jsonify, flash
from flask import abort

# ---------- CONFIG ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'codequest.db')
SQL_INIT_FILE = os.path.join(BASE_DIR, 'codequest_db_init.sql')

SECRET_KEY = os.environ.get('FLASK_SECRET', 'super-secret-change-me')

# ---------- APP ----------
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['DATABASE'] = DB_PATH

# ensure data directory exists
os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)

# ---------- DB UTIL ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    if os.path.exists(SQL_INIT_FILE):
        with open(SQL_INIT_FILE, 'r', encoding='utf-8') as f:
            db.executescript(f.read())
    else:
        # fallback: create table directly
        db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT,
            password_hash TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            streaks INTEGER DEFAULT 0,
            lessons_completed TEXT DEFAULT '[]'
        );
        """)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# run DB init at start
with app.app_context():
    init_db()

# ---------- AUTH HELPERS ----------
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            # If not logged in, redirect to the login page
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return wrapped

def get_current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    cur = db.execute('SELECT * FROM users WHERE id = ?', (uid,))
    row = cur.fetchone()
    return dict(row) if row else None

# ---------- ROUTES ----------

# FIX: This route now renders index.html
@app.route('/')
def index():
    user = get_current_user()
    if user:
        # If already logged in, go straight to dashboard
        return redirect(url_for('dashboard'))
    # Otherwise, show the public homepage
    return render_template('index.html', user=user)

# Serves the login.html page
@app.route('/login.html')
def login_page():
    return render_template('login.html')

# Serves the signup.html page
@app.route('/signup.html')
def signup_page():
    return render_template('signup.html')

# Handles the signup form submission
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json() or request.form
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'ok': False, 'error': 'username and password required'}), 400
    db = get_db()
    try:
        password_hash = generate_password_hash(password)
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                    (username, password_hash))
        db.commit()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'error': 'username already exists'}), 400

# Handles the login form submission
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or request.form
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'ok': False, 'error': 'username and password required'}), 400
    db = get_db()
    cur = db.execute('SELECT * FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    if not row:
        return jsonify({'ok': False, 'error': 'invalid credentials'}), 401
    
    if check_password_hash(row['password_hash'], password):
        session['user_id'] = row['id']
        user_data = {
            'id': row['id'],
            'username': row['username'],
            'xp': row['points'],
            'streak': row['streaks']
        }
        return jsonify({'ok': True, 'user': user_data})
    else:
        return jsonify({'ok': False, 'error': 'invalid credentials'}), 401

# Logout
@app.route('/logout', methods=['POST'])
@login_required
def logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})

# Dashboard (Protected)
@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    lessons = json.loads(user.get('lessons_completed') or '[]')
    return render_template('dashboard.html', user=user, lessons=lessons)

# API: get current user data
@app.route('/api/me')
def api_me():
    user = get_current_user()
    if not user:
        return jsonify({'ok': False, 'user': None}), 200
    user_data = {
        'id': user['id'],
        'username': user['username'],
        'points': user['points'],
        'lessons_completed': json.loads(user['lessons_completed'] or '[]')
    }
    return jsonify({'ok': True, 'user': user_data})

# API: mark lesson complete
@app.route('/api/complete_lesson', methods=['POST'])
@login_required
def complete_lesson():
    data = request.get_json() or request.form
    lesson_slug = data.get('lesson')
    points_awarded = int(data.get('points', 10))
    if not lesson_slug:
        return jsonify({'ok': False, 'error': 'lesson required'}), 400

    db = get_db()
    user = get_current_user()
    lessons = json.loads(user.get('lessons_completed') or '[]')
    if lesson_slug in lessons:
        return jsonify({'ok': True, 'message': 'lesson already completed', 'points': user['points'], 'lessons_completed': lessons})

    lessons.append(lesson_slug)
    new_points = user['points'] + points_awarded
    db.execute('UPDATE users SET lessons_completed = ?, points = ? WHERE id = ?',
               (json.dumps(lessons), new_points, user['id']))
    db.commit()
    return jsonify({'ok': True, 'points': new_points, 'lessons_completed': lessons})

# API: submit code for validation (placeholder)
@app.route('/api/submit_code', methods=['POST'])
@login_required
def submit_code():
    data = request.get_json() or request.form
    lesson = data.get('lesson')
    code_text = data.get('code', '')
    
    def placeholder_validator(code, lesson_slug):
        checks = {
            'lesson_variables': ['='],
            'lesson_datatypes': ['int', 'str', 'float', 'list', 'dict'],
            'lesson_operators': ['+', '-', '*', '/', '%'],
            'lesson_loops': ['for ', 'while '],
        }
        tokens = checks.get(lesson_slug, [])
        if not tokens:
            return {'passed': False, 'message': 'No validator rules for this lesson', 'points': 0}
        for t in tokens:
            if t in code:
                return {'passed': True, 'message': f'Found token "{t}"', 'points': 10}
        return {'passed': False, 'message': 'Required token not found', 'points': 0}

    result = placeholder_validator(code_text, lesson)

    if result.get('passed'):
        user = get_current_user()
        lessons = json.loads(user.get('lessons_completed') or '[]')
        already = lesson in lessons
        if not already:
            lessons.append(lesson)
            new_points = user['points'] + int(result.get('points', 0))
            db = get_db()
            db.execute('UPDATE users SET lessons_completed = ?, points = ? WHERE id = ?',
                       (json.dumps(lessons), new_points, user['id']))
            db.commit()
            return jsonify({'ok': True, 'passed': True, 'message': result.get('message', ''), 'points': new_points, 'lessons_completed': lessons})
        else:
            return jsonify({'ok': True, 'passed': True, 'message': 'Already completed', 'points': user['points'], 'lessons_completed': lessons})
    else:
        return jsonify({'ok': True, 'passed': False, 'message': result.get('message', '')})

# A simple route to return a template for each lesson
@app.route('/lesson/<slug>')
@login_required
def lesson_page(slug):
    user = get_current_user()
    possible_names = [ f'lesson_{slug}.html', f'{slug}.html' ]
    for name in possible_names:
        if os.path.exists(os.path.join(BASE_DIR, 'templates', name)):
            return render_template(name, user=user)
    return render_template('lesson_generic.html', slug=slug, user=user)

# Quiz page
@app.route('/quiz/<topic>')
@login_required
def quiz_page(topic):
    user = get_current_user()
    return render_template('quiz.html', user=user, topic=topic)


@app.route('/<template_name>.html')
def serve_template_html(template_name):
    """Serve existing template files directly when requested as '/name.html'.
    For lesson and protected pages require login; otherwise render publicly.
    """
    # only serve templates that actually exist in the templates folder
    candidate = os.path.join(BASE_DIR, 'templates', f'{template_name}.html')
    if not os.path.exists(candidate):
        return abort(404)

    # protect lesson and dashboard pages
    if template_name.startswith('lesson_') or template_name in ('dashboard', 'quiz'):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))

    user = get_current_user()
    return render_template(f'{template_name}.html', user=user)


@app.route('/lesson_<slug>')
@login_required
def lesson_underscore(slug):
    """Support URLs like /lesson_loops that map to templates named lesson_loops.html."""
    user = get_current_user()
    name = f'lesson_{slug}.html'
    candidate = os.path.join(BASE_DIR, 'templates', name)
    if os.path.exists(candidate):
        return render_template(name, user=user)
    return abort(404)


@app.route('/submit_quiz', methods=['POST'])
@login_required
def submit_quiz():
    data = request.get_json() or request.form
    topic = data.get('topic')
    try:
        score = int(data.get('score', 0))
    except Exception:
        score = 0

    # Treat any positive score as correct (client sends 100 for correct)
    if score > 0:
        db = get_db()
        user = get_current_user()
        # award flat 10 XP for a correct quiz
        new_points = (user.get('points') or 0) + 10
        db.execute('UPDATE users SET points = ? WHERE id = ?', (new_points, user['id']))
        db.commit()
        return jsonify({'ok': True, 'message': 'Correct! 10 XP awarded.', 'points': new_points})
    else:
        return jsonify({'ok': False, 'error': 'Incorrect answer. Try again.'}), 400


# API: set a user's streak (admin or self)
@app.route('/api/set_streak', methods=['POST'])
@login_required
def api_set_streak():
    data = request.get_json() or request.form
    username = data.get('username')
    try:
        streak = int(data.get('streak', 0))
    except Exception:
        return jsonify({'ok': False, 'error': 'invalid streak value'}), 400

    if not username:
        return jsonify({'ok': False, 'error': 'username required'}), 400

    current = get_current_user()
    # only allow setting other users if current is admin (env ADMIN_USER) otherwise only allow self
    admin_user = os.environ.get('ADMIN_USER', 'admin')
    if current['username'] != username and current['username'] != admin_user:
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    db = get_db()
    cur = db.execute('SELECT id FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    if not row:
        return jsonify({'ok': False, 'error': 'user not found'}), 404

    db.execute('UPDATE users SET streaks = ? WHERE id = ?', (streak, row['id']))
    db.commit()
    return jsonify({'ok': True, 'username': username, 'streak': streak})


# API: increment current user's streak (simple endpoint — caller ensures daily logic)
@app.route('/api/streak/increment', methods=['POST'])
@login_required
def api_increment_streak():
    user = get_current_user()
    db = get_db()
    try:
        new = (int(user.get('streaks') or 0) + 1)
    except Exception:
        new = 1
    db.execute('UPDATE users SET streaks = ? WHERE id = ?', (new, user['id']))
    db.commit()
    return jsonify({'ok': True, 'streak': new})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

