import os
from dotenv import load_dotenv
import requests
import random

load_dotenv()

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w500"

def get_movie_detail(tmdb_id):
    resp = requests.get(f"{BASE_URL}/movie/{tmdb_id}", params={"api_key": TMDB_API_KEY, "append_to_response": "credits,videos"})
    resp.raise_for_status()
    data = resp.json()

    trailer = next(
        (v for v in data.get("videos", {}).get("results", [])
         if v["site"] == "YouTube" and v["type"] == "Trailer"),
        None
    )

    release_date = data.get("release_date", "")

    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "synopsis": data.get("overview"),
        "poster_url": f"{IMG_BASE}{data['poster_path']}" if data.get("poster_path") else None,
        "backdrop_url": f"{IMG_BASE}{data['backdrop_path']}" if data.get("backdrop_path") else None,
        "cast": data.get("credits", {}).get("cast", [])[:10],
        "trailer_key": trailer["key"] if trailer else None,
        "rating": data.get("vote_average"),
        "release_year": release_date[:4] if release_date else None,
        "genres": [g["name"] for g in data.get("genres", [])]
    }

def get_now_playing(limit = 8):
    resp = requests.get(f"{BASE_URL}/movie/now_playing", params={"api_key": TMDB_API_KEY, 'region': "US"})
    resp.raise_for_status()
    results = resp.json().get('results', [])[:limit]
    return [{
        "tmdb_id": m["id"],
        "title": m["title"],
        "poster_url": f"{IMG_BASE}{m['poster_path']}" if m.get("poster_path") else None,
        "rating": m.get("vote_average"),
        "movie_id": None
    } for m in results]


def get_random_tmdb_movie():
    random_page = random.randint(1, 500)
    resp = requests.get(
        f"{BASE_URL}/discover/movie",
        params={
            "api_key": TMDB_API_KEY,
            "page": random_page,
            "vote_count.gte": 200,
            "sort_by": "popularity.desc"
        }
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    return random.choice(results)["id"]

def search_tmdb(query, page=1):
    resp = requests.get(
        f"{BASE_URL}/search/movie",
        params={"api_key": TMDB_API_KEY, "query": query, "page": page}
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [{
        "tmdb_id": m["id"],
        "title": m["title"],
        "poster_url": f"{IMG_BASE}{m['poster_path']}" if m.get("poster_path") else None,
        "rating": m.get("vote_average"),
        "movie_id": None
    } for m in results]