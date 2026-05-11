---
skill_name: auto_post_agent
archetype: orchestrator
description: Wraps the MVP auto_post_agent — evaluates recurring JE tolerance and posts to ACS when within bounds.
inputs:
  - je_draft
  - recurring_id
expected_output: Auto-post decision + ACS posting result (if posted).
allowed_tools:
  - get_recurring_tolerance
  - should_auto_post
  - post_je_to_acs
  - record_feedback
privacy_class: P0
perturbations_emitted:
  - JOURNAL_ENTRY_READY
---

# auto_post_agent (MVP wrapper)
