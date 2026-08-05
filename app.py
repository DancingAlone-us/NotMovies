import os
from flask import Flask, render_template
from dotenv import load_dotenv
from services.tmdb import get_movie_detail, get_now_playing
import psycopg2
import requests

load_dotenv()

app = Flask(__name__, template_folder = 'templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('Flask_Secret_Key')

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

conn = get_db_connection()

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/home')
def index():
    new_movies = get_now_playing(limit = 8)
    print('new movies count:', len(new_movies))

    top_movie_raw = get_top_rated_movies(limit=20)
    print('top movies count raw', len(top_movie_raw))
    top_movies = use_tmdb(top_movie_raw)[:8]
    print('count', len(top_movies))

    featured_movie = top_movies[:5]
    return render_template('index.html', featured_movie = featured_movie, new_movies = new_movies, top_movies = top_movies)

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
    details = get_movie_detail(tmdb_id)
    return render_template('movie_detail.html', movie = details)

@app.route('/movie/tmdb/<int:tmdb_id>')
def movie_detail_tmdb(tmdb_id):
    try:
        details = get_movie_detail(tmdb_id)
    except requests.exceptions.HTTPError:
        return "Movie Not Found",404
    details['movie_id'] = None
    return render_template('movie_detail.html', movie = details)

def get_new_movies(limit = 8):
    cur = conn.cursor()
    cur.execute("""
    SELECT movie_id, title
    FROM movies
    WHERE title ~ '\\(\\d{4}\\)$'
    ORDER BY substring(title from '\\((\\d{4})\\)$')::int DESC
    LIMIT %s
    """, (limit,))
    return cur.fetchall()

def get_top_rated_movies(limit=10):
    cur = conn.cursor()
    cur.execute("""
        SELECT m.movie_id, m.title, AVG(r.rating) as avg_rating
        FROM movies m
        JOIN ratings r ON m.movie_id = r.movie_id
        GROUP BY m.movie_id, m.title
        HAVING COUNT(r.rating) >= 200
        ORDER BY avg_rating DESC
        LIMIT %s
    """, (limit,))
    return cur.fetchall()



def use_tmdb(rows):
    use = []
    for row in rows:
        movie_id = row[0]
        tmdb_id = get_tmdb_id(movie_id)
        if not tmdb_id:
            continue
        try:
            details = get_movie_detail(tmdb_id)
        except requests.exceptions.HTTPError:
            continue
        details['movie_id'] = movie_id
        use.append(details)
    return use



if __name__ == "__main__":
    app.run(debug = True)