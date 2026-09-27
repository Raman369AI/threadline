'use strict';
// Runs in <head>, before the page paints, so a saved Light or Dark choice never flashes the other theme.
// Without a saved choice the stylesheet follows the system setting.
(() => {
  const key = 'threadline-theme', choices = ['system', 'light', 'dark'];
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem(key); } catch { /* Storage can be blocked, e.g. for a file:// page. */ }
  let choice = choices.includes(saved) ? saved : 'system';
  const apply = () => { if (choice === 'system') delete root.dataset.theme; else root.dataset.theme = choice; };
  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('themeButton');
    const label = () => {
      toggle.textContent = 'Theme: ' + choice[0].toUpperCase() + choice.slice(1);
      toggle.setAttribute('aria-label', `Color theme: ${choice}. Select to switch to ${choices[(choices.indexOf(choice) + 1) % choices.length]}.`);
    };
    label();
    toggle.addEventListener('click', () => {
      choice = choices[(choices.indexOf(choice) + 1) % choices.length];
      try { if (choice === 'system') localStorage.removeItem(key); else localStorage.setItem(key, choice); } catch { /* Still applies for this visit. */ }
      apply(); label();
    });
  });
})();
