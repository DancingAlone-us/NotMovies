CREATE TABLE movies(
    movie_id INTEGER PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    genres VARCHAR(255) NOT NULL
);

CREATE TABLE links(
    movie_id INTEGER PRIMARY KEY REFERENCES movies(movie_id),
    imdb_id VARCHAR(20),
    tmdb_id INTEGER
);

CREATE TABLE ratings(
    user_id INTEGER,
    movie_id INTEGER REFERENCES movies(movie_id),
    rating NUMERIC(2,1),
    timestamp BIGINT
);

CREATE TABLE tags(
    user_id INTEGER,
    movie_id INTEGER REFERENCES movies(movie_id),
    tag TEXT,
    timestamp BIGINT
);

CREATE TABLE tmdb_cache(
    tmdb_id INTEGER PRIMARY KEY,
    data JSONB NOT NULL,
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);