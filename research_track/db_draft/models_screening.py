"""Staging-only SQLAlchemy 2.0 draft. Do not import into production metadata yet."""
import enum
import uuid
from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now


class ScreeningAction(str, enum.Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    ALERT = "ALERT"


class ReasonCode(str, enum.Enum):
    """Standardized audit reason codes emitted by deterministic screening policy."""
    ALLOW_PERMITTED_FOOD = "ALLOW_PERMITTED_FOOD"
    ALLOW_PERMITTED_GOODS = "ALLOW_PERMITTED_GOODS"
    CATEGORY_RULE_ALLOW = "CATEGORY_RULE_ALLOW"

    REVIEW_UNCERTAIN_CLASSIFICATION = "REVIEW_UNCERTAIN_CLASSIFICATION"
    REVIEW_CONTROLLED_ITEM = "REVIEW_CONTROLLED_ITEM"
    REVIEW_HAZARDOUS_QUANTITY = "REVIEW_HAZARDOUS_QUANTITY"
    CATEGORY_RULE_REVIEW = "CATEGORY_RULE_REVIEW"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    UNKNOWN_CATEGORY = "UNKNOWN_CATEGORY"
    LOW_CLASSIFIER_CONFIDENCE = "LOW_CLASSIFIER_CONFIDENCE"
    MISSING_CLASSIFIER_CONFIDENCE = "MISSING_CLASSIFIER_CONFIDENCE"
    INVALID_CLASSIFICATION = "INVALID_CLASSIFICATION"
    MISSING_QUANTITY = "MISSING_QUANTITY"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    UNSUPPORTED_QUANTITY_UNIT = "UNSUPPORTED_QUANTITY_UNIT"
    POLICY_RULE_CONFLICT = "POLICY_RULE_CONFLICT"
    POLICY_VERSION_INVALID = "POLICY_VERSION_INVALID"
    HAZARDOUS_THRESHOLD_MET = "HAZARDOUS_THRESHOLD_MET"

    ALERT_PROHIBITED_CHEMICAL = "ALERT_PROHIBITED_CHEMICAL"
    ALERT_PROHIBITED_TOBACCO = "ALERT_PROHIBITED_TOBACCO"
    ALERT_PROHIBITED_ALCOHOL = "ALERT_PROHIBITED_ALCOHOL"
    ALERT_PROHIBITED_DRUG = "ALERT_PROHIBITED_DRUG"
    ALERT_PROHIBITED_WEAPON = "ALERT_PROHIBITED_WEAPON"
    CATEGORY_RULE_ALERT = "CATEGORY_RULE_ALERT"

    NO_MATCHING_POLICY_RULE = "NO_MATCHING_POLICY_RULE"
    POLICY_RULE_INACTIVE = "POLICY_RULE_INACTIVE"
    POLICY_RULE_EXPIRED = "POLICY_RULE_EXPIRED"
    MISSING_REQUIRED_PLATFORM = "MISSING_REQUIRED_PLATFORM"
    MULTIPLE_RULES_MATCHED = "MULTIPLE_RULES_MATCHED"
    HAZARDOUS_THRESHOLD_NOT_MET = "HAZARDOUS_THRESHOLD_NOT_MET"


class ItemCategory(Base, TimestampMixin):
    __tablename__ = "item_categories"

    code = Column(String(50), primary_key=True)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    default_action = Column(SQLEnum(ScreeningAction, name="screening_action_enum"), nullable=False)
    severity = Column(String(20), nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)

    rules = relationship("ScreeningPolicyRule", back_populates="category")
    classifications = relationship("InvoiceLineClassification", back_populates="category")


class ScreeningPolicyRule(Base, TimestampMixin):
    __tablename__ = "screening_policy_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category_code = Column(String(50), ForeignKey("item_categories.code"), nullable=False, index=True)
    action = Column(SQLEnum(ScreeningAction, name="screening_action_enum"), nullable=False)
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    platform = Column(String(30), nullable=True, index=True)
    priority = Column(Integer, nullable=False, default=100)
    policy_version = Column(String(40), nullable=False, default="1.0", server_default="1.0", index=True)
    effective_from = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)  # soft-deactivate only

    category = relationship("ItemCategory", back_populates="rules")


class InvoiceLineClassification(Base):
    __tablename__ = "invoice_line_classifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_item_id = Column(UUID(as_uuid=True), ForeignKey("invoice_items.id"), nullable=False, index=True)
    category_code = Column(String(50), ForeignKey("item_categories.code"), nullable=False, index=True)
    confidence = Column(Float, nullable=True)  # Nullable for manual entries or low-res images without score
    classifier_name = Column(String(120), nullable=False)
    classifier_version = Column(String(120), nullable=False)
    normalized_item_text = Column(String(300), nullable=False)
    raw_item_text = Column(Text, nullable=True)  # Retained only when screening outcome != ALLOW
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    category = relationship("ItemCategory", back_populates="classifications")
    invoice_item = relationship("InvoiceItem")


class InvoiceScreeningResult(Base):
    __tablename__ = "invoice_screening_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True)
    outcome = Column(SQLEnum(ScreeningAction, name="screening_action_enum"), nullable=False, index=True)
    matched_rule_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False)
    reason_codes = Column(ARRAY(String(80)), nullable=False)  # Validated against ReasonCode enum values
    policy_version = Column(String(40), nullable=False, default="1.0", server_default="1.0")
    raw_payload = Column(JSONB, nullable=False)  # Immutable raw screening JSON payload for audit verification
    security_alert_id = Column(UUID(as_uuid=True), ForeignKey("security_alerts.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    invoice = relationship("Invoice")
    security_alert = relationship("SecurityAlert")


class MLEvalRun(Base):
    __tablename__ = "ml_eval_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track = Column(String(20), nullable=False, index=True)
    model_name = Column(String(160), nullable=False)
    model_version = Column(String(160), nullable=False)
    dataset_name = Column(String(160), nullable=False)
    metrics = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
