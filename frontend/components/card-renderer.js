/**
 * CardRenderer — generic card type renderer with privacy/authority gating (FRD §16, UCS-02, UCS-10).
 *
 * Renders all eight card types (EventCard, DecisionCard, ExceptionCard, PolicyCard,
 * RecommendationCard, ReconciliationCard, QuestionCard, ForecastCard).
 *
 * Privacy-aware: P0 content invisible below T3, P1 masked by default below T2 with reveal.
 * State-driven affordances: different buttons/actions based on CardState.
 * Reusable across Operations Council, Trace Viewer, and individual detail screens.
 */

class CardRenderer {
  static PRIVACY_LEVELS = {
    P0: { tier: 3, label: 'Pastoral (T3+ only)' },
    P1: { tier: 2, label: 'Donor PII (masked <T2)' },
    P2: { tier: 1, label: 'Internal Staff (T1+)' },
    P3: { tier: 0, label: 'Public' }
  };

  static CARD_TYPES = {
    event: 'EventCard',
    decision: 'DecisionCard',
    exception: 'ExceptionCard',
    policy: 'PolicyCard',
    recommendation: 'RecommendationCard',
    reconciliation: 'ReconciliationCard',
    question: 'QuestionCard',
    forecast: 'ForecastCard'
  };

  /**
   * Check if field should be visible at current authority tier.
   * @param {string} privacyClass - P0, P1, P2, or P3
   * @param {number} userAuthorityTier - 0 (guest), 1 (T1), 2 (T2), 3 (T3+)
   * @returns {boolean}
   */
  static canView(privacyClass, userAuthorityTier) {
    const required = this.PRIVACY_LEVELS[privacyClass]?.tier || 0;
    return userAuthorityTier >= required;
  }

  /**
   * Mask PII field for display below reveal threshold.
   * @param {string} value - original value
   * @param {string} privacyClass
   * @param {number} userAuthorityTier
   * @param {boolean} revealed - has user clicked reveal button?
   * @returns {string}
   */
  static maskIfNeeded(value, privacyClass, userAuthorityTier, revealed = false) {
    if (privacyClass !== 'P1' || userAuthorityTier >= 2 || revealed) {
      return value;
    }
    // P1 below T2: show length and first/last 2 chars
    if (value.length <= 4) return '••••';
    return value.substring(0, 2) + '•'.repeat(value.length - 4) + value.substring(value.length - 2);
  }

  /**
   * Render an EventCard (economic event with provenance).
   */
  static renderEventCard(card, userTier = 0, onReveal = null) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Pastoral content restricted to T3+ authorization level</p>
      </div>`;
    }

    const counterpartyName = card.counterparty?.display_name || 'Unknown';
    const glAccount = card.classification?.gl_account || 'Unclassified';

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">Event</p>
          <p class="text-lg font-bold text-slate-900">${card.event_type}</p>
        </div>
        <div class="text-right text-xs text-slate-500">
          <p>v${card.version}</p>
          <p>${new Date(card.created_at).toLocaleDateString()}</p>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p class="text-xs text-slate-500 mb-1">Amount</p>
          <p class="text-xl font-bold text-slate-900">$${card.amount.toFixed(2)}</p>
        </div>
        <div>
          <p class="text-xs text-slate-500 mb-1">GL Account</p>
          <p class="font-mono text-sm text-slate-700">${glAccount}</p>
        </div>
        <div>
          <p class="text-xs text-slate-500 mb-1">Counterparty</p>
          <p class="text-sm text-slate-700">${counterpartyName}</p>
        </div>
        <div>
          <p class="text-xs text-slate-500 mb-1">Confidence</p>
          <p class="text-sm text-slate-700">${(card.confidence * 100).toFixed(0)}%</p>
        </div>
      </div>
      <div class="text-xs text-slate-600 bg-slate-50 rounded p-2">
        <p class="font-mono">${card.event_id}</p>
      </div>
    </div>`;
  }

  /**
   * Render a DecisionCard (decision with reasoning chain).
   */
  static renderDecisionCard(card, userTier = 0, onReveal = null) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Pastoral content restricted to T3+ authorization level</p>
      </div>`;
    }

    const reasoning = card.reasoning || {};
    const actor = card.authoring_actor || {};

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">Decision</p>
          <p class="text-lg font-bold text-slate-900">${card.decision_type}</p>
        </div>
        <div class="text-right text-xs text-slate-500">
          <p>v${card.version}</p>
          <p>${new Date(card.created_at).toLocaleDateString()}</p>
        </div>
      </div>
      <div class="bg-blue-50 border border-blue-200 rounded p-3 mb-4">
        <p class="text-sm text-blue-900">
          <strong>By:</strong> ${actor.actor_type || 'system'} (${actor.authority_tier || 'unknown'})
        </p>
        ${reasoning.conclusion ? `<p class="text-sm text-blue-900 mt-2"><strong>Reasoning:</strong> ${reasoning.conclusion}</p>` : ''}
      </div>
      ${card.alternatives && card.alternatives.length > 0 ? `
        <div class="mb-4">
          <p class="text-xs font-semibold text-slate-700 mb-2">Alternatives Considered</p>
          <ul class="space-y-2 text-sm text-slate-700">
            ${card.alternatives.map(alt => `
              <li class="bg-amber-50 rounded p-2">
                <p class="font-medium">${alt.description}</p>
                <p class="text-xs text-amber-900">Rejected: ${alt.rejection_rationale}</p>
              </li>
            `).join('')}
          </ul>
        </div>
      ` : ''}
      <div class="text-xs text-slate-600 bg-slate-50 rounded p-2">
        <p class="font-mono">${card.decision_id}</p>
      </div>
    </div>`;
  }

  /**
   * Render an ExceptionCard (exception requiring human judgment).
   */
  static renderExceptionCard(card, userTier = 0, onAction = null) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Pastoral content restricted to T3+ authorization level</p>
      </div>`;
    }

    // Normalise field names: API returns status/title/card_id; schema uses state/summary/exception_id
    const priority = card.priority || card.severity || 'NORMAL';
    const state    = card.state || card.status || 'OPEN';
    const summary  = card.summary || card.title || '';
    const excId    = card.exception_id || card.card_id || '';
    const body     = card.details?.reason || card.details?.description || card.description || '';

    const priorityColor = {
      HIGH: 'bg-red-100 border-red-300 text-red-900',
      NORMAL: 'bg-yellow-100 border-yellow-300 text-yellow-900',
      LOW: 'bg-blue-100 border-blue-300 text-blue-900'
    }[priority] || 'bg-slate-100';

    const stateColor = {
      OPEN: 'bg-red-50 text-red-700',
      IN_REVIEW: 'bg-yellow-50 text-yellow-700',
      RESOLVED: 'bg-green-50 text-green-700',
      CLOSED: 'bg-slate-50 text-slate-700',
      PAUSED: 'bg-orange-50 text-orange-700'
    }[state] || 'bg-slate-50';

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">${card.exception_type || ''}</p>
          <p class="text-lg font-bold text-slate-900">${summary}</p>
        </div>
        <div class="text-right">
          <p class="text-xs font-semibold rounded px-2 py-1 ${priorityColor}">${priority}</p>
          <p class="text-xs font-semibold rounded px-2 py-1 ${stateColor} mt-2">${state}</p>
        </div>
      </div>
      <p class="text-sm text-slate-700 mb-4">${body}</p>
      ${card.assigned_to ? `
        <p class="text-xs text-slate-600 mb-4">👤 Assigned to: ${card.assigned_to}</p>
      ` : ''}
      <div class="flex gap-2">
        ${state === 'OPEN' ? `
          <button onclick="if(window.onExceptionApprove) window.onExceptionApprove('${excId}')"
            class="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700">Approve</button>
          <button onclick="if(window.onExceptionReject) window.onExceptionReject('${excId}')"
            class="text-xs px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700">Reject</button>
          <button onclick="if(window.onExceptionRoute) window.onExceptionRoute('${excId}')"
            class="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">Route</button>
        ` : ''}
      </div>
    </div>`;
  }

  /**
   * Render a RecommendationCard (NBA candidate with projected impact).
   */
  static renderRecommendationCard(card, userTier = 0, onAction = null) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Pastoral content restricted to T3+ authorization level</p>
      </div>`;
    }

    const impact = card.impact_projection || card.evidence || {};
    const recState = card.state || card.status || 'OPEN';
    const recId = card.recommendation_id || card.card_id || '';

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">NBA Recommendation</p>
          <p class="text-lg font-bold text-slate-900">${card.title || ''}</p>
        </div>
        <div class="text-right text-xs text-slate-500">
          <p class="font-semibold rounded px-2 py-1 ${recState === 'OPEN' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}">${recState}</p>
        </div>
      </div>
      <p class="text-sm text-slate-700 mb-4">${card.description || ''}</p>
      ${impact && Object.keys(impact).length > 0 ? `
        <div class="bg-blue-50 rounded p-3 mb-4">
          <p class="text-xs font-semibold text-blue-900 mb-2">Projected Impact</p>
          <div class="grid grid-cols-2 gap-2 text-xs text-blue-800">
            ${impact.cash_impact_usd ? `<div>💰 Cash: $${Number(impact.cash_impact_usd).toLocaleString()}</div>` : ''}
            ${impact.confidence_pct ? `<div>🎯 Confidence: ${impact.confidence_pct}%</div>` : ''}
          </div>
        </div>
      ` : ''}
      ${recState === 'OPEN' ? `
        <div class="flex gap-2">
          <button onclick="if(window.onRecommendationAccept) window.onRecommendationAccept('${recId}')"
            class="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700">Accept</button>
          <button onclick="if(window.onRecommendationDecline) window.onRecommendationDecline('${recId}')"
            class="text-xs px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700">Decline</button>
        </div>
      ` : ''}
    </div>`;
  }

  /**
   * Render a PolicyCard (policy decision with voting).
   */
  static renderPolicyCard(card, userTier = 0, onAction = null) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Pastoral content restricted to T3+ authorization level</p>
      </div>`;
    }

    // Normalise: API returns status (not state); voted_by nested under evidence
    const state      = card.state || card.status || 'OPEN';
    const votedBy    = card.voted_by || card.evidence?.voted_by || [];
    const proposed   = card.proposed_action || card.description || '';
    const policyId   = card.policy_id || card.card_id || '';
    const statusBadge = card.decision
      ? 'bg-green-50 text-green-700'
      : (state === 'OPEN' ? 'bg-red-50 text-red-700' : 'bg-slate-50 text-slate-700');

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-4">
        <div>
          <p class="text-sm font-semibold text-slate-700">Policy Decision</p>
          <p class="text-lg font-bold text-slate-900">${card.title || ''}</p>
        </div>
        <div class="text-right text-xs text-slate-500">
          <p class="font-semibold rounded px-2 py-1 ${statusBadge}">${card.decision || state}</p>
        </div>
      </div>
      ${proposed ? `<p class="text-sm text-slate-700 mb-4">${proposed}</p>` : ''}
      ${votedBy.length > 0 ? `
        <div class="mb-4">
          <p class="text-xs font-semibold text-slate-700 mb-2">Votes (${votedBy.length})</p>
          <div class="space-y-1 text-xs text-slate-600">
            ${votedBy.map(v => {
              const voteColor = v.vote === 'yes' ? 'text-green-700' : v.vote === 'no' ? 'text-red-700' : 'text-slate-600';
              return `<div class="${voteColor}">✓ ${v.actor_id || v.user_id || ''} (${v.tier || ''}): ${v.vote}</div>`;
            }).join('')}
          </div>
        </div>
      ` : ''}
      ${state === 'OPEN' ? `
        <div class="flex gap-2">
          <button onclick="if(window.onPolicyVote) window.onPolicyVote('${policyId}', 'yes')"
            class="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700">Vote Yes</button>
          <button onclick="if(window.onPolicyVote) window.onPolicyVote('${policyId}', 'no')"
            class="text-xs px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700">Vote No</button>
          <button onclick="if(window.onPolicyVote) window.onPolicyVote('${policyId}', 'abstain')"
            class="text-xs px-3 py-1 bg-slate-600 text-white rounded hover:bg-slate-700">Abstain</button>
        </div>
      ` : ''}
    </div>`;
  }

  /**
   * Render a ReconciliationCard (matched/unmatched transaction).
   */
  static renderReconciliationCard(card, userTier = 0) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Content restricted</p>
      </div>`;
    }

    const statusColor = {
      'matched': 'bg-green-100 text-green-900',
      'partial': 'bg-yellow-100 text-yellow-900',
      'unmatched': 'bg-red-100 text-red-900',
      'missing_event': 'bg-orange-100 text-orange-900'
    }[card.matching_status] || 'bg-slate-100';

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="flex items-start justify-between mb-3">
        <div>
          <p class="text-sm text-slate-600">${new Date(card.transaction_date).toLocaleDateString()}</p>
          <p class="text-lg font-bold text-slate-900">${card.description}</p>
        </div>
        <p class="text-xl font-bold text-slate-900">$${card.amount.toFixed(2)}</p>
      </div>
      <div class="flex items-center justify-between">
        <p class="text-xs text-slate-600">${card.account_id}</p>
        <p class="text-xs font-semibold rounded px-2 py-1 ${statusColor}">${card.matching_status}</p>
      </div>
      ${card.matched_je_id ? `
        <p class="text-xs text-slate-600 mt-2">✓ JE: ${card.matched_je_id}</p>
      ` : ''}
    </div>`;
  }

  /**
   * Render a QuestionCard (user query with answer history).
   */
  static renderQuestionCard(card, userTier = 0) {
    const visible = this.canView(card.privacy_class, userTier);
    if (!visible) {
      return `<div class="bg-slate-100 border border-slate-300 rounded-lg p-4 text-slate-600 text-sm">
        <p>🔒 Content restricted</p>
      </div>`;
    }

    return `<div class="bg-white border border-slate-200 rounded-lg p-4">
      <div class="mb-3">
        <p class="text-sm text-slate-600">Question</p>
        <p class="text-base font-semibold text-slate-900">${card.query}</p>
      </div>
      ${card.intent ? `
        <div class="text-xs bg-blue-50 rounded px-2 py-1 mb-3 inline-block text-blue-900">
          Intent: ${card.intent}
        </div>
      ` : ''}
      ${card.answer ? `
        <div class="bg-slate-50 rounded p-3 mb-3">
          <p class="text-xs text-slate-600 mb-1">Answer</p>
          <p class="text-sm text-slate-900">${card.answer}</p>
        </div>
      ` : ''}
      ${card.follow_on_suggestions && card.follow_on_suggestions.length > 0 ? `
        <div class="text-xs text-slate-600">
          <p class="font-semibold mb-1">Suggested Follow-Ups</p>
          <ul class="space-y-1">
            ${card.follow_on_suggestions.slice(0, 3).map(s => `<li>• ${s}</li>`).join('')}
          </ul>
        </div>
      ` : ''}
    </div>`;
  }

  /**
   * Dispatch to correct renderer based on card type.
   */
  static render(card, userTier = 0, callbacks = {}) {
    const cardType = card.card_type || card.constructor?.name || Object.keys(this.CARD_TYPES).find(
      k => card[`${k}_id`]
    );

    const renderer = {
      EventCard: () => this.renderEventCard(card, userTier, callbacks.onReveal),
      DecisionCard: () => this.renderDecisionCard(card, userTier, callbacks.onReveal),
      ExceptionCard: () => this.renderExceptionCard(card, userTier, callbacks.onAction),
      PolicyCard: () => this.renderPolicyCard(card, userTier, callbacks.onAction),
      RecommendationCard: () => this.renderRecommendationCard(card, userTier, callbacks.onAction),
      ReconciliationCard: () => this.renderReconciliationCard(card, userTier),
      QuestionCard: () => this.renderQuestionCard(card, userTier),
      ForecastCard: () => this.renderEventCard(card, userTier) // placeholder: same as EventCard for now
    }[cardType];

    if (!renderer) {
      return `<div class="bg-red-50 border border-red-300 rounded p-4 text-red-900 text-sm">
        Unknown card type: ${cardType}
      </div>`;
    }

    return renderer();
  }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CardRenderer;
}
