import os
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
from services.tmdb import get_movie_detail, get_now_playing, get_random_tmdb_movie, search_tmdb
import psycopg2
import requests
import json
from datetime import datetime, timedelta
import random

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


if __name__ == "__main__":
    app.run(debug=True)