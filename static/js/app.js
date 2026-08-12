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

document.addEventListener('DOMContentLoaded', function () {
  const toggle = document.getElementById('chatToggle');
  const panel = document.getElementById('chatPanel');
  const closeBtn = document.getElementById('chatClose');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const messages = document.getElementById('chatMessages');

  toggle.addEventListener('click', () => panel.classList.toggle('d-none'));
  closeBtn.addEventListener('click', () => panel.classList.add('d-none'));

  function addBubble(text, sender) {
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${sender}`;
    bubble.textContent = text;
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    addBubble(text, 'user');
    input.value = '';

    addBubble('Thinking...', 'bot');
    const thinkingBubble = messages.lastChild;

    fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    })
      .then(res => res.json())
      .then(data => {
        thinkingBubble.textContent = data.reply;
      })
      .catch(() => {
        thinkingBubble.textContent = "Sorry, something went wrong.";
      });
  });
});