"""Feature engineering for the HousingHand timeline prediction model.

Extracts numeric and categorical features from Project objects,
producing a flat feature vector suitable for scikit-learn estimators.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from src.models.enums import BuildingType, NeighborOpposition, PipelineStage, StructureType
from src.models.project import Project

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_STAGES: list[str] = [
    "entitlement_days",
    "financing_days",
    "construction_days",
]

# Ordered mapping for opposition level -> numeric severity score (0-4)
_OPPOSITION_SCORES: dict[str | None, int] = {
    None: 0,
    NeighborOpposition.NONE: 0,
    NeighborOpposition.LOW: 1,
    NeighborOpposition.MODERATE: 2,
    NeighborOpposition.HIGH: 3,
    NeighborOpposition.SEVERE: 4,
}

# Building-type one-hot categories (sorted for deterministic ordering)
_BUILDING_TYPES: list[str] = sorted(bt.value for bt in BuildingType)

# Structure-type one-hot categories
_STRUCTURE_TYPES: list[str] = sorted(st.value for st in StructureType)

# Pipeline stage ordinal encoding (concept=0 ... operations=6)
_STAGE_ORDINAL: dict[PipelineStage, int] = {
    PipelineStage.CONCEPT: 0,
    PipelineStage.PRE_DEVELOPMENT: 1,
    PipelineStage.ENTITLEMENT: 2,
    PipelineStage.FINANCING: 3,
    PipelineStage.CONSTRUCTION: 4,
    PipelineStage.LEASE_UP: 5,
    PipelineStage.OPERATIONS: 6,
    PipelineStage.STALLED: -1,
    PipelineStage.ABANDONED: -2,
}


# ---------------------------------------------------------------------------
# Feature descriptor
# ---------------------------------------------------------------------------

@dataclass
class FeatureSchema:
    """Describes every column the feature matrix can contain.

    Provides the canonical column ordering so that train-time and
    inference-time matrices are always aligned.
    """

    numeric_columns: list[str] = field(default_factory=list)
    categorical_columns: list[str] = field(default_factory=list)

    @property
    def all_columns(self) -> list[str]:
        return self.numeric_columns + self.categorical_columns

    @property
    def n_features(self) -> int:
        return len(self.all_columns)


def build_feature_schema() -> FeatureSchema:
    """Return the canonical feature schema used by the timeline model."""
    numeric = [
        # Scale / size
        "total_units",
        "affordable_units_pct",
        "deep_affordability_pct",
        "market_rate_pct",
        "stories",
        "parking_ratio",
        "site_acres",
        "density_units_per_acre",
        # Unit-mix proportions
        "studio_pct",
        "one_br_pct",
        "two_br_pct",
        "three_plus_br_pct",
        # Special population share
        "senior_pct",
        "family_pct",
        "psf_pct",
        "homeless_pct",
        # Regulatory complexity
        "jurisdiction_friction_score",
        "opposition_score",
        "variance_hearings",
        "design_review_iterations",
        "appeals_filed",
        # Cost context
        "cost_per_unit_log",
        "tdc_log",
        # External market signals (to be filled by caller / pipeline)
        "construction_cost_index",
        "interest_rate",
        # Peer benchmarks
        "peer_median_entitlement_days",
        "peer_median_financing_days",
        "peer_median_construction_days",
        # Calendar
        "start_month_sin",
        "start_month_cos",
        "start_year",
        # Current stage ordinal
        "current_stage_ordinal",
    ]

    categorical = (
        [f"building_type_{bt}" for bt in _BUILDING_TYPES]
        + [f"structure_type_{st}" for st in _STRUCTURE_TYPES]
    )

    return FeatureSchema(numeric_columns=numeric, categorical_columns=categorical)


# ---------------------------------------------------------------------------
# Safe value helpers
# ---------------------------------------------------------------------------

def _safe_ratio(numerator: float | None, denominator: float | None, default: float = 0.0) -> float:
    """Compute *numerator / denominator* without blowing up."""
    if numerator is None or denominator is None or denominator == 0:
        return default
    return float(numerator) / float(denominator)


def _safe_log(value: float | None, default: float = 0.0) -> float:
    if value is None or value <= 0:
        return default
    return math.log(float(value))


def _pct_of_total(part: int | None, total: int | None) -> float:
    if part is None or total is None or total == 0:
        return 0.0
    return float(part) / float(total)


# ---------------------------------------------------------------------------
# Single-project feature extraction
# ---------------------------------------------------------------------------

def extract_project_features(
    project: Project,
    *,
    construction_cost_index: float | None = None,
    interest_rate: float | None = None,
    peer_median_entitlement_days: float | None = None,
    peer_median_financing_days: float | None = None,
    peer_median_construction_days: float | None = None,
) -> dict[str, float]:
    """Convert one :class:`Project` into a flat feature dictionary.

    External signals (cost index, interest rate, peer medians) are
    accepted as keyword arguments because they are not stored directly
    on the ``Project`` row -- they come from companion tables or APIs.

    Returns a ``dict`` whose keys match :func:`build_feature_schema`.
    """
    total = project.total_units or 0
    affordable = project.affordable_units or 0
    deep_units = (project.ami_30_units or 0) + (project.ami_40_units or 0)

    three_plus_br = (project.three_br_units or 0) + (project.four_plus_br_units or 0)

    parking_ratio = _safe_ratio(project.parking_spaces, total)
    density = _safe_ratio(total, project.site_acres) if project.site_acres else 0.0

    # Calendar features -- cyclical encoding of start month
    start_date = (
        project.entitlement_start
        or project.pre_development_start
        or project.concept_start
    )
    if start_date is not None:
        month = start_date.month
        start_month_sin = math.sin(2 * math.pi * month / 12)
        start_month_cos = math.cos(2 * math.pi * month / 12)
        start_year = float(start_date.year)
    else:
        start_month_sin = 0.0
        start_month_cos = 1.0
        start_year = 0.0

    # One-hot encoding for building_type
    bt_value = project.building_type.value if project.building_type else None
    bt_features = {
        f"building_type_{bt}": float(bt == bt_value) for bt in _BUILDING_TYPES
    }

    # One-hot encoding for structure_type
    st_value = project.structure_type.value if project.structure_type else None
    st_features = {
        f"structure_type_{st}": float(st == st_value) for st in _STRUCTURE_TYPES
    }

    features: dict[str, float] = {
        # Scale / size
        "total_units": float(total),
        "affordable_units_pct": _pct_of_total(affordable, total),
        "deep_affordability_pct": _pct_of_total(deep_units, total),
        "market_rate_pct": _pct_of_total(project.market_rate_units, total),
        "stories": float(project.stories or 0),
        "parking_ratio": parking_ratio,
        "site_acres": float(project.site_acres or 0),
        "density_units_per_acre": density,
        # Unit-mix proportions
        "studio_pct": _pct_of_total(project.studio_units, total),
        "one_br_pct": _pct_of_total(project.one_br_units, total),
        "two_br_pct": _pct_of_total(project.two_br_units, total),
        "three_plus_br_pct": _pct_of_total(three_plus_br, total),
        # Special populations
        "senior_pct": _pct_of_total(project.senior_units, total),
        "family_pct": _pct_of_total(project.family_units, total),
        "psf_pct": _pct_of_total(project.psf_units, total),
        "homeless_pct": _pct_of_total(project.homeless_set_aside, total),
        # Regulatory complexity
        "jurisdiction_friction_score": float(project.jurisdiction_friction_score or 0),
        "opposition_score": float(_OPPOSITION_SCORES.get(project.neighbor_opposition_level, 0)),
        "variance_hearings": float(project.variance_hearings or 0),
        "design_review_iterations": float(project.design_review_iterations or 0),
        "appeals_filed": float(project.appeals_filed or 0),
        # Cost context
        "cost_per_unit_log": _safe_log(project.cost_per_unit),
        "tdc_log": _safe_log(project.total_development_cost),
        # External signals (defaults to 0 when unavailable)
        "construction_cost_index": float(construction_cost_index or 0),
        "interest_rate": float(interest_rate or 0),
        # Peer medians
        "peer_median_entitlement_days": float(peer_median_entitlement_days or 0),
        "peer_median_financing_days": float(peer_median_financing_days or 0),
        "peer_median_construction_days": float(peer_median_construction_days or 0),
        # Calendar
        "start_month_sin": start_month_sin,
        "start_month_cos": start_month_cos,
        "start_year": start_year,
        # Stage
        "current_stage_ordinal": float(_STAGE_ORDINAL.get(project.current_stage, -1)),
    }

    features.update(bt_features)
    features.update(st_features)

    return features


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

def extract_features_dataframe(
    projects: Sequence[Project],
    *,
    external_signals: dict[Any, dict[str, float]] | None = None,
) -> pd.DataFrame:
    """Build feature matrix for a list of projects.

    Parameters
    ----------
    projects:
        Iterable of :class:`Project` ORM objects.
    external_signals:
        Optional mapping of ``project_id -> {"construction_cost_index": ..., ...}``
        providing per-project external signals (cost index, interest rate,
        peer medians).  Keys that do not match a project are silently ignored.

    Returns
    -------
    pd.DataFrame
        One row per project, columns ordered by :func:`build_feature_schema`.
    """
    schema = build_feature_schema()
    rows: list[dict[str, float]] = []

    for proj in projects:
        ext = {}
        if external_signals and proj.project_id in external_signals:
            ext = external_signals[proj.project_id]

        row = extract_project_features(
            proj,
            construction_cost_index=ext.get("construction_cost_index"),
            interest_rate=ext.get("interest_rate"),
            peer_median_entitlement_days=ext.get("peer_median_entitlement_days"),
            peer_median_financing_days=ext.get("peer_median_financing_days"),
            peer_median_construction_days=ext.get("peer_median_construction_days"),
        )
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=schema.all_columns)

    df = pd.DataFrame(rows)

    # Ensure column ordering matches schema; fill any missing cols with 0
    for col in schema.all_columns:
        if col not in df.columns:
            df[col] = 0.0

    df = df[schema.all_columns]
    return df


def extract_targets(projects: Sequence[Project]) -> pd.DataFrame:
    """Extract the three target stage durations for supervised training.

    Returns a DataFrame with columns ``entitlement_days``,
    ``financing_days``, and ``construction_days``.  Rows where *any*
    target is ``None`` are **not** dropped -- callers should handle
    missing targets (e.g. by filtering or imputing).
    """
    records = []
    for proj in projects:
        records.append({
            "entitlement_days": proj.entitlement_duration_days,
            "financing_days": proj.financing_duration_days,
            "construction_days": proj.construction_duration_days,
        })

    return pd.DataFrame(records, columns=TARGET_STAGES)


def prepare_training_data(
    projects: Sequence[Project],
    *,
    external_signals: dict[Any, dict[str, float]] | None = None,
    drop_incomplete_targets: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One-call helper that produces aligned (X, y) matrices.

    Parameters
    ----------
    projects:
        Project ORM objects.
    external_signals:
        See :func:`extract_features_dataframe`.
    drop_incomplete_targets:
        If *True* (default), rows where **any** target column is NaN
        are dropped from both X and y.

    Returns
    -------
    (X, y) : tuple of pd.DataFrame
    """
    X = extract_features_dataframe(projects, external_signals=external_signals)
    y = extract_targets(projects)

    if drop_incomplete_targets:
        valid_mask = y.notna().all(axis=1)
        n_dropped = (~valid_mask).sum()
        if n_dropped > 0:
            logger.info(
                "Dropped %d / %d projects with incomplete target durations.",
                n_dropped,
                len(y),
            )
        X = X.loc[valid_mask].reset_index(drop=True)
        y = y.loc[valid_mask].reset_index(drop=True)

    return X, y
