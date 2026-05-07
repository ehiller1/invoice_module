/*
 * EIME Responsive Helper for legacy pages
 * Phase 3.9 — Mobile / Tablet Responsive UI (FR-10.5)
 *
 * Pages that DON'T use _shell.html (index, jobs, budget, coa, chat, skills)
 * have a hardcoded sidebar. responsive.css hides that sidebar below `lg`.
 * This script then:
 *   - injects a top bar with a hamburger button (left) + chat FAB (right)
 *   - clones the existing <aside> sidebar into a slide-in drawer
 *   - wires open/close behavior on click + outside-tap + swipe-left
 *   - adds a chat FAB which navigates to /chat.html (legacy chat page).
 *
 * Usage: include after the page's main markup.
 *   <script src="/eime-responsive.js"></script>
 *
 * Idempotent: doesn't run if shell already mounted.
 */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  function isShellPage() {
    return !!document.getElementById('eime-shell-root');
  }

  function findLegacySidebar() {
    // Hardcoded legacy sidebars are <aside class="w-64 bg-navy-900 ...">
    return document.querySelector('body > div.flex.h-full > aside.w-64');
  }

  function findMain() {
    return document.querySelector('body > div.flex.h-full > main');
  }

  function getPageTitle() {
    const h1 = document.querySelector('main header h1');
    if (h1) return h1.textContent.trim().split('\n')[0].slice(0, 30);
    return document.title.split('—')[0].trim() || 'EIME';
  }

  function injectTopBar(main) {
    if (document.getElementById('eime-rsv-topbar')) return;
    const bar = document.createElement('div');
    bar.id = 'eime-rsv-topbar';
    bar.className = 'eime-rsv-topbar lg:hidden';
    bar.innerHTML = `
      <button id="eime-rsv-menu-btn" aria-label="Open menu">
        <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
        </svg>
      </button>
      <p style="font-size:0.875rem;font-weight:600;flex:1;text-align:center;">${escapeHtml(getPageTitle())}</p>
      <a id="eime-rsv-chat-link" href="/chat.html" aria-label="Open chat" style="color:#fff;display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;">
        <svg width="22" height="22" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
        </svg>
      </a>
    `;
    main.parentNode.insertBefore(bar, main);
  }

  function injectDrawer(sidebar) {
    if (document.getElementById('eime-rsv-drawer')) return;
    const drawer = document.createElement('div');
    drawer.id = 'eime-rsv-drawer';
    drawer.className = 'eime-rsv-drawer';

    const clone = sidebar.cloneNode(true);
    // Remove width constraints from the clone so it fills the drawer.
    clone.classList.remove('w-64', 'w-60');
    clone.style.display = 'flex';
    clone.style.width = '100%';
    clone.style.height = '100%';
    drawer.appendChild(clone);

    const backdrop = document.createElement('div');
    backdrop.id = 'eime-rsv-backdrop';
    backdrop.className = 'eime-rsv-backdrop';

    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);
  }

  function injectFAB() {
    if (document.getElementById('eime-rsv-fab')) return;
    // Don't inject FAB on chat.html itself
    if (location.pathname.endsWith('/chat.html')) return;
    const btn = document.createElement('button');
    btn.id = 'eime-rsv-fab';
    btn.className = 'eime-rsv-fab';
    btn.setAttribute('aria-label', 'Open chat');
    btn.innerHTML = `
      <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
      </svg>
    `;
    btn.addEventListener('click', () => {
      window.location.href = '/chat.html';
    });
    document.body.appendChild(btn);
  }

  function wireDrawer() {
    const drawer = document.getElementById('eime-rsv-drawer');
    const backdrop = document.getElementById('eime-rsv-backdrop');
    const btn = document.getElementById('eime-rsv-menu-btn');
    if (!drawer || !backdrop || !btn) return;

    function open() {
      drawer.classList.add('is-open');
      backdrop.classList.add('is-open');
    }
    function close() {
      drawer.classList.remove('is-open');
      backdrop.classList.remove('is-open');
    }

    btn.addEventListener('click', open);
    backdrop.addEventListener('click', close);

    // Swipe-left to dismiss
    let touchStartX = 0;
    drawer.addEventListener('touchstart', (e) => {
      touchStartX = e.touches[0].clientX;
    }, { passive: true });
    drawer.addEventListener('touchend', (e) => {
      const dx = e.changedTouches[0].clientX - touchStartX;
      if (dx < -50) close();
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });

    // Close on viewport resize >=lg
    window.addEventListener('resize', () => {
      if (window.innerWidth >= 1024) close();
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  ready(function () {
    if (isShellPage()) return; // shell handles its own responsive UI
    const sidebar = findLegacySidebar();
    const main = findMain();
    if (!sidebar || !main) return;

    injectTopBar(main);
    injectDrawer(sidebar);
    injectFAB();
    wireDrawer();
  });
})();
