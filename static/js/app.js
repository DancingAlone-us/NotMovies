document.addEventListener('DOMContentLoaded', function () {
  const toggleBtn = document.getElementById('themeToggle');
  const icon = document.getElementById('themeIcon');

  function updateIcon(theme) {
    icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
  }

  updateIcon(document.documentElement.getAttribute('data-bs-theme'));

  toggleBtn.addEventListener('click', function () {
    const current = document.documentElement.getAttribute('data-bs-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', next);
    localStorage.setItem('theme', next);
    updateIcon(next);
  });
});

document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('watchedToggle');
  if (!toggle) return;

  const icon = document.getElementById('watchedIcon');
  const label = document.getElementById('watchedLabel');

  toggle.addEventListener('click', function () {
    const tmdbId = toggle.dataset.tmdbId;
    const title = toggle.dataset.title;
    const poster = toggle.dataset.poster;
    const genre = toggle.dataset.genres
    const currentlyWatched = toggle.dataset.watched === 'true';

    fetch('/watched/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ tmdb_id: tmdbId, title: title, poster_url: poster, genres: genre })
    })
      .then(res => res.json())
      .then(data => {
        const nowWatched = data.watched;
        toggle.dataset.watched = nowWatched;
        icon.className = nowWatched ? 'bi bi-heart-fill' : 'bi bi-heart';
        label.textContent = nowWatched ? 'Watched' : 'Already Watched?';
      })
      .catch(() => {
        
      });
  });
});