"""Phase 3: SkillRegistry loading + frontmatter shape tests."""
from __future__ import annotations

import frontmatter
from pathlib import Path

from backend.tools.skill_registry import SkillRegistry

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"

# 19 canonical Phase 3 skill names (excludes MVP-agent wrappers, which are
# additional and not part of the original 19 SKILL.md count).
EXPECTED_19 = {
    "invoice_processing_workflow",
    "pdf_extraction",
    "line_item_classifier",
    "gl_account_mapper",
    "journal_entry_builder",
    "expense_taxonomy_v1",
    "denomination_episcopal",
    "denomination_umc",
    "denomination_baptist",
    "denomination_presbyterian",
    "denomination_catholic_parish",
    "coa_reference_loader",
    "vendor_history_lookup",
    "allocation_reviewer",
    "risk_assessor",
    "fraud_detector",
    "hitl_invoice_gate",
    "agent_qa_interface",
    "accounting_domain_distillation",
}


def test_all_19_skills_load() -> None:
    reg = SkillRegistry()
    names = {s["name"] for s in reg.search()}
    missing = EXPECTED_19 - names
    assert not missing, f"missing skills: {missing}"


def test_skill_md_frontmatter_required_fields() -> None:
    """Every SKILL.md must declare skill_name, archetype, inputs, expected_output,
    privacy_class, perturbations_emitted."""
    required = {"skill_name", "archetype", "inputs", "expected_output", "privacy_class", "perturbations_emitted"}
    errors = []
    for skill_md in SKILLS_ROOT.rglob("SKILL.md"):
        post = frontmatter.load(skill_md)
        missing = required - set(post.metadata.keys())
        if missing:
            errors.append(f"{skill_md}: missing {missing}")
    assert not errors, "\n".join(errors)


def test_privacy_class_valid() -> None:
    for skill_md in SKILLS_ROOT.rglob("SKILL.md"):
        post = frontmatter.load(skill_md)
        pc = post.metadata.get("privacy_class")
        assert pc in ("P0", "P1"), f"{skill_md}: bad privacy_class {pc!r}"


def test_archetype_membership() -> None:
    valid = {"orchestrator", "worker", "researcher", "reviewer", "conversationalist", "membrane"}
    reg = SkillRegistry()
    for skill in reg.search():
        assert skill["archetype"] in valid, f"{skill['name']}: bad archetype {skill['archetype']!r}"


def test_registry_lazy_body_load() -> None:
    reg = SkillRegistry()
    body = reg.load_body("pdf_extraction")
    assert "Workflow Steps" in body or "pdf_extraction" in body
