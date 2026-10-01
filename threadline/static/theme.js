'use strict';
// Runs in <head>, before the page paints, so a saved Light or Dark choice never flashes the other theme.
// Without a saved choice the page is Dark; System follows the operating system setting.
(() => {
  const key = 'threadline-theme', choices = ['dark', 'light', 'system'];
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem(key); } catch { /* Storage can be blocked, e.g. for a file:// page. */ }
  let choice = choices.includes(saved) ? saved : 'dark';
  const apply = () => { if (choice === 'system') delete root.dataset.theme; else root.dataset.theme = choice; };
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('themeButton');
    // Moon for Dark, sun for Light, monitor for System.
    const glyphs = {dark:'M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z', light:'M12 3v2m0 14v2M5.6 5.6L7 7m10 10l1.4 1.4M3 12h2m14 0h2M5.6 18.4L7 17M17 7l1.4-1.4M16 12a4 4 0 11-8 0 4 4 0 018 0z', system:'M4 5h16v11H4zM9 20h6m-3-4v4'};
    const label = () => {
      const text = 'Theme: ' + choice[0].toUpperCase() + choice.slice(1);
      toggle.querySelector('.sr-only').textContent = text;
      toggle.querySelector('path').setAttribute('d', glyphs[choice]);
      toggle.title = `${text}. Select to switch to ${choices[(choices.indexOf(choice) + 1) % choices.length]}.`;
    };
    label();
    toggle.addEventListener('click', () => {
      choice = choices[(choices.indexOf(choice) + 1) % choices.length];
      try { if (choice === 'dark') localStorage.removeItem(key); else localStorage.setItem(key, choice); } catch { /* Still applies for this visit. */ }
      apply(); label();
    });
  });
})();
