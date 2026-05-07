/*
 * Invoice Review Card — reusable component
 *
 * Usage:
 *   <div id="invoice-review-container"></div>
 *   <script src="/components/invoice-review-card.js"></script>
 *   <script>
 *     InvoiceReviewCard.render(jobData, {
 *       containerId: 'invoice-review-container',
 *       onApprove: (decisions) => fetch(...),
 *       onReject:  (decisions) => fetch(...),
 *     });
 *   </script>
 *
 * jobData fields consumed:
 *   invoice_document.{vendor_name, invoice_number, invoice_date, total_amount, line_items[]}
 *   draft_allocations.lines[].postings[]
 *   budget_check[]              (per-line budget impact)
 *   reviewed_allocations.lines[].reasons[]   (already prioritized by Phase 1.5)
 *
 * fraud_assessment is intentionally NOT rendered.
 */
(function () {
  function fmt(n) {
    const v = Number(n || 0);
    return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
    );
  }

  // ---- Confidence badge: green >=0.85, amber 0.60-0.84, red <0.60 ----
  function confidenceBadge(conf) {
    const c = Number(conf || 0);
    let cls, label;
    if (c >= 0.85) { cls = 'bg-emerald-100 text-emerald-700 border border-emerald-200'; label = 'High'; }
    else if (c >= 0.60) { cls = 'bg-amber-100 text-amber-700 border border-amber-200'; label = 'Medium'; }
    else { cls = 'bg-rose-100 text-rose-700 border border-rose-200'; label = 'Low'; }
    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}">${label} • ${(c * 100).toFixed(0)}%</span>`;
  }

  // ---- Budget status pill: only 3 colors (green/amber/red). NO fraud display. ----
  function budgetPill(status) {
    let cls, label;
    if (status === 'OVER_BUDGET') { cls = 'bg-rose-100 text-rose-700'; label = 'Over budget'; }
    else if (status === 'WARNING') { cls = 'bg-amber-100 text-amber-700'; label = 'Approaching'; }
    else if (status === 'NO_BUDGET') { cls = 'bg-slate-100 text-slate-600'; label = 'No budget'; }
    else { cls = 'bg-emerald-100 text-emerald-700'; label = 'Within budget'; }
    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}">${label}</span>`;
  }

  function headerHtml(inv) {
    const date = inv && inv.invoice_date ? inv.invoice_date : '—';
    return `
      <header class="px-6 py-5 border-b border-slate-200 bg-slate-50">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-500 font-medium">Vendor</p>
            <p class="text-lg font-semibold text-slate-800">${escapeHtml(inv && inv.vendor_name || '—')}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-500 font-medium">Invoice #</p>
            <p class="text-sm font-mono text-slate-700 mt-0.5">${escapeHtml(inv && inv.invoice_number || '—')}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wide text-slate-500 font-medium">Date</p>
            <p class="text-sm text-slate-700 mt-0.5">${escapeHtml(date)}</p>
          </div>
          <div class="text-right">
            <p class="text-xs uppercase tracking-wide text-slate-500 font-medium">Total</p>
            <p class="text-lg font-semibold text-slate-800">$${fmt(inv && inv.total_amount)}</p>
          </div>
        </div>
      </header>
    `;
  }

  function extractedSummaryHtml(lineItems) {
    const items = lineItems || [];
    if (!items.length) {
      return `<section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Extracted Line Items</h3>
        <p class="text-sm text-slate-400 italic">No line items extracted.</p>
      </section>`;
    }
    const rows = items.map((li) => `
      <tr class="border-b border-slate-100 last:border-0">
        <td class="py-2 px-3 text-xs font-mono text-slate-500">${escapeHtml(li.line_id || '')}</td>
        <td class="py-2 px-3 text-sm text-slate-700">${escapeHtml(li.description || '')}</td>
        <td class="py-2 px-3 text-sm text-right text-slate-600">${escapeHtml(li.quantity != null ? li.quantity : '')}</td>
        <td class="py-2 px-3 text-sm text-right font-mono text-slate-800">$${fmt(li.amount)}</td>
      </tr>
    `).join('');
    return `
      <section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Extracted Line Items</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-slate-200">
                <th class="py-1.5 px-3 text-left text-xs font-medium text-slate-500">#</th>
                <th class="py-1.5 px-3 text-left text-xs font-medium text-slate-500">Description</th>
                <th class="py-1.5 px-3 text-right text-xs font-medium text-slate-500">Qty</th>
                <th class="py-1.5 px-3 text-right text-xs font-medium text-slate-500">Amount</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function proposedGlHtml(job) {
    const draftLines = (job.draft_allocations && job.draft_allocations.lines) || [];
    const reviewedLines = (job.reviewed_allocations && job.reviewed_allocations.lines) || [];
    if (!draftLines.length) {
      return `<section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Proposed GL Mapping</h3>
        <p class="text-sm text-slate-400 italic">No GL allocations available yet.</p>
      </section>`;
    }
    const rows = draftLines.map((dl) => {
      const reasons = (reviewedLines.find((r) => r.line_id === dl.line_id) || {}).reasons || [];
      // A "posting" is the GL hit for that line. There may be 1+ debit/credit pairs.
      const postingRows = (dl.postings || []).filter((p) => Number(p.debit || 0) > 0).map((p) => `
        <tr class="bg-white border-b border-slate-100 last:border-0">
          <td class="py-2 px-3 text-xs font-mono text-slate-500 align-top">${escapeHtml(dl.line_id || '')}</td>
          <td class="py-2 px-3 align-top">
            <p class="text-sm text-slate-800 font-mono">${escapeHtml(p.account_number || '')}</p>
            <p class="text-xs text-slate-500">${escapeHtml(p.account_name || '')}</p>
            ${p.fund_id ? `<p class="text-[11px] text-slate-400 mt-0.5">Fund: ${escapeHtml(p.fund_id)}</p>` : ''}
          </td>
          <td class="py-2 px-3 text-right text-sm font-mono text-slate-800 align-top">$${fmt(p.debit)}</td>
          <td class="py-2 px-3 align-top">${confidenceBadge(p.confidence != null ? p.confidence : dl.confidence)}</td>
          <td class="py-2 px-3 align-top">
            <input type="text"
              data-irc-override
              data-line-id="${escapeHtml(dl.line_id || '')}"
              data-original-account="${escapeHtml(p.account_number || '')}"
              placeholder="${escapeHtml(p.account_number || 'override')}"
              class="w-28 text-xs font-mono border border-slate-200 rounded px-2 py-1 focus:ring-1 focus:ring-navy-600 outline-none" />
          </td>
        </tr>
        ${reasons.length ? `<tr class="bg-slate-50">
          <td></td>
          <td colspan="4" class="py-1.5 px-3 text-[11px] text-slate-500"><strong class="text-slate-600">Why:</strong> ${reasons.map(escapeHtml).join(' • ')}</td>
        </tr>` : ''}
      `).join('');
      return postingRows;
    }).join('');

    return `
      <section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Proposed GL Mapping</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
            <thead class="bg-slate-50">
              <tr>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Line</th>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Account</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">Debit</th>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Confidence</th>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Override Account</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function budgetImpactHtml(job) {
    const checks = job.budget_check || [];
    if (!checks.length) {
      return `<section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Budget Impact</h3>
        <p class="text-sm text-slate-400 italic">No budget configured for this church.</p>
      </section>`;
    }
    const rows = checks.map((b) => {
      const before = Number(b.annual_budget || 0) - Number(b.ytd_actual || 0);
      const after = Number(b.after);
      const pct = Number(b.consumed_pct || 0);
      return `
        <tr class="border-b border-slate-100 last:border-0">
          <td class="py-2 px-3 text-xs font-mono text-slate-500">${escapeHtml(b.line_id || '')}</td>
          <td class="py-2 px-3">
            <p class="text-sm font-mono text-slate-700">${escapeHtml(b.account_number || '')}</p>
            <p class="text-xs text-slate-500">${escapeHtml(b.account_name || '')}</p>
          </td>
          <td class="py-2 px-3 text-right text-sm font-mono text-slate-700">$${fmt(before)}</td>
          <td class="py-2 px-3 text-right text-sm font-mono text-slate-700">$${fmt(b.this_invoice)}</td>
          <td class="py-2 px-3 text-right text-sm font-mono text-slate-700">$${fmt(after)}</td>
          <td class="py-2 px-3 text-right text-sm font-semibold text-slate-700">${(pct * 100).toFixed(0)}%</td>
          <td class="py-2 px-3 text-right">${budgetPill(b.status)}</td>
        </tr>
      `;
    }).join('');
    return `
      <section class="px-6 py-4 border-b border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Budget Impact</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm border border-slate-200 rounded-lg overflow-hidden">
            <thead class="bg-slate-50">
              <tr>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Line</th>
                <th class="py-2 px-3 text-left text-xs font-medium text-slate-500">Account</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">Remaining (before)</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">This Invoice</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">Remaining (after)</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">% Consumed</th>
                <th class="py-2 px-3 text-right text-xs font-medium text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function actionBarHtml() {
    return `
      <footer class="px-6 py-4 bg-white">
        <div id="irc-rationale-row" class="hidden mb-3">
          <label class="block text-xs font-medium text-slate-600 mb-1">Override rationale (required when GL changed)</label>
          <textarea id="irc-rationale" rows="2" placeholder="Explain why you changed the GL account..."
            class="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 resize-none focus:ring-1 focus:ring-navy-600 outline-none"></textarea>
        </div>
        <div class="flex justify-end gap-2">
          <button id="irc-reject" type="button"
            class="px-4 py-2 text-sm font-medium text-rose-700 border border-rose-200 rounded-lg hover:bg-rose-50">
            Reject
          </button>
          <button id="irc-override" type="button"
            class="px-4 py-2 text-sm font-medium text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-50">
            Save Override
          </button>
          <button id="irc-approve" type="button"
            class="px-4 py-2 text-sm font-medium text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg">
            Approve
          </button>
        </div>
      </footer>
    `;
  }

  function render(jobData, opts) {
    opts = opts || {};
    const containerId = opts.containerId || 'invoice-review-container';
    const container = document.getElementById(containerId);
    if (!container) {
      console.error('InvoiceReviewCard: container not found:', containerId);
      return;
    }
    if (!jobData) {
      container.innerHTML = `<div class="text-sm text-slate-400 text-center py-8">No invoice data.</div>`;
      return;
    }

    const inv = jobData.invoice_document || {};
    container.innerHTML = `
      <article class="invoice-review-card bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        ${headerHtml(inv)}
        ${extractedSummaryHtml(inv.line_items)}
        ${proposedGlHtml(jobData)}
        ${budgetImpactHtml(jobData)}
        ${actionBarHtml()}
      </article>
    `;

    // ---- Wiring ----
    const overrideInputs = container.querySelectorAll('input[data-irc-override]');
    const rationaleRow = container.querySelector('#irc-rationale-row');

    function anyOverridden() {
      return Array.from(overrideInputs).some((inp) => (inp.value || '').trim().length > 0);
    }
    function refreshRationaleVisibility() {
      if (anyOverridden()) rationaleRow.classList.remove('hidden');
      else rationaleRow.classList.add('hidden');
    }
    overrideInputs.forEach((inp) => inp.addEventListener('input', refreshRationaleVisibility));

    function collectDecisions() {
      const overrides = [];
      overrideInputs.forEach((inp) => {
        const v = (inp.value || '').trim();
        if (v) {
          overrides.push({
            line_id: inp.getAttribute('data-line-id'),
            original_account: inp.getAttribute('data-original-account'),
            new_account: v,
          });
        }
      });
      const rationale = (container.querySelector('#irc-rationale').value || '').trim();
      return { overrides, rationale, job_id: jobData.job_id };
    }

    container.querySelector('#irc-approve').addEventListener('click', () => {
      const d = collectDecisions();
      if (d.overrides.length && !d.rationale) {
        alert('Please provide a rationale for the GL override.');
        return;
      }
      if (typeof opts.onApprove === 'function') opts.onApprove(d);
    });
    container.querySelector('#irc-override').addEventListener('click', () => {
      const d = collectDecisions();
      if (!d.overrides.length) { alert('Enter at least one override account.'); return; }
      if (!d.rationale) { alert('Override rationale is required.'); return; }
      if (typeof opts.onOverride === 'function') opts.onOverride(d);
    });
    container.querySelector('#irc-reject').addEventListener('click', () => {
      const d = collectDecisions();
      if (typeof opts.onReject === 'function') opts.onReject(d);
    });
  }

  window.InvoiceReviewCard = { render };
})();
