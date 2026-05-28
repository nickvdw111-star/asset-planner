// Run the IIFE immediately so there's no flash; the full logic fires on DOMContentLoaded.
(function () {
  var t = localStorage.getItem('printmap-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

function toggleTheme() {
  var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('printmap-theme', next);
  _syncThemeButtons();
}

function _syncThemeButtons() {
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.querySelectorAll('.theme-btn').forEach(function (b) {
    b.textContent = isDark ? '☀' : '🌙';
    b.title = isDark ? 'Switch to light mode' : 'Switch to dark mode';
  });
}

document.addEventListener('DOMContentLoaded', _syncThemeButtons);
