"""Data models for EIME per FRS §6."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ===== Enums =====

class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    PAYMENT_REMITTANCE = "PAYMENT_REMITTANCE"
    UTILITY_BILL = "UTILITY_BILL"
    CREDIT_MEMO = "CREDIT_MEMO"
    DONATION_RECEIPT = "DONATION_RECEIPT"


class FundCategory(str, Enum):
    GENERAL_OPERATING = "GENERAL_OPERATING"
    TEMP_RESTRICTED_PURPOSE = "TEMP_RESTRICTED_PURPOSE"
    TEMP_RESTRICTED_TIME = "TEMP_RESTRICTED_TIME"
    PERMANENTLY_RESTRICTED = "PERMANENTLY_RESTRICTED"
    BOARD_DESIGNATED = "BOARD_DESIGNATED"
    CAPITAL_CAMPAIGN = "CAPITAL_CAMPAIGN"


class RestrictionClass(str, Enum):
    WITHOUT_RESTRICTION = "WITHOUT_RESTRICTION"
    WITH_RESTRICTION_PURPOSE = "WITH_RESTRICTION_PURPOSE"
    WITH_RESTRICTION_PERMANENT = "WITH_RESTRICTION_PERMANENT"


class DenominationType(str, Enum):
    EPISCOPAL = "EPISCOPAL"
    UMC = "UMC"
    PRESBYTERIAN_PCUSA = "PRESBYTERIAN_PCUSA"
    BAPTIST_INDEPENDENT = "BAPTIST_INDEPENDENT"
    CATHOLIC_PARISH = "CATHOLIC_PARISH"
    NONDENOMINATIONAL = "NONDENOMINATIONAL"
    AOG = "AOG"
    OTHER = "OTHER"


class ExpenseCategory(str, Enum):
    # Personnel (5000)
    CLERGY_COMPENSATION = "CLERGY_COMPENSATION"
    CLERGY_HOUSING = "CLERGY_HOUSING"
    LAY_STAFF_WAGES = "LAY_STAFF_WAGES"
    BENEFITS = "BENEFITS"
    SECA_REIMBURSEMENT = "SECA_REIMBURSEMENT"
    # Ministry (6000)
    WORSHIP = "WORSHIP"
    CHILDREN_MINISTRY = "CHILDREN_MINISTRY"
    YOUTH_MINISTRY = "YOUTH_MINISTRY"
    ADULT_EDUCATION = "ADULT_EDUCATION"
    MISSIONS = "MISSIONS"
    PASTORAL_CARE = "PASTORAL_CARE"
    # Facility (7000)
    MORTGAGE_RENT = "MORTGAGE_RENT"
    UTILITIES = "UTILITIES"
    MAINTENANCE_REPAIRS = "MAINTENANCE_REPAIRS"
    INSURANCE = "INSURANCE"
    TECHNOLOGY = "TECHNOLOGY"
    JANITORIAL = "JANITORIAL"
    LANDSCAPING = "LANDSCAPING"
    # Admin (8000)
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES"
    LEGAL_AUDIT = "LEGAL_AUDIT"
    DENOMINATIONAL_ASSESSMENT = "DENOMINATIONAL_ASSESSMENT"
    STEWARDSHIP_FUNDRAISING = "STEWARDSHIP_FUNDRAISING"
    BANK_FEES = "BANK_FEES"
    PROFESSIONAL_DEVELOPMENT = "PROFESSIONAL_DEVELOPMENT"
    # Capital (9000)
    CAPITAL_EXPENDITURE = "CAPITAL_EXPENDITURE"
    EQUIPMENT = "EQUIPMENT"
    IMPROVEMENT = "IMPROVEMENT"
    LOAN_PRINCIPAL = "LOAN_PRINCIPAL"
    DEPRECIATION = "DEPRECIATION"
    # Special
    BENEVOLENCE = "BENEVOLENCE"
    HOSPITALITY = "HOSPITALITY"
    PRINTING = "PRINTING"
    UNKNOWN = "UNKNOWN"


class MinistryArea(str, Enum):
    WORSHIP = "WORSHIP"
    CHILDREN = "CHILDREN"
    YOUTH = "YOUTH"
    ADULT_EDUCATION = "ADULT_EDUCATION"
    MISSIONS = "MISSIONS"
    PASTORAL_CARE = "PASTORAL_CARE"
    ADMINISTRATION = "ADMINISTRATION"
    FACILITIES = "FACILITIES"


class Verdict(str, Enum):
    APPROVED = "APPROVED"
    REVISE = "REVISE"
    ESCALATE = "ESCALATE"


class OverallVerdict(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    ESCALATE = "ESCALATE"


class ProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    EXTRACTING = "EXTRACTING"
    CLASSIFYING = "CLASSIFYING"
    MAPPING = "MAPPING"
    REVIEWING = "REVIEWING"
    PENDING_HITL = "PENDING_HITL"
    BUILDING_ENTRY = "BUILDING_ENTRY"
    EMITTED = "EMITTED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class JEStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"


# ===== Invoice extraction =====

class LineItem(BaseModel):
    line_id: str
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Optional[Decimal] = None
    amount: Decimal
    gl_hint: Optional[str] = None


class InvoiceDocument(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    vendor_name: str
    vendor_address: Optional[str] = None
    invoice_number: str
    invoice_date: date
    due_date: Optional[date] = None
    document_type: DocumentType
    currency: str = "USD"
    subtotal: Decimal
    tax_amount: Decimal = Decimal("0")
    total_amount: Decimal
    payment_terms: Optional[str] = None
    memo: Optional[str] = None
    line_items: List[LineItem]
    warnings: List[str] = Field(default_factory=list)
    requires_manual_review: bool = False
    raw_text: Optional[str] = None


# ===== Accounting context =====

class Account(BaseModel):
    account_number: str
    account_name: str
    account_type: str
    fund_id: str
    restriction_class: RestrictionClass
    active: bool = True


class Fund(BaseModel):
    fund_id: str
    fund_name: str
    restriction_class: RestrictionClass
    fund_category: FundCategory
    purpose_description: Optional[str] = None
    expenditure_rules: Optional[str] = None
    current_balance: Decimal = Decimal("0")


class AllocationSchedule(BaseModel):
    schedule_id: str
    name: str
    basis: str  # "square_footage" | "headcount" | "manual"
    allocations: List[Dict[str, Any]]  # [{fund_id, pct}]
    applies_to_categories: List[str] = Field(default_factory=list)


class ApportionmentAccount(BaseModel):
    account_number: str
    pct_of_revenue: Decimal


class BudgetMonth(BaseModel):
    """Monthly budget allocation for a single account.
    All 12 months always present; missing months in upload fill with 0.
    """
    jan: Decimal = Decimal("0")
    feb: Decimal = Decimal("0")
    mar: Decimal = Decimal("0")
    apr: Decimal = Decimal("0")
    may: Decimal = Decimal("0")
    jun: Decimal = Decimal("0")
    jul: Decimal = Decimal("0")
    aug: Decimal = Decimal("0")
    sep: Decimal = Decimal("0")
    oct: Decimal = Decimal("0")
    nov: Decimal = Decimal("0")
    dec: Decimal = Decimal("0")
    annual_total: Decimal = Decimal("0")  # canonical figure for compare


class BudgetPlan(BaseModel):
    fiscal_year: int
    plan_date: date                              # date plan was approved
    amendment_number: int = 0                    # 0 = original, 1+ = amendments
    accounts: Dict[str, BudgetMonth] = Field(default_factory=dict)
                                                 # key = account_number
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    source_filename: Optional[str] = None


class BudgetStatus(str, Enum):
    NO_BUDGET = "NO_BUDGET"
    WITHIN_BUDGET = "WITHIN_BUDGET"
    WARNING = "WARNING"
    OVER_BUDGET = "OVER_BUDGET"


class BudgetCheck(BaseModel):
    line_id: str
    account_number: str
    account_name: str
    fund_id: str
    annual_budget: Decimal
    ytd_actual: Decimal
    this_invoice: Decimal
    after: Decimal
    remaining: Decimal
    consumed_pct: float
    status: BudgetStatus
    reason: str


class AccountingContext(BaseModel):
    church_id: str
    church_name: str
    denomination_type: DenominationType
    fiscal_year: int
    fiscal_year_start: date
    accounts: List[Account]
    funds: List[Fund]
    allocation_schedules: List[AllocationSchedule] = Field(default_factory=list)
    capitalisation_threshold_usd: Decimal = Decimal("2500")
    parsonage_allowance_current_year: Decimal = Decimal("0")
    parsonage_allowance_used_ytd: Decimal = Decimal("0")
    apportionment_accounts: List[ApportionmentAccount] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    budget: Optional[BudgetPlan] = None
    ytd_actuals: Dict[str, Decimal] = Field(default_factory=dict)
    budget_warning_threshold: float = 0.80


# ===== Classification =====

class ClassificationFlags(BaseModel):
    is_housing_related: bool = False
    is_missions_passthrough: bool = False
    capitalise: bool = False
    is_apportionment: bool = False
    is_split_required: bool = False
    requires_hitl: bool = False


class ClassifiedLineItem(BaseModel):
    line_id: str
    description: str
    amount: Decimal
    expense_category: str
    ministry_area: Optional[str] = None
    fund_eligibility: List[str]  # fund_ids
    flags: ClassificationFlags
    classification_rationale: str
    confidence: float = 1.0


# ===== GL mapping =====

class Posting(BaseModel):
    account_number: str
    account_name: str
    fund_id: str
    fund_name: str
    debit_amount: Decimal = Decimal("0")
    credit_amount: Decimal = Decimal("0")
    restriction_class: RestrictionClass
    confidence: float = 1.0
    mapping_rationale: str = ""


class DraftLineAllocation(BaseModel):
    line_id: str
    description: str
    postings: List[Posting]
    total_debits: Decimal
    total_credits: Decimal
    balanced: bool


class DraftAllocations(BaseModel):
    invoice_number: str
    lines: List[DraftLineAllocation]
    document_total_debits: Decimal
    document_total_credits: Decimal
    document_balanced: bool


# ===== Reviewer =====

class ReviewedLine(BaseModel):
    line_id: str
    verdict: Verdict
    reasons: List[str] = Field(default_factory=list)
    revised_postings: Optional[List[Posting]] = None


class ReviewedAllocations(BaseModel):
    lines: List[ReviewedLine]
    overall_verdict: OverallVerdict
    escalation_items: List[str] = Field(default_factory=list)
    revision_items: List[str] = Field(default_factory=list)
    review_notes: str = ""


# ===== HITL =====

class HITLLineDecision(BaseModel):
    line_id: str
    action: str  # APPROVED | OVERRIDE | REJECT
    override_postings: Optional[List[Posting]] = None
    reviewer_id: str
    approval_timestamp: datetime
    notes: str = ""
    missions_attestation: bool = False


class HITLDecision(HITLLineDecision):
    pass


class HITLDecisions(BaseModel):
    line_decisions: List[HITLLineDecision]
    all_resolved: bool


# ===== Journal entry =====

class JournalEntryLine(BaseModel):
    sequence: int
    account_number: str
    account_name: str
    fund_id: str
    fund_name: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""
    approved_by: Optional[str] = None


class JournalEntry(BaseModel):
    entry_id: str
    church_id: str
    fiscal_year: int
    accounting_period: str  # YYYY-MM
    entry_date: date
    reference: str  # invoice_number
    vendor_name: str
    description: str
    status: JEStatus
    lines: List[JournalEntryLine]
    total_debits: Decimal
    total_credits: Decimal
    balanced: bool
    audit_trail_url: str = ""


# ===== Risk & Fraud =====

class RiskLineDetail(BaseModel):
    line_id: str
    risk_level: str
    risk_score: float
    flags: List[str] = Field(default_factory=list)
    recommendation: str = ""


class RiskAssessment(BaseModel):
    risk_level: str
    risk_score: float
    per_line_risks: List[RiskLineDetail] = Field(default_factory=list)
    aggregate_flags: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class FraudSignal(BaseModel):
    signal_id: str
    category: str
    description: str
    weight: float
    evidence: str


class FraudAssessment(BaseModel):
    fraud_level: str
    fraud_score: float
    signals: List[FraudSignal] = Field(default_factory=list)
    recommended_action: str = "APPROVE"


# ===== Chat =====

class ChatRequest(BaseModel):
    question: str
    job_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    skills_consulted: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# ===== Membrane / Event mesh =====

class AccountingDomainEvent(BaseModel):
    event_type: str = "JOURNAL_ENTRY_READY"
    payload: Dict[str, Any]
    metadata: Dict[str, Any]


# ===== Orchestration =====

class ExecutionPlanStep(BaseModel):
    archetype: str
    skill_name: str
    inputs: List[str]
    depends_on: List[str] = Field(default_factory=list)


# ===== Job tracking (web-app specific) =====

class ProcessingJob(BaseModel):
    job_id: str
    church_id: str
    filename: str
    pdf_path: str
    document_type: DocumentType
    status: ProcessingStatus
    created_at: datetime
    updated_at: datetime
    invoice_document: Optional[InvoiceDocument] = None
    accounting_context: Optional[AccountingContext] = None
    classified_items: Optional[List[ClassifiedLineItem]] = None
    draft_allocations: Optional[DraftAllocations] = None
    reviewed_allocations: Optional[ReviewedAllocations] = None
    hitl_decisions: Optional[HITLDecisions] = None
    journal_entry: Optional[JournalEntry] = None
    risk_assessment: Optional[Dict[str, Any]] = None
    fraud_assessment: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)
    budget_check: Optional[List[BudgetCheck]] = None
