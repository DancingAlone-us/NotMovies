import os
from flask import Flask, render_template
from dotenv import load_dotenv
from services.tmdb import get_movie_detail, get_now_playing
import psycopg2
import requests
import json
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('FLASK_SECRET_KEY')


def get_db_connection():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = True
    return conn


conn = get_db_connection()


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
    return render_template('browse.html')


@app.route('/signup')
def signup():
    return render_template('signup.html')


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
    details = get_movie_detail_cached(tmdb_id)
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


if __name__ == "__main__":
    app.run(debug=True)