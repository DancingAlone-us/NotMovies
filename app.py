import os
from flask import Flask, render_template
from dotenv import load_dotenv
from services.tmdb import get_movie_detail
import psycopg2

load_dotenv()

app = Flask(__name__, template_folder = 'templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('Flask_Secret_Key')

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/home')
def index():
    return render_template('index.html')

@app.route('/browse')
def browse():
    return render_template('browse.html')

@app.route('/signup')

def signup():
    return render_template('signup.html')

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

def get_tmdb_id(movie_id):
    conn = get_db_connection()
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



if __name__ == "__main__":
    app.run(debug = True)