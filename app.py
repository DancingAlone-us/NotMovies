import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
from services.tmdb import get_movie_detail, get_now_playing, get_random_tmdb_movie, search_tmdb
import psycopg2
import requests
import json
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash, check_password_hash
from services.mailer import send_verification_email
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('FLASK_SECRET_KEY')


def get_db_connection():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = True
    return conn


conn = get_db_connection()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'signup'

class User(UserMixin):
    def __init__(self, user_id, username, email):
        self.id = user_id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    return User(row[0], row[1], row[2])


@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/home')
def index():
    new_movies = get_now_playing(limit=8)
    top_movie_raw = get_top_rated_movies(limit=20)
    top_movies = use_tmdb(top_movie_raw)[:8]
    featured_movies = top_movies[:5]
    return render_template('index.html', featured_movies=featured_movies, new_movies=new_movies, top_movies=top_movies)


@app.route('/browse')
def browse():
    sort = request.args.get('sort', 'recent')
    genre = request.args.get('genre', 'all')
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    if query:
        movies_raw, total_pages = get_browse_movies(sort=sort, genre=genre, query=query, page=page, per_page=per_page * 2)
        if movies_raw:
            movies = enrich_with_posters(movies_raw, require_poster=True)[:per_page]
        else:
            movies = search_tmdb(query, page=page)
            total_pages = 500
    else:
        movies_raw, total_pages = get_browse_movies(sort=sort, genre=genre, page=page, per_page=per_page * 2)
        movies = enrich_with_posters(movies_raw, require_poster=True)[:per_page]

    return render_template('browse.html', movies=movies, current_sort=sort,
                            current_genre=genre, current_query=query,
                            current_page=page, total_pages=total_pages,
                            available_genres=['Action', 'Adventure', 'Animation', 'Crime', 'Drama'])

@app.route('/feeling-lucky')
def lucky():
    for _ in range(5):
        tmdb_id = get_random_tmdb_movie()
        if not tmdb_id:
            continue
        try:
            get_movie_detail_cached(tmdb_id)
            return redirect(url_for('movie_detail_tmdb', tmdb_id=tmdb_id))
        except requests.exceptions.HTTPError:
            continue
    return redirect(url_for('browse'))


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    cur = conn.cursor()
    cur.execute("SELECT user_id, username, password_hash, is_verified FROM users WHERE email = %s", (email,))
    row = cur.fetchone()

    if not row:
        return render_template('signup.html', msg="No account found with that email.")

    user_id, username, password_hash, is_verified = row

    if not check_password_hash(password_hash, password):
        return render_template('signup.html', msg="Incorrect password. Please try again.")

    if not is_verified:
        return render_template('signup.html', msg="Please verify your account first — check your email for the verification link.")

    login_user(User(user_id, username, email))
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("User has been logged out")
    return redirect(url_for('landing'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not username or not email or not password:
        flash("All required fields must be filled in.")
        return redirect(url_for('register'))

    if password != confirm_password:
        flash("Passwords don't match. Please try again.")
        return redirect(url_for('register'))

    if len(password) < 6:
        flash("Password must be at least 6 characters long.")
        return redirect(url_for('register'))

    password_hash = generate_password_hash(password)

    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING user_id",
            (username, email, password_hash)
        )
        user_id = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        flash("That username or email is already taken.")
        return redirect(url_for('register'))

    # generate and store the verification token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(minutes=10)
    cur.execute("""
        INSERT INTO verification_tokens (user_id, token, expires_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET token = EXCLUDED.token, expires_at = EXCLUDED.expires_at
    """, (user_id, token, expires_at))

    verify_link = url_for('verify_account', token=token, _external=True)
    send_verification_email(email, verify_link)

    flash("Account created! Check your email for a verification link before logging in.")
    return redirect(url_for('signup'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


def get_tmdb_id(movie_id):
    cur = conn.cursor()
    cur.execute("SELECT tmdb_id from links where movie_id = %s", (movie_id,))
    row = cur.fetchone()
    return row[0] if row else None


@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    tmdb_id = get_tmdb_id(movie_id)
    if not tmdb_id:
        return "Movie Not Found", 404
    try:
        details = get_movie_detail_cached(tmdb_id)
    except requests.exceptions.HTTPError:
        return "Movie Not Found", 404
    return render_template('movie_detail.html', movie=details)


@app.route('/movie/tmdb/<int:tmdb_id>')
def movie_detail_tmdb(tmdb_id):
    try:
        details = get_movie_detail_cached(tmdb_id)
    except requests.exceptions.HTTPError:
        return "Movie Not Found", 404
    details['movie_id'] = None
    return render_template('movie_detail.html', movie=details)


def get_new_movies(limit=8):
    cur = conn.cursor()
    cur.execute("""
    SELECT movie_id, title
    FROM movies
    WHERE title ~ '\\(\\d{4}\\)$'
    ORDER BY substring(title from '\\((\\d{4})\\)$')::int DESC
    LIMIT %s
    """, (limit,))
    return cur.fetchall()


def get_top_rated_movies(limit=20):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT movie_id, title, avg_rating
        FROM top_rated_movies
        LIMIT {int(limit)}
    """)
    return cur.fetchall()


def use_tmdb(rows):
    use = []
    for row in rows:
        movie_id = row[0]
        tmdb_id = get_tmdb_id(movie_id)
        if not tmdb_id:
            continue
        try:
            details = get_movie_detail_cached(tmdb_id)
        except requests.exceptions.HTTPError:
            continue
        details['movie_id'] = movie_id
        use.append(details)
    return use


def get_movie_detail_cached(tmdb_id, max_age_days=5):
    cur = conn.cursor()
    cur.execute('SELECT data, fetched_at FROM tmdb_cache WHERE tmdb_id = %s', (tmdb_id,))
    row = cur.fetchone()

    if row and row[1] > datetime.now() - timedelta(days=max_age_days):
        if row[0].get('_failed'):
            raise requests.exceptions.HTTPError(f"cached failure for tmdb_id {tmdb_id}")
        return row[0]

    try:
        details = get_movie_detail(tmdb_id)
    except requests.exceptions.HTTPError:
        cur.execute("""
            INSERT INTO tmdb_cache (tmdb_id, data, fetched_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (tmdb_id) DO UPDATE SET data = EXCLUDED.data, fetched_at = NOW()
        """, (tmdb_id, json.dumps({"_failed": True})))
        raise

    cur.execute("""
        INSERT INTO tmdb_cache (tmdb_id, data, fetched_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (tmdb_id) DO UPDATE SET data = EXCLUDED.data, fetched_at = NOW()
    """, (tmdb_id, json.dumps(details)))
    return details

def get_browse_movies(sort='recent', genre='all', query='', page=1, per_page=20):
    offset = (page - 1) * per_page
    cur = conn.cursor()

    order_clause = {
        'recent': "substring(m.title from '\\((\\d{4})\\)$')::int DESC NULLS LAST",
        'watched': 'watch_count DESC NULLS LAST',
        'top_rated': 'avg_rating DESC NULLS LAST'
    }.get(sort, 'm.movie_id DESC')

    having_clause = "HAVING COUNT(r.rating) >= 200" if sort == 'top_rated' else ""

    conditions = []
    params = []
    if genre != 'all':
        conditions.append("m.genres ILIKE %s")
        params.append(f'%{genre}%')
    if query:
        conditions.append("m.title ILIKE %s")
        params.append(f'%{query}%')

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"""
        SELECT COUNT(*) FROM (
            SELECT m.movie_id
            FROM movies m
            LEFT JOIN ratings r ON m.movie_id = r.movie_id
            {where_clause}
            GROUP BY m.movie_id
            {having_clause}
        ) sub
    """
    cur.execute(count_query, params)
    total_count = cur.fetchone()[0]

    query_sql = f"""
        SELECT m.movie_id, m.title, m.genres,
               COUNT(r.rating) as watch_count,
               AVG(r.rating) as avg_rating
        FROM movies m
        LEFT JOIN ratings r ON m.movie_id = r.movie_id
        {where_clause}
        GROUP BY m.movie_id, m.title, m.genres
        {having_clause}
        ORDER BY {order_clause}
        LIMIT %s OFFSET %s
    """
    params_full = params + [per_page, offset]
    cur.execute(query_sql, params_full)
    movies = cur.fetchall()

    total_pages = max(1, (total_count + per_page - 1) // per_page)
    return movies, total_pages

def enrich_with_posters(movies, require_poster=False):
    enriched = []
    for row in movies:
        movie_id, title, genres, watch_count, avg_rating = row
        tmdb_id = get_tmdb_id(movie_id)
        poster_url = None
        if tmdb_id:
            try:
                details = get_movie_detail_cached(tmdb_id)
                poster_url = details.get('poster_url')
            except requests.exceptions.HTTPError:
                pass

        if require_poster and not poster_url:
            continue

        enriched.append({
            'movie_id': movie_id,
            'title': title,
            'genres': genres,
            'watch_count': watch_count,
            'avg_rating': avg_rating,
            'poster_url': poster_url
        })
    return enriched

@app.route('/verify/<token>')
def verify_account(token):
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, expires_at
        FROM verification_tokens
        WHERE token = %s
    """, (token,))
    row = cur.fetchone()

    if not row:
        flash("Invalid or already-used verification link.")
        return redirect(url_for('signup'))

    user_id, expires_at = row

    if expires_at < datetime.now():
        flash("This verification link has expired. Please register again or request a new link.")
        return redirect(url_for('signup'))

    cur.execute("UPDATE users SET is_verified = TRUE WHERE user_id = %s", (user_id,))
    cur.execute("DELETE FROM verification_tokens WHERE user_id = %s", (user_id,))

    flash("Your account has been verified! You can now log in.")
    return redirect(url_for('signup'))

@app.route('/watched/toggle', methods=['POST'])
@login_required
def toggle_watched():
    tmdb_id = request.form.get('tmdb_id', type=int)
    title = request.form.get('title')
    poster_url = request.form.get('poster_url') or None

    cur = conn.cursor()
    cur.execute("SELECT 1 FROM watched WHERE user_id = %s AND tmdb_id = %s", (current_user.id, tmdb_id))
    already_watched = cur.fetchone() is not None

    if already_watched:
        cur.execute("DELETE FROM watched WHERE user_id = %s AND tmdb_id = %s", (current_user.id, tmdb_id))
        now_watched = False
    else:
        cur.execute("""
            INSERT INTO watched (user_id, tmdb_id, movie_title, poster_url)
            VALUES (%s, %s, %s, %s)
        """, (current_user.id, tmdb_id, title, poster_url))
        now_watched = True

    return {"watched": now_watched}


if __name__ == "__main__":
    app.run(debug=True)