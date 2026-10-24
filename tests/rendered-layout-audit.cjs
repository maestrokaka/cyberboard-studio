/* Read-only browser inspection for manual CUA layout reviews.
   Inspect actual text rectangles, not just their containing element's box.
   Scrolled-out content and deliberate horizontal ellipses are not defects. */
module.exports = function auditRenderedLayout() {
  const page = document.querySelector('.page.active');
  const roots = [page, ...document.querySelectorAll('.modal-backdrop:not([hidden])')].filter(Boolean);
  const clippedText = [];
  let checkedTextRuns = 0;
  const name = e => e.id ? '#' + e.id : e.tagName.toLowerCase() + (e.classList.length ? '.' + [...e.classList].join('.') : '');
  for (const root of roots) {
    for (const element of root.querySelectorAll('*')) {
      if (['SCRIPT', 'STYLE', 'OPTION', 'TEXTAREA', 'SVG', 'TITLE'].includes(element.tagName)) continue;
      const closedDetails = element.closest('details:not([open])');
      if (closedDetails && !closedDetails.querySelector('summary')?.contains(element)) continue;
      const box = element.getBoundingClientRect();
      if (!box.width || !box.height) continue;
      for (const text of element.childNodes) {
        if (text.nodeType !== 3 || !text.textContent.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(text);
        for (const rect of range.getClientRects()) {
          if (!rect.width || !rect.height) continue;
          checkedTextRuns++;
          const constraints = [];
          let ellipsis = false;
          for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
            const style = getComputedStyle(ancestor);
            const outer = ancestor.getBoundingClientRect();
            const clamped = !['none', '0', ''].includes(style.getPropertyValue('-webkit-line-clamp'));
            ellipsis ||= style.textOverflow === 'ellipsis';
            if ((['auto', 'scroll'].includes(style.overflowY) && (rect.top < outer.top - 1 || rect.bottom > outer.bottom + 1)) ||
                (['auto', 'scroll'].includes(style.overflowX) && (rect.left < outer.left - 1 || rect.right > outer.right + 1))) {
              // Still report clipping inside the off-screen component itself;
              // only stop comparing it with outer scroll-viewport boundaries.
              break;
            }
            const vertical = ['hidden', 'clip'].includes(style.overflowY) &&
              (rect.top < outer.top - 1 || rect.bottom > outer.bottom + 1) &&
              !clamped;
            const horizontal = ['hidden', 'clip'].includes(style.overflowX) && !ellipsis &&
              (rect.left < outer.left - 1 || rect.right > outer.right + 1);
            if (vertical || horizontal) constraints.push({ancestor: name(ancestor), vertical, horizontal});
            if (ancestor === root) break;
          }
          if (constraints.length) clippedText.push({element: name(element), text: text.textContent.trim().slice(0, 70), constraints});
        }
      }
    }
  }
  const slots = [...document.querySelectorAll('.page.active .slot-card')].map(card => {
    const bounds = card.getBoundingClientRect();
    const meta = card.querySelector('.slot-meta')?.getBoundingClientRect();
    const title = card.querySelector('.slot-title')?.getBoundingClientRect();
    const actions = card.querySelector('.slot-card-actions')?.getBoundingClientRect();
    return {height: bounds.height, headerInset: meta ? meta.top - bounds.top : null,
      titleActionGap: title && actions ? actions.top - title.bottom : null};
  });
  return {page: page?.id, theme: document.documentElement.getAttribute('data-ui-theme'),
    viewport: [innerWidth, innerHeight], checkedTextRuns, clippedText, slots,
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth};
};
