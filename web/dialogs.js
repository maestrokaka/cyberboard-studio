/* Keep keyboard and assistive-technology focus inside the visible dialog. */
(function () {
 'use strict';
 if (typeof MutationObserver !== 'function') return;
 const backdrops = [...document.querySelectorAll('.modal-backdrop')];
 const shell = document.querySelector('.app-shell');
 let active = null, returnFocus = null, previousAria = null;
 const focusable = dialog => [...dialog.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')]
  .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
 function refresh() {
  const next = backdrops.find(el => !el.hidden) || null;
  if (next === active) return;
  if (!active && next) {
   returnFocus = document.activeElement;
   previousAria = shell?.getAttribute('aria-hidden');
   if (shell) { shell.inert = true; shell.setAttribute('aria-hidden', 'true'); }
  }
  active = next;
  if (active) {
   const cancel = active.querySelector('#cancelSyncBtn,#libraryConfirmCancelBtn');
   const target = cancel && !cancel.disabled ? cancel : focusable(active)[0];
   target?.focus();
  } else {
   if (shell) {
    shell.inert = false;
    if (previousAria === null) shell.removeAttribute('aria-hidden');
    else shell.setAttribute('aria-hidden', previousAria);
   }
   if (returnFocus?.isConnected && !returnFocus.disabled && returnFocus.getClientRects().length) returnFocus.focus();
   returnFocus = null;
  }
 }
 const observer = new MutationObserver(refresh);
 backdrops.forEach(el => observer.observe(el, { attributes: true, attributeFilter: ['hidden'] }));
 document.addEventListener('keydown', event => {
  if (!active || event.key !== 'Tab') return;
  const items = focusable(active);
  if (!items.length) { event.preventDefault(); return; }
  const first = items[0], last = items[items.length - 1];
  if (event.shiftKey && (document.activeElement === first || !active.contains(document.activeElement))) {
   event.preventDefault(); last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !active.contains(document.activeElement))) {
   event.preventDefault(); first.focus();
  }
 }, true);
 refresh();
})();
