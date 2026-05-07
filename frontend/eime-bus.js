/*
 * EIME Event Bus
 *
 * Provides a vanilla JS pub/sub bus for inter-panel communication:
 *   - center panel announces context via setContext()
 *   - chat rail listens via subscribeContextChange()
 *   - chat rail dispatches actions via dispatchAction()
 *   - center panel handles them via subscribeAction()
 *
 * Exposed as window.eime.
 */
(function () {
  if (window.eime) return; // singleton

  const _ctxListeners = [];
  const _actionListeners = {}; // { actionType: [fn, fn] }
  let _currentContext = { page: null, payload: null };

  window.eime = {
    /**
     * Center-panel calls this to announce what is currently displayed.
     * @param {object} ctx { page: 'budget'|'jobs'|'invoices'|..., payload: any }
     */
    setContext(ctx) {
      _currentContext = ctx || {};
      _ctxListeners.forEach((fn) => {
        try { fn(_currentContext); } catch (e) { console.error('eime ctx listener', e); }
      });
    },

    /** Returns the most-recently-set context, or {}. */
    getContext() {
      return _currentContext;
    },

    /**
     * Chat rail subscribes to be notified when the center context changes.
     * @param {function} fn called with the new context object
     * @returns {function} unsubscribe
     */
    subscribeContextChange(fn) {
      _ctxListeners.push(fn);
      return () => {
        const i = _ctxListeners.indexOf(fn);
        if (i >= 0) _ctxListeners.splice(i, 1);
      };
    },

    /**
     * Chat rail issues a command for the center panel to act on.
     * @param {string} action e.g. 'OPEN_INVOICE', 'OPEN_RECON'
     * @param {object} payload action-specific
     */
    dispatchAction(action, payload) {
      const subs = _actionListeners[action] || [];
      subs.forEach((fn) => {
        try { fn(payload); } catch (e) { console.error('eime action', action, e); }
      });
      // Also broadcast as a window event for any listener
      window.dispatchEvent(new CustomEvent('eime.action', {
        detail: { action, payload }
      }));
    },

    /**
     * Center panel registers handlers for actions issued by the chat rail.
     * @param {string} action
     * @param {function} fn called with payload
     * @returns {function} unsubscribe
     */
    subscribeAction(action, fn) {
      if (!_actionListeners[action]) _actionListeners[action] = [];
      _actionListeners[action].push(fn);
      return () => {
        const arr = _actionListeners[action] || [];
        const i = arr.indexOf(fn);
        if (i >= 0) arr.splice(i, 1);
      };
    },
  };
})();
