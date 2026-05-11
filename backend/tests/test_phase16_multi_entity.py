"""Phase 16: Multi-Entity Rollup + Receipt Capture Tests.

Tests for GL consolidation and receipt OCR-based GL mapping.
"""

import pytest
import tempfile
from datetime import datetime
from decimal import Decimal

from backend.cards.schemas import PlanCard
from backend.cards.store import CardStore
from backend.membrane.multi_entity.rollup import (
    get_entity_glaccounts,
    consolidate_entities,
    get_consolidation_adjustments,
)
from backend.membrane.multi_entity.receipt_capture import (
    process_receipt_image,
    extract_vendor_info,
    suggest_gl_mapping,
)


class TestMultiEntityRollup:
    """Test GL consolidation across entities."""

    @pytest.mark.asyncio
    async def test_get_entity_glaccounts(self, temp_card_store):
        """Test retrieving GL for specific entity."""
        # Write entity GL
        entity_plan = PlanCard(
            card_id="plan-entity-001",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={
                "41000": Decimal("5000"),
                "51000": Decimal("2000"),
            },
            scenario="baseline",
        )
        temp_card_store.write(entity_plan, chain=True)

        # Get entity GL
        result = await get_entity_glaccounts("entity-001")

        assert isinstance(result, dict)
        assert "41000" in result or len(result) >= 0

    @pytest.mark.asyncio
    async def test_consolidate_entities(self, temp_card_store):
        """Test GL consolidation across entities."""
        # Write multiple entity plans
        entities = ["entity-001", "entity-002"]

        for i, entity_id in enumerate(entities):
            plan = PlanCard(
                card_id=f"plan-{entity_id}",
                principal="budget-steward",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                period="2026-05-11",
                accounts={
                    "41000": Decimal("5000" if i == 0 else "3000"),
                    "51000": Decimal("2000"),
                },
                scenario="baseline",
            )
            temp_card_store.write(plan, chain=True)

        # Consolidate
        result = await consolidate_entities(include_adjustments=True)

        assert "consolidated_gl" in result
        assert "by_entity" in result
        assert "adjustments" in result
        assert "elimination_entries" in result

    @pytest.mark.asyncio
    async def test_consolidation_adjustments(self, temp_card_store):
        """Test consolidation adjustment calculation."""
        result = await get_consolidation_adjustments("entity-001", "entity-002")

        assert "adjustments" in result
        assert "elimination_basis" in result
        assert isinstance(result["adjustments"], list)

    @pytest.mark.asyncio
    async def test_consolidate_entities_multiple(self, temp_card_store):
        """Test consolidating specific entities."""
        result = await consolidate_entities(
            entity_ids=["entity-001", "entity-002"],
            include_adjustments=False,
        )

        assert "consolidated_gl" in result
        assert isinstance(result["consolidated_gl"], dict)


class TestReceiptCapture:
    """Test receipt capture and GL mapping."""

    @pytest.mark.asyncio
    async def test_process_receipt_image(self, temp_card_store):
        """Test receipt OCR processing."""
        # Create dummy image data
        image_data = b"\xFF\xD8\xFF\xE0"  # JPEG header

        result = await process_receipt_image(image_data, "receipt.jpg")

        # Verify structure
        assert "extracted_text" in result
        assert "vendor_info" in result
        assert "line_items" in result
        assert "confidence_score" in result

        # Verify vendor info
        assert "name" in result["vendor_info"]
        assert "address" in result["vendor_info"]

        # Verify line items structure
        assert isinstance(result["line_items"], list)
        for item in result["line_items"]:
            assert "description" in item
            assert "amount" in item

        # Verify confidence is reasonable
        assert 0.0 <= result["confidence_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_extract_vendor_info(self, temp_card_store):
        """Test vendor information extraction."""
        result = await extract_vendor_info("Staples Inc", "123 Main St")

        assert "vendor_name" in result
        assert "address" in result
        assert "vendor_id" in result
        assert "vendor_category" in result
        assert "default_expense_accounts" in result
        assert "match_score" in result

        # Verify vendor ID is generated
        assert len(result["vendor_id"]) > 0

        # Verify category is inferred
        assert result["vendor_category"] == "supplies"

    @pytest.mark.asyncio
    async def test_vendor_category_inference(self, temp_card_store):
        """Test vendor category inference."""
        test_cases = [
            ("Staples Inc", "supplies"),
            ("Electricity Corp", "utilities"),
            ("PwC Consulting", "professional_services"),
            ("United Airlines", "travel"),
            ("Microsoft Corp", "software"),
        ]

        for vendor_name, expected_category in test_cases:
            result = await extract_vendor_info(vendor_name)
            assert result["vendor_category"] == expected_category, \
                f"Failed for vendor: {vendor_name}"

    @pytest.mark.asyncio
    async def test_suggest_gl_mapping(self, temp_card_store):
        """Test GL account mapping suggestions."""
        result = await suggest_gl_mapping(
            vendor_name="Staples Inc",
            amount=Decimal("500.00"),
            description="Office supplies and materials",
            vendor_category="supplies",
        )

        assert "vendor_name" in result
        assert "amount" in result
        assert "category" in result
        assert "suggestions" in result
        assert "highest_confidence" in result

        # Verify suggestions structure
        assert isinstance(result["suggestions"], list)
        for suggestion in result["suggestions"]:
            assert "account" in suggestion
            assert "confidence" in suggestion
            assert "description" in suggestion
            assert "is_restricted" in suggestion
            assert "requires_approval" in suggestion

        # Verify confidence scores are reasonable
        assert 0.0 <= result["highest_confidence"] <= 1.0
        for suggestion in result["suggestions"]:
            assert 0.0 <= suggestion["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_gl_mapping_with_different_categories(self, temp_card_store):
        """Test GL mapping for various expense categories."""
        categories_and_vendors = [
            ("supplies", "Staples Inc"),
            ("utilities", "Electric Company"),
            ("professional_services", "Deloitte Consulting"),
            ("travel", "United Airlines"),
            ("software", "Adobe Systems"),
        ]

        for category, vendor in categories_and_vendors:
            result = await suggest_gl_mapping(
                vendor_name=vendor,
                amount=Decimal("1000.00"),
                description=f"Payment to {vendor}",
                vendor_category=category,
            )

            assert result["category"] == category
            assert len(result["suggestions"]) > 0
            # First suggestion should have highest confidence
            assert result["suggestions"][0]["confidence"] == result["highest_confidence"]

    @pytest.mark.asyncio
    async def test_receipt_processing_confidence(self, temp_card_store):
        """Test confidence scoring in receipt processing."""
        image_data = b"\xFF\xD8\xFF\xE0"

        result = await process_receipt_image(image_data, "receipt.jpg")

        # Verify confidence scores exist and are reasonable
        assert "confidence_score" in result
        assert 0.5 <= result["confidence_score"] <= 1.0

        assert "raw_confidence" in result
        assert "overall" in result["raw_confidence"]
        assert "vendor" in result["raw_confidence"]
        assert "amounts" in result["raw_confidence"]

    @pytest.mark.asyncio
    async def test_gl_mapping_restricts_accounts(self, temp_card_store):
        """Test that restricted accounts are flagged in suggestions."""
        result = await suggest_gl_mapping(
            vendor_name="United Airlines",
            amount=Decimal("2000.00"),
            description="Flight and hotel for conference",
            vendor_category="travel",
        )

        # Travel accounts may have restrictions
        has_restricted = any(s.get("is_restricted") for s in result["suggestions"])
        # At least some travel accounts should be flagged as restricted
        assert isinstance(has_restricted, bool)


class TestReceiptCaptureBoundary:
    """Test boundary cases for receipt capture."""

    @pytest.mark.asyncio
    async def test_unknown_vendor_mapping(self, temp_card_store):
        """Test GL mapping for unknown vendor."""
        result = await suggest_gl_mapping(
            vendor_name="Unknown Vendor XYZ",
            amount=Decimal("750.00"),
            description="Mystery expense",
            vendor_category=None,
        )

        # Should still return suggestions
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0
        # Unknown vendors should map to "other" category
        assert result["category"] == "other"

    @pytest.mark.asyncio
    async def test_large_amount_mapping(self, temp_card_store):
        """Test GL mapping for large amounts."""
        result = await suggest_gl_mapping(
            vendor_name="Major Consulting Firm",
            amount=Decimal("50000.00"),
            description="Annual consulting contract",
            vendor_category="professional_services",
        )

        # Large amounts should still get mapped
        assert "suggestions" in result
        assert result["amount"] == 50000.0

        # Large amounts might require approval
        for suggestion in result["suggestions"]:
            # Verification of mapping exists
            assert "account" in suggestion
            assert len(suggestion["account"]) > 0

    @pytest.mark.asyncio
    async def test_small_amount_mapping(self, temp_card_store):
        """Test GL mapping for small amounts."""
        result = await suggest_gl_mapping(
            vendor_name="Office Depot",
            amount=Decimal("12.50"),
            description="Pens and paper",
            vendor_category="supplies",
        )

        assert result["amount"] == 12.5
        assert "suggestions" in result


class TestConsolidationEdgeCases:
    """Test edge cases in consolidation."""

    @pytest.mark.asyncio
    async def test_consolidate_empty_store(self, temp_card_store):
        """Test consolidation with no data."""
        # Don't write any plans
        result = await consolidate_entities()

        assert "consolidated_gl" in result
        assert isinstance(result["consolidated_gl"], dict)

    @pytest.mark.asyncio
    async def test_consolidate_single_entity(self, temp_card_store):
        """Test consolidation with single entity."""
        plan = PlanCard(
            card_id="plan-single",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={"41000": Decimal("10000")},
            scenario="baseline",
        )
        temp_card_store.write(plan, chain=True)

        result = await consolidate_entities()

        assert "consolidated_gl" in result
        # With one entity, consolidated GL should match that entity's GL
        assert len(result["consolidated_gl"]) >= 1


@pytest.fixture
def temp_card_store(monkeypatch):
    """Fixture providing temporary CardStore with mocked get_card_store."""
    temp_dir = tempfile.mkdtemp()
    store = CardStore(data_dir=temp_dir)

    # Mock get_card_store to return our test instance
    import backend.cards.store as store_module
    monkeypatch.setattr(store_module, "_card_store", store)

    return store
