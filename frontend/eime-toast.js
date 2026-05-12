/*
 * EIME Toast
 *
 * Tiny replacement for alert() / confirm() / prompt() so feedback doesn't
 * pause the whole tab and looks at home in the app. Falls back to native
 * dialogs when the DOM isn't ready.
 *
 * Usage:
 *   EIMEToast.show('Vote recorded', 'success');
 *   EIMEToast.show('Quorum reached — policy active', 'success', { ttl: 6000 });
 *   EIMEToast.error('Something went wrong: ' + err);
 */
(function () {
  const CONTAINER_ID = 'eime-toast-stack';
  const STYLES = {
    success: 'bg-emerald-600 text-white',
    error:   'bg-red-600 text-white',
    info:    'bg-slate-800 text-white',
    warn:    'bg-amber-600 text-white',
  };

  function _ensureContainer() {
    let el = document.getElementById(CONTAINER_ID);
    if (el) return el;
    el = document.createElement('div');
    el.id = CONTAINER_ID;
    el.style.cssText = `
      position: fixed; right: 1rem; bottom: 1rem; z-index: 9999;
      display: flex; flex-direction: column; gap: 0.5rem;
      pointer-events: none;
    `;
    document.body.appendChild(el);
    return el;
  }

  function show(message, kind, opts) {
    if (!message) return;
    const tone = STYLES[kind || 'info'] || STYLES.info;
    const ttl  = (opts && opts.ttl) || 4000;
    if (!document.body) { try { console.log('[toast]', message); } catch (e) {} return; }
    const wrap = _ensureContainer();
    const toast = document.createElement('div');
    toast.className = 'rounded-lg shadow-lg px-4 py-3 text-sm font-medium ' + tone;
    toast.style.cssText = 'pointer-events:auto; max-width: 22rem; opacity: 0; transform: translateY(8px); transition: all 200ms ease-out;';
    toast.textContent = message;
    toast.addEventListener('click', () => _dismiss(toast));
    wrap.appendChild(toast);
    // Animate in.
    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });
    setTimeout(() => _dismiss(toast), ttl);
  }

  function _dismiss(toast) {
    if (!toast || !toast.parentNode) return;
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    setTimeout(() => { toast.parentNode && toast.parentNode.removeChild(toast); }, 220);
  }

  window.EIMEToast = {
    show,
    success: (m, o) => show(m, 'success', o),
    error:   (m, o) => show(m, 'error',   o),
    info:    (m, o) => show(m, 'info',    o),
    warn:    (m, o) => show(m, 'warn',    o),
  };
})();
