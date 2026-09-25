'use strict';
// Path bar back through opened methods, the reading guide, and keyboard shortcuts.

function renderPathBar() {
  const host = $('#pathBar');
  host.hidden = !state.stack.length;
  host.replaceChildren();
  if (host.hidden) return;
  const previous = state.stack.at(-1);
  const back = button('← Back', 'quiet-button path-back', returnToCaller);
  back.title = `Return to ${scopeName(previous.scope)}`;
  const trail = el('ol', 'path-trail');
  state.stack.forEach((frame, index) => {
    const item = el('li');
    item.append(button(scopeName(frame.scope), 'path-crumb', () => returnTo(index)));
    trail.append(item);
  });
  const current = el('li'), label = el('span', 'path-current', scopeName(state.scope));
  label.setAttribute('aria-current', 'page'); current.append(label); trail.append(current);
  host.append(back, trail);
}

function toggleHelp(open) {
  const panel = $('#helpPanel'), show = open ?? panel.hidden;
  panel.hidden = !show; $('#helpButton').setAttribute('aria-expanded', String(show));
  if (show) panel.focus(); else if (panel.contains(document.activeElement) || document.activeElement === document.body) $('#helpButton').focus();
}

$('#helpButton').addEventListener('click', () => toggleHelp());
$('#helpClose').addEventListener('click', () => toggleHelp(false));
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest?.('input, textarea, select, [contenteditable]')) return;
  if (event.key === 'Escape' && !$('#helpPanel').hidden) { toggleHelp(false); return; }
  if (event.key === '?') { event.preventDefault(); toggleHelp(); return; }
  if (!state.scope || $('.workspace').classList.contains('choosing') || !$('#comparisonPanel').hidden) return;
  if (event.key === 'Backspace' && state.stack.length) { event.preventDefault(); returnToCaller(); }
});
