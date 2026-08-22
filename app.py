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
from collections import Counter
from google import genai

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('Flask_Secret_Key')

gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))


def get_db_connection():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = True
    return conn


# initial connection, opened once at startup
conn = get_db_connection()


def get_conn():
    """Returns a healthy connection, transparently reconnecting if the
    existing one has gone stale (e.g. dropped by Supabase's pooler)."""
    global conn
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        conn = get_db_connection()
    return conn


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
    cur = get_conn().cursor()
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

    cur = get_conn().cursor()
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

    cur = get_conn().cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING user_id",
            (username, email, password_hash)
        )
        user_id = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        get_conn().rollback()
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


@app.route('/dashboard')
@login_required
def dashboard():
    cur = get_conn().cursor()
    cur.execute("""
        SELECT tmdb_id, movie_title, poster_url, genres, watched_at
        FROM watched
        WHERE user_id = %s
        ORDER BY watched_at DESC
    """, (current_user.id,))
    watched_movies = cur.fetchall()

    genre_counter = Counter()
    for row in watched_movies:
        genres = row[3]
        if genres:
            for g in genres.split(','):
                g = g.strip()
                if g:
                    genre_counter[g] += 1

    top_genres = genre_counter.most_common(6)
    most_watched_genre = top_genres[0][0] if top_genres else "N/A"

    return render_template('dashboard.html',
                            watched_movies=watched_movies,
                            total_watched=len(watched_movies),
                            most_watched_genre=most_watched_genre,
                            genre_labels=[g[0] for g in top_genres],
                            genre_counts=[g[1] for g in top_genres])


@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_new_password = request.form.get('confirm_new_password', '')

    cur = get_conn().cursor()
    cur.execute("SELECT password_hash FROM users WHERE user_id = %s", (current_user.id,))
    row = cur.fetchone()

    if not row or not check_password_hash(row[0], current_password):
        flash("Current password is incorrect.")
        return redirect(url_for('dashboard'))

    if new_password != confirm_new_password:
        flash("New passwords don't match.")
        return redirect(url_for('dashboard'))

    if len(new_password) < 6:
        flash("New password must be at least 6 characters long.")
        return redirect(url_for('dashboard'))

    new_hash = generate_password_hash(new_password)
    cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (new_hash, current_user.id))
    flash("Password updated successfully.")
    return redirect(url_for('dashboard'))


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()

    if not user_message:
        return {"reply": "Say something and I'll help you find a movie!"}

    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=f"You are a friendly movie recommendation assistant for a site called Not Movies. Respond briefly and conversationally to: {user_message}"
        )
        return {"reply": response.text}
    except Exception as e:
        print("Gemini error:", e)
        return {"reply": "Sorry, I'm having trouble right now. Try again in a moment."}, 500


def get_tmdb_id(movie_id):
    cur = get_conn().cursor()
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
    cur = get_conn().cursor()
    cur.execute("""
    SELECT movie_id, title
    FROM movies
    WHERE title ~ '\\(\\d{4}\\)$'
    ORDER BY substring(title from '\\((\\d{4})\\)$')::int DESC
    LIMIT %s
    """, (limit,))
    return cur.fetchall()


def get_top_rated_movies(limit=20):
    cur = get_conn().cursor()
    cur.execute(f"""
        SELECT m.movie_id, m.title, ms.avg_rating
        FROM movies m
        JOIN movie_stats ms ON m.movie_id = ms.movie_id
        WHERE ms.watch_count >= 200
        ORDER BY ms.avg_rating DESC NULLS LAST
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
    cur = get_conn().cursor()
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
    cur = get_conn().cursor()

    order_clause = {
        'recent': "substring(m.title from '\\((\\d{4})\\)$')::int DESC NULLS LAST",
        'watched': 'ms.watch_count DESC NULLS LAST',
        'top_rated': 'ms.avg_rating DESC NULLS LAST'
    }.get(sort, 'm.movie_id DESC')

    having_clause = "AND ms.watch_count >= 200" if sort == 'top_rated' else ""

    conditions = []
    params = []
    if genre != 'all':
        conditions.append("m.genres ILIKE %s")
        params.append(f'%{genre}%')
    if query:
        conditions.append("m.title ILIKE %s")
        params.append(f'%{query}%')

    where_clause = f"WHERE {' AND '.join(conditions)} {having_clause}" if conditions else (f"WHERE 1=1 {having_clause}" if having_clause else "")

    count_query = f"""
        SELECT COUNT(*)
        FROM movies m
        LEFT JOIN movie_stats ms ON m.movie_id = ms.movie_id
        {where_clause}
    """
    cur.execute(count_query, params)
    total_count = cur.fetchone()[0]

    query_sql = f"""
        SELECT m.movie_id, m.title, m.genres, ms.watch_count, ms.avg_rating
        FROM movies m
        LEFT JOIN movie_stats ms ON m.movie_id = ms.movie_id
        {where_clause}
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
    cur = get_conn().cursor()
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
    genres = request.form.get('genres') or None

    cur = get_conn().cursor()
    cur.execute("SELECT 1 FROM watched WHERE user_id = %s AND tmdb_id = %s", (current_user.id, tmdb_id))
    already_watched = cur.fetchone() is not None

    if already_watched:
        cur.execute("DELETE FROM watched WHERE user_id = %s AND tmdb_id = %s", (current_user.id, tmdb_id))
        now_watched = False
    else:
        cur.execute("""
            INSERT INTO watched (user_id, tmdb_id, movie_title, poster_url, genres)
            VALUES (%s, %s, %s, %s, %s)
        """, (current_user.id, tmdb_id, title, poster_url, genres))
        now_watched = True

    return {"watched": now_watched}


@app.route('/watched/remove', methods=['POST'])
@login_required
def remove_watched():
    tmdb_id = request.form.get('tmdb_id', type=int)
    cur = get_conn().cursor()
    cur.execute("DELETE FROM watched WHERE user_id = %s AND tmdb_id = %s", (current_user.id, tmdb_id))
    return redirect(url_for('dashboard'))


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


if __name__ == "__main__":
    app.run(debug=False)