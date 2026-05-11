---
skill_name: drafting_agent
archetype: orchestrator
description: Wraps the MVP CrewAI drafting_agent. Transforms natural-language journal-entry descriptions into balanced JE drafts with CoA mapping.
inputs:
  - description
  - church_id
expected_output: Journal entry draft (proposal; requires human approval).
allowed_tools:
  - extract_je_slots
  - resolve_account
  - build_je_draft
  - semantic_search_coa
privacy_class: P0
perturbations_emitted:
  - MAPPING_CONFIDENCE_LOW
---

# drafting_agent (MVP wrapper)

Skill-library entry point for the existing `backend.agents.agents.drafting_agent`
CrewAI Agent. Invoked through the SkillRouter so cabinet members and the
Flow can call the drafting agent uniformly with other skills.
