// Apply saved theme immediately to prevent flash.
(function () {
  var t = localStorage.getItem('printmap-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

function setTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  localStorage.setItem('printmap-theme', name);
  _syncThemeUI();
}

function getTheme() {
  return document.documentElement.getAttribute('data-theme') || 'dark';
}

// Kept for backwards compat with any remaining toggle buttons.
function toggleTheme() {
  setTheme(getTheme() === 'light' ? 'dark' : 'light');
}

function _syncThemeUI() {
  var theme = getTheme();
  var isDark = theme !== 'light';
  // Old ☀/🌙 toggle buttons
  document.querySelectorAll('.theme-btn').forEach(function (b) {
    b.textContent = isDark ? '☀' : '🌙';
    b.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
  });
  // Theme picker cards in Admin
  document.querySelectorAll('.theme-card').forEach(function (c) {
    c.classList.toggle('active', c.dataset.theme === theme);
  });
}

document.addEventListener('DOMContentLoaded', _syncThemeUI);
