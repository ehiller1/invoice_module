/*
 * EIME Shell Loader
 *
 * Usage from any page:
 *   <script src="/eime-bus.js"></script>
 *   <script src="/eime-chat-rail.js"></script>
 *   <script src="/eime-shell.js"></script>
 *   <script>
 *     EIMEShell.mount({
 *       activeNav: 'budget',
 *       centerContent: '<div>...page html...</div>',
 *       onMounted: () => { ...page-specific js... }
 *     });
 *   </script>
 *
 * The shell HTML is fetched from /_shell.html and replaces the document body.
 */
(function () {
  const SHELL_URL = '/_shell.html';
  const API = (typeof window !== 'undefined' && window.EIME_API) || 'http://localhost:8000';

  async function mount(opts) {
    opts = opts || {};
    const activeNav = opts.activeNav || 'invoices';
    const centerContent = opts.centerContent || '';

    // Fetch shell html
    let shellHtml;
    try {
      const r = await fetch(SHELL_URL, { cache: 'no-cache' });
      shellHtml = await r.text();
    } catch (e) {
      console.error('EIMEShell: failed to load shell', e);
      return;
    }

    // Inject shell into a fresh body
    document.body.innerHTML = shellHtml;
    document.body.classList.add('h-full', 'bg-slate-50', 'font-sans', 'overflow-hidden');
    document.documentElement.classList.add('h-full');

    // Ensure responsive.css is loaded
    if (!document.querySelector('link[data-eime-responsive]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/responsive.css';
      link.setAttribute('data-eime-responsive', '1');
      document.head.appendChild(link);
    }

    // Inject center content
    const centerEl = document.getElementById('eime-center');
    if (centerEl) centerEl.innerHTML = centerContent;

    // Highlight active sidebar nav link
    document.querySelectorAll('.eime-nav-link').forEach((a) => {
      const isActive = a.getAttribute('data-nav') === activeNav;
      if (isActive) {
        a.classList.remove('text-slate-300', 'hover:text-white', 'hover:bg-navy-700');
        a.classList.add('text-white', 'bg-navy-700');
      }
    });

    // Highlight active mobile tab
    document.querySelectorAll('.eime-mobile-tab[data-nav]').forEach((tab) => {
      if (tab.getAttribute('data-nav') === activeNav) {
        tab.classList.remove('text-slate-400');
        tab.classList.add('text-white');
      }
    });

    // Initialize the chat rail
    if (window.EIMEChatRail && typeof window.EIMEChatRail.init === 'function') {
      window.EIMEChatRail.init({ containerId: 'eime-chat-rail', api: API });
    } else {
      console.warn('EIMEShell: EIMEChatRail not loaded');
    }

    // Subscribe to NAVIGATE action for chat-driven page navigation
    if (window.eime && typeof window.eime.subscribeAction === 'function') {
      window.eime.subscribeAction('NAVIGATE', (payload) => {
        if (payload && payload.url) {
          window.location.href = payload.url;
        }
      });
    }

    // Load church name badge
    loadChurchBadge();

    // Poll HITL count — updates all [data-badge="hitl"] elements
    refreshHitlBadge();
    setInterval(refreshHitlBadge, 15000);

    // Poll inbox count — updates all [data-badge="inbox"] elements
    refreshInboxBadge();
    setInterval(refreshInboxBadge, 15000);

    // Restore admin nav collapsed state from localStorage
    try {
      if (localStorage.getItem('eime_admin_nav') === '1') {
        toggleAdminNav(true);
      }
    } catch(e) {}

    // Wire mobile breakpoint listeners
    window.addEventListener('resize', _adjustToBreakpoint);
    _adjustToBreakpoint();

    // Swipe-down to dismiss the mobile chat bottom-sheet
    _wireChatSwipeDismiss();

    // Close drawers on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && window.innerWidth < 1024) {
        toggleNav(false);
        toggleChat(false);
      }
    });

    if (typeof opts.onMounted === 'function') {
      try { opts.onMounted(); } catch (e) { console.error('onMounted error', e); }
    }
  }

  function _adjustToBreakpoint() {
    const isLg = window.innerWidth >= 1024;
    const nav = document.getElementById('eime-left-nav');
    const chat = document.getElementById('eime-chat-rail');
    const navBd = document.getElementById('eime-nav-backdrop');
    const chatBd = document.getElementById('eime-chat-backdrop');
    if (!nav || !chat) return;
    if (isLg) {
      nav.classList.remove('hidden'); nav.classList.add('flex');
      chat.classList.remove('hidden'); chat.classList.add('flex');
      navBd && navBd.classList.add('hidden');
      chatBd && chatBd.classList.add('hidden');
    } else {
      nav.classList.add('hidden'); nav.classList.remove('flex');
      chat.classList.add('hidden'); chat.classList.remove('flex');
    }
  }

  function toggleNav(show) {
    const nav = document.getElementById('eime-left-nav');
    const bd = document.getElementById('eime-nav-backdrop');
    if (!nav) return;
    if (show) {
      nav.classList.remove('hidden'); nav.classList.add('flex');
      bd && bd.classList.remove('hidden');
    } else {
      if (window.innerWidth < 1024) {
        nav.classList.add('hidden'); nav.classList.remove('flex');
      }
      bd && bd.classList.add('hidden');
    }
  }

  function toggleChat(show) {
    const chat = document.getElementById('eime-chat-rail');
    const bd = document.getElementById('eime-chat-backdrop');
    const fab = document.getElementById('eime-chat-fab');
    if (!chat) return;
    if (show) {
      chat.classList.remove('hidden'); chat.classList.add('flex');
      bd && bd.classList.remove('hidden');
      fab && fab.classList.add('hidden');
    } else {
      if (window.innerWidth < 1024) {
        chat.classList.add('hidden'); chat.classList.remove('flex');
      }
      bd && bd.classList.add('hidden');
      fab && fab.classList.remove('hidden');
    }
  }

  function _wireChatSwipeDismiss() {
    const chat = document.getElementById('eime-chat-rail');
    if (!chat || chat.__eimeSwipeWired) return;
    chat.__eimeSwipeWired = true;
    let touchStartY = 0;
    let touchStartX = 0;
    chat.addEventListener('touchstart', (e) => {
      touchStartY = e.touches[0].clientY;
      touchStartX = e.touches[0].clientX;
    }, { passive: true });
    chat.addEventListener('touchend', (e) => {
      if (window.innerWidth >= 1024) return;
      const dy = e.changedTouches[0].clientY - touchStartY;
      const dx = Math.abs(e.changedTouches[0].clientX - touchStartX);
      if (dy > 50 && dx < 60) {
        toggleChat(false);
      }
    });
  }

  async function loadChurchBadge() {
    try {
      const r = await fetch(`${API}/api/churches`);
      const churches = await r.json();
      if (churches[0]) {
        const el = document.getElementById('eime-church-name-label');
        if (el) el.textContent = churches[0].church_name;
      }
    } catch (e) { /* offline */ }
  }

  async function refreshHitlBadge() {
    try {
      const r = await fetch(`${API}/api/jobs`);
      const jobs = await r.json();
      const cnt = jobs.filter((j) => j.status === 'PENDING_HITL').length;
      document.querySelectorAll('[data-badge="hitl"]').forEach((el) => {
        if (cnt > 0) { el.textContent = cnt; el.classList.remove('hidden'); }
        else el.classList.add('hidden');
      });
    } catch (e) { /* offline */ }
  }

  function toggleAdminNav(forceShow) {
    const section = document.getElementById('eime-admin-section');
    const arrow = document.getElementById('eime-more-arrow');
    if (!section) return;
    const show = forceShow !== undefined ? forceShow : section.classList.contains('hidden');
    if (show) {
      section.classList.remove('hidden');
      section.classList.add('flex');
      if (arrow) arrow.textContent = '▴';
      try { localStorage.setItem('eime_admin_nav', '1'); } catch(e) {}
    } else {
      section.classList.remove('flex');
      section.classList.add('hidden');
      if (arrow) arrow.textContent = '▾';
      try { localStorage.setItem('eime_admin_nav', '0'); } catch(e) {}
    }
  }

  async function refreshInboxBadge() {
    try {
      const API_BASE = (typeof window !== 'undefined' && window.EIME_API) || 'http://localhost:8000';
      const church = 'holy_comforter';
      const [exRes, qRes] = await Promise.all([
        fetch(`${API_BASE}/api/churches/${church}/exceptions`).catch(() => null),
        fetch(`${API_BASE}/api/churches/${church}/questions`).catch(() => null),
      ]);
      let count = 0;
      if (exRes && exRes.ok) { const d = await exRes.json(); const exArr = Array.isArray(d) ? d : (d?.exceptions || []); count += exArr.filter(e => (e.status || '').toUpperCase() === 'OPEN').length; }
      if (qRes && qRes.ok) { const d = await qRes.json(); const qArr = Array.isArray(d) ? d : (d?.questions || []); count += qArr.filter(q => (q.status || '').toUpperCase() === 'OPEN').length; }
      document.querySelectorAll('[data-badge="inbox"]').forEach((el) => {
        if (count > 0) { el.textContent = count; el.classList.remove('hidden'); }
        else el.classList.add('hidden');
      });
    } catch(e) { /* offline */ }
  }

  window.EIMEShell = { mount, toggleNav, toggleChat, toggleAdminNav };
})();
