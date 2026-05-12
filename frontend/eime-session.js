/*
 * EIME Session
 *
 * Single source of truth for the current user identity and active church.
 * Persists to localStorage; exposes a tiny pub-sub so badges/queues update
 * when the user switches identity.
 *
 * Usage:
 *   const user   = EIMESession.getUser();      // { id, name, role }
 *   const church = EIMESession.getChurch();    // 'holy_comforter'
 *   EIMESession.setUser({ id, name, role });
 *   EIMESession.onChange(() => reloadView());
 */
(function () {
  const USER_KEY   = 'eime_session_user';
  const CHURCH_KEY = 'eime_session_church';

  const DEFAULT_USER   = { id: 'guest', name: 'Guest', role: 'GUEST' };
  const DEFAULT_CHURCH = 'holy_comforter';

  const subscribers = new Set();

  function _read(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      return JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }
  function _write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
  }
  function _emit() {
    subscribers.forEach((cb) => { try { cb(); } catch (e) { console.error(e); } });
  }

  function getUser()   { return _read(USER_KEY, DEFAULT_USER); }
  function getChurch() { return _read(CHURCH_KEY, DEFAULT_CHURCH); }

  function setUser(u) {
    if (!u || !u.id) return;
    _write(USER_KEY, { id: u.id, name: u.name || u.id, role: u.role || 'STAFF' });
    _emit();
  }
  function setChurch(c) {
    if (!c) return;
    _write(CHURCH_KEY, String(c));
    _emit();
  }
  function onChange(cb) {
    subscribers.add(cb);
    return () => subscribers.delete(cb);
  }

  // Convenience headers for fetch() — backend reads X-Voter-Id / X-Church-Id
  // where available, and falls back to body fields for legacy endpoints.
  function authHeaders() {
    const u = getUser();
    return {
      'X-Voter-Id':  u.id,
      'X-User-Role': u.role,
      'X-Church-Id': getChurch(),
    };
  }

  window.EIMESession = { getUser, getChurch, setUser, setChurch, onChange, authHeaders };
})();
