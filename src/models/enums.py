"""Enumerations for the HousingHand data model."""

import enum


class PipelineStage(str, enum.Enum):
    CONCEPT = "concept"
    PRE_DEVELOPMENT = "pre_development"
    ENTITLEMENT = "entitlement"
    FINANCING = "financing"
    CONSTRUCTION = "construction"
    LEASE_UP = "lease_up"
    OPERATIONS = "operations"
    STALLED = "stalled"
    ABANDONED = "abandoned"


class BuildingType(str, enum.Enum):
    NEW_CONSTRUCTION = "new_construction"
    ADAPTIVE_REUSE = "adaptive_reuse"
    SUBSTANTIAL_REHAB = "substantial_rehab"
    ACQUISITION_REHAB = "acquisition_rehab"


class StructureType(str, enum.Enum):
    WOOD_FRAME = "wood_frame"
    CONCRETE = "concrete"
    STEEL = "steel"
    MIXED = "mixed"


class ParkingType(str, enum.Enum):
    SURFACE = "surface"
    STRUCTURED = "structured"
    UNDERGROUND = "underground"
    NONE = "none"


class OverallHealth(str, enum.Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    DELAYED = "delayed"
    STALLED = "stalled"


class DataSource(str, enum.Enum):
    DEVELOPER_PORTAL = "developer_portal"
    PUBLIC_RECORDS = "public_records"
    FUNDER_REPORT = "funder_report"
    HOUSING_MIND_INFERENCE = "housing_mind_inference"
    MANUAL_ENTRY = "manual_entry"


class FundingSourceType(str, enum.Enum):
    LIHTC_4PCT = "LIHTC_4pct"
    LIHTC_9PCT = "LIHTC_9pct"
    HOME = "HOME"
    CDBG = "CDBG"
    HTF = "HTF"
    STATE_TAX_CREDIT = "state_tax_credit"
    LOCAL_TRUST_FUND = "local_trust_fund"
    CONSTRUCTION_LOAN = "construction_loan"
    PERMANENT_LOAN = "permanent_loan"
    EQUITY = "equity"
    GRANT = "grant"
    OTHER = "other"


class FundingSourceStatus(str, enum.Enum):
    ANTICIPATED = "anticipated"
    APPLIED = "applied"
    AWARDED = "awarded"
    COMMITTED = "committed"
    CLOSED = "closed"
    REJECTED = "rejected"


class NeighborOpposition(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"


class AMIMixCategory(str, enum.Enum):
    DEEP_AFFORDABILITY = "deep_affordability"
    MIXED_INCOME = "mixed_income"
    WORKFORCE = "workforce"
    SENIOR = "senior"


class PortfolioType(str, enum.Enum):
    PHA_SERVICE_AREA = "pha_service_area"
    FUNDER_PORTFOLIO = "funder_portfolio"
    CITY_JURISDICTION = "city_jurisdiction"
    STATE_REGION = "state_region"
    CUSTOM = "custom"


class ReformType(str, enum.Enum):
    ZONING_CHANGE = "zoning_change"
    PARKING_REFORM = "parking_reform"
    DENSITY_BONUS = "density_bonus"
    STREAMLINING = "streamlining"
    FEE_REDUCTION = "fee_reduction"
    OTHER = "other"


class StakeholderType(str, enum.Enum):
    PHA = "pha"
    FUNDER = "funder"
    CITY = "city"
    STATE = "state"
    RESEARCHER = "researcher"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class BarrierStage(str, enum.Enum):
    PRE_DEVELOPMENT = "pre_development"
    ENTITLEMENT = "entitlement"
    FINANCING = "financing"
    CONSTRUCTION = "construction"
