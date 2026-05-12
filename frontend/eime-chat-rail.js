/*
 * EIME Chat Rail
 *
 * Vanilla JS chat panel rendered into #eime-chat-rail.
 * - POSTs to /api/chat with question (+ context job_id when available)
 * - Subscribes to eime.contextChange so the conversation knows what's on the center panel
 * - Parses chat responses for action intents (OPEN_INVOICE, OPEN_RECON, etc.)
 *   and emits via eime.dispatchAction so the center panel can react.
 * - Mobile-collapsible; close button dismisses on <1024px screens.
 */
(function () {
  let API = (typeof window !== 'undefined' && window.EIME_API) || window.location.origin;
  let containerId = 'eime-chat-rail';
  let contextRef = { page: null, payload: null };
  let messages = []; // {role:'user'|'assistant'|'system', text:string, meta?:object}

  function getPlaceholder(page) {
    const map = {
      invoices: 'Ask about this invoice…',
      reconciliation: 'Ask why a transaction didn\'t match…',
      jobs: 'Ask about invoice coding…',
      payments: 'Ask about a payment…',
      budget: 'Ask about budget variances…',
      jes: 'Ask about this journal entry…',
      vendors: 'Ask about a vendor…',
      audit: 'Ask about an audit event…',
    };
    return map[page] || 'Ask about your books…';
  }

  function applyPlaceholder() {
    const input = document.getElementById('eime-chat-input');
    if (input) {
      const page = (contextRef && contextRef.page) || null;
      input.placeholder = getPlaceholder(page);
    }
  }

  function init(opts) {
    if (opts && opts.api) API = opts.api;
    if (opts && opts.containerId) containerId = opts.containerId;
    render();
    if (window.eime && window.eime.subscribeContextChange) {
      window.eime.subscribeContextChange((ctx) => {
        contextRef = ctx || {};
        const ctxLabel = document.getElementById('eime-chat-context');
        if (ctxLabel) ctxLabel.textContent = describeContext(contextRef);
        applyPlaceholder();
      });
      // seed with current context
      contextRef = window.eime.getContext() || {};
    }
    applyPlaceholder();
  }

  function describeContext(ctx) {
    if (!ctx || !ctx.page) return 'No context';
    if (ctx.page === 'invoices' && ctx.payload && ctx.payload.job_id) {
      return `Invoice job ${String(ctx.payload.job_id).slice(0, 8)}`;
    }
    if (ctx.page === 'jobs' && ctx.payload && ctx.payload.job_id) {
      return `Job ${String(ctx.payload.job_id).slice(0, 8)}`;
    }
    if (ctx.page === 'budget') return 'Budget overview';
    if (ctx.page === 'settings') return 'Chart of Accounts';
    return ctx.page;
  }

  function render() {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = `
      <div class="flex items-center justify-between px-4 py-3 border-b border-slate-200 flex-shrink-0">
        <div>
          <p class="text-sm font-semibold text-slate-800">Assistant</p>
          <p class="text-xs text-slate-500" id="eime-chat-context">${describeContext(contextRef)}</p>
        </div>
        <button class="lg:hidden text-slate-400 hover:text-slate-700" onclick="EIMEShell.toggleChat(false)">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>

      <div id="eime-chat-messages" class="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-slate-50">
        <div class="text-xs text-slate-400 text-center py-8">
          Ask about a bill, the budget, a giving record, or anything else on this page.
        </div>
      </div>

      <div class="px-4 py-3 border-t border-slate-200 flex-shrink-0">
        <form id="eime-chat-form" class="flex gap-2">
          <input id="eime-chat-input" type="text" autocomplete="off"
            placeholder="Ask the assistant..."
            class="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:ring-2 focus:ring-navy-600 focus:border-transparent outline-none" />
          <button type="submit" id="eime-chat-send"
            class="bg-navy-900 hover:bg-navy-800 text-white rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-50">
            Send
          </button>
        </form>
        <p class="text-[10px] text-slate-400 mt-1.5">Powered by Claude</p>
      </div>
    `;

    document.getElementById('eime-chat-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const input = document.getElementById('eime-chat-input');
      const text = (input.value || '').trim();
      if (!text) return;
      input.value = '';
      sendMessage(text);
    });
  }

  function appendMessage(role, text, meta) {
    messages.push({ role, text, meta });
    const list = document.getElementById('eime-chat-messages');
    if (!list) return;
    // remove the empty seed if first message
    if (messages.length === 1) list.innerHTML = '';
    const wrap = document.createElement('div');
    if (role === 'user') {
      wrap.className = 'flex justify-end';
      wrap.innerHTML = `<div class="bg-navy-700 text-white text-sm rounded-2xl rounded-tr-sm px-3 py-2 max-w-[85%] whitespace-pre-wrap">${escapeHtml(text)}</div>`;
    } else if (role === 'assistant') {
      wrap.className = 'flex justify-start';
      const skills = meta && meta.skills_consulted && meta.skills_consulted.length
        ? `<p class="text-[10px] text-slate-400 mt-1">via ${meta.skills_consulted.join(', ')}</p>`
        : '';
      wrap.innerHTML = `<div class="max-w-[85%]">
        <div class="bg-white border border-slate-200 text-slate-800 text-sm rounded-2xl rounded-tl-sm px-3 py-2 whitespace-pre-wrap">${escapeHtml(text)}</div>
        ${skills}
      </div>`;
    } else {
      wrap.className = 'flex justify-center';
      wrap.innerHTML = `<div class="text-[11px] text-slate-400">${escapeHtml(text)}</div>`;
    }
    list.appendChild(wrap);
    list.scrollTop = list.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function sendMessage(text) {
    appendMessage('user', text);
    const sendBtn = document.getElementById('eime-chat-send');
    sendBtn.disabled = true; sendBtn.textContent = '...';

    // Add a "thinking" placeholder
    const list = document.getElementById('eime-chat-messages');
    const thinking = document.createElement('div');
    thinking.className = 'flex justify-start';
    thinking.id = 'eime-chat-thinking';
    thinking.innerHTML = `<div class="bg-white border border-slate-200 text-slate-400 text-sm rounded-2xl rounded-tl-sm px-3 py-2 italic">Thinking...</div>`;
    list.appendChild(thinking);
    list.scrollTop = list.scrollHeight;

    // Try to detect intents in user text and dispatch local actions
    const localIntent = detectLocalIntent(text);

    const body = { question: text };
    if (contextRef && contextRef.payload && contextRef.payload.job_id) {
      body.job_id = contextRef.payload.job_id;
    }

    // Forward church_id when known (so KB + manual JE creation work)
    if (contextRef && contextRef.payload && contextRef.payload.church_id) {
      body.church_id = contextRef.payload.church_id;
    } else if (window.eime && window.eime.getActiveChurch) {
      const ch = window.eime.getActiveChurch();
      if (ch) body.church_id = ch;
    }

    try {
      const r = await fetch(`${API}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      thinking.remove();
      const answer = data.answer || data.error || '(no response)';
      appendMessage('assistant', answer, {
        skills_consulted: data.skills_consulted || [],
        model: data.model,
      });

      // FR-06.2: render the manual JE draft card with Confirm / Cancel buttons.
      if (data.type === 'manual_je_draft' && data.je_draft) {
        renderManualJEDraftCard(data.je_draft);
      }

      // If response has explicit action intent payload, dispatch it
      if (data.action) {
        if (window.eime) window.eime.dispatchAction(data.action, data.action_payload || {});
      }

      // If user input matched a local intent, dispatch that as well
      if (localIntent && window.eime) {
        window.eime.dispatchAction(localIntent.action, localIntent.payload);
      }
    } catch (e) {
      thinking.remove();
      appendMessage('assistant', 'Sorry — chat is unavailable: ' + e.message);
    } finally {
      sendBtn.disabled = false; sendBtn.textContent = 'Send';
    }
  }

  /**
   * Render a draft journal-entry confirmation card in the chat rail.
   * On Confirm: POSTs to /api/jes/manual-create and dispatches OPEN_JE.
   * On Cancel: removes the card.
   */
  function renderManualJEDraftCard(jeDraft) {
    const list = document.getElementById('eime-chat-messages');
    if (!list) return;

    const wrap = document.createElement('div');
    wrap.className = 'flex justify-start fade-in';
    const lines = (jeDraft.lines || []).map((ln) => {
      const dr = Number(ln.debit) || 0;
      const cr = Number(ln.credit) || 0;
      const side = dr > 0 ? `DR $${dr.toLocaleString()}` : `CR $${cr.toLocaleString()}`;
      return `<div class="text-xs text-slate-700">
        <span class="font-mono">${escapeHtml(ln.account_number || '')}</span>
        ${escapeHtml(ln.account_name || '')}
        <span class="text-slate-500">(${escapeHtml(ln.fund_name || ln.fund_id || '')})</span>
        — <span class="font-semibold ${dr > 0 ? 'text-emerald-700' : 'text-amber-700'}">${side}</span>
      </div>`;
    }).join('');

    const totalDebits = Number(jeDraft.total_debits) || 0;
    const totalCredits = Number(jeDraft.total_credits) || 0;
    const balancedTag = jeDraft.balanced
      ? '<span class="inline-block text-[10px] px-2 py-0.5 bg-emerald-100 text-emerald-800 rounded-full">Balanced</span>'
      : '<span class="inline-block text-[10px] px-2 py-0.5 bg-red-100 text-red-800 rounded-full">UNBALANCED</span>';

    const cardId = 'eime-je-draft-' + Math.random().toString(36).slice(2, 8);
    wrap.innerHTML = `<div class="max-w-[92%] w-full">
      <div id="${cardId}" class="bg-white border border-amber-300 rounded-xl px-3 py-2 shadow-sm">
        <div class="flex items-center justify-between mb-2">
          <p class="text-xs font-semibold text-amber-800">Draft Journal Entry</p>
          ${balancedTag}
        </div>
        <p class="text-xs text-slate-600 mb-1">${escapeHtml(jeDraft.description || '')}</p>
        <div class="space-y-1 mb-2">${lines}</div>
        <p class="text-[11px] text-slate-500 mb-2">
          Total DR $${totalDebits.toLocaleString()} / Total CR $${totalCredits.toLocaleString()}
        </p>
        <div class="flex gap-2">
          <button data-act="confirm"
            class="bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded-md px-3 py-1.5 font-medium">
            Confirm
          </button>
          <button data-act="cancel"
            class="bg-white hover:bg-slate-50 border border-slate-200 text-slate-600 text-xs rounded-md px-3 py-1.5 font-medium">
            Cancel
          </button>
        </div>
      </div>
    </div>`;
    list.appendChild(wrap);
    list.scrollTop = list.scrollHeight;

    const card = wrap.querySelector('#' + cardId);
    card.querySelector('[data-act="cancel"]').addEventListener('click', () => {
      card.innerHTML = '<p class="text-xs text-slate-400">Draft cancelled.</p>';
    });
    card.querySelector('[data-act="confirm"]').addEventListener('click', async () => {
      const btns = card.querySelectorAll('button');
      btns.forEach((b) => { b.disabled = true; });
      try {
        const r = await fetch(`${API}/api/jes/manual-create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(jeDraft),
        });
        const data = await r.json();
        if (!r.ok) {
          throw new Error(data.detail || 'Failed to create JE');
        }
        card.innerHTML = `<p class="text-xs text-emerald-700">
          Created JE ${escapeHtml(data.entry_id)} (status ${escapeHtml(data.status)}).
        </p>`;
        if (window.eime) {
          window.eime.dispatchAction('OPEN_JE', { entry_id: data.entry_id });
        }
      } catch (err) {
        card.innerHTML = `<p class="text-xs text-red-700">Error: ${escapeHtml(err.message)}</p>`;
      }
    });
  }

  /**
   * Lightweight client-side intent detection so chat-driven navigation
   * works even before the backend returns structured actions.
   */
  function detectLocalIntent(text) {
    const t = text.toLowerCase();
    let m;

    // Entity-specific intents (invoice/job detail views)
    m = t.match(/open\s+invoice\s+([a-z0-9\-]+)/i);
    if (m) return { action: 'OPEN_INVOICE', payload: { invoice_id: m[1] } };
    m = t.match(/open\s+job\s+([a-z0-9\-]+)/i);
    if (m) return { action: 'OPEN_INVOICE', payload: { job_id: m[1] } };
    if (/reconcil/.test(t)) return { action: 'OPEN_RECON', payload: {} };
    if (/budget/.test(t) && /show|view|open/.test(t)) return { action: 'OPEN_BUDGET', payload: {} };

    // Page navigation intents
    const pageMap = {
      invoices: '/index.html',
      invoice: '/index.html',
      jobs: '/jobs.html',
      'je|journal': '/jes.html',
      'entry|entries': '/jes.html',
      'treasurer': '/treasurer-queue.html',
      'queue': '/treasurer-queue.html',
      'reconcil|recon': '/reconciliation.html',
      'payment|payments': '/payments.html',
      'budget': '/budget.html',
      'vendor|suppliers': '/vendors.html',
      'coa|chart|account': '/settings/coa.html',
      'audit|audit.trail|history': '/audit.html',
      'approval|chain': '/settings/approval-chains.html',
      'authorit|permission': '/settings/authorities.html',
      'knowledge|doc|reference': '/knowledge-base.html',
      'plaid|bank|link': '/settings/plaid-linking.html',
    };

    for (const [keywords, url] of Object.entries(pageMap)) {
      const keywordList = keywords.split('|');
      for (const keyword of keywordList) {
        if (t.includes(keyword)) {
          // Confirm this is a navigation intent (not just mentioning the word)
          if (/show|view|open|go.to|navigate|take.me|display/.test(t) || t.startsWith(keyword)) {
            return { action: 'NAVIGATE', payload: { url } };
          }
        }
      }
    }

    return null;
  }

  /**
   * Append a system narration message (for agent processing steps).
   * Renders as italic, centered, with a step icon.
   */
  function appendSystemNarration(text) {
    const list = document.getElementById('eime-chat-messages');
    if (!list) return;
    const wrap = document.createElement('div');
    wrap.className = 'flex justify-center';
    wrap.innerHTML = `<div class="text-[11px] text-slate-500 italic flex items-center gap-2 py-1">
      <svg class="w-3 h-3 text-slate-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>
      ${escapeHtml(text)}
    </div>`;
    list.appendChild(wrap);
    list.scrollTop = list.scrollHeight;
  }

  window.EIMEChatRail = { init, sendMessage, appendMessage, appendSystemNarration };
})();
