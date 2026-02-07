"""Evaluation metrics and diagnostic utilities for the timeline model.

Computes RMSE, MAE, R-squared, and MAPE for each predicted stage as well
as aggregate (all-stages) metrics.  Also provides calibration checks for
the confidence-interval coverage and residual analysis helpers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.ml.feature_engineering import TARGET_STAGES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StageMetrics:
    """Evaluation metrics for a single predicted stage."""

    stage: str
    n_samples: int
    rmse: float
    mae: float
    r2: float
    mape: float  # mean absolute percentage error (0-100 scale)
    median_absolute_error: float
    max_error: float
    mean_residual: float  # bias indicator; ideally ~0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "n_samples": self.n_samples,
            "rmse": round(self.rmse, 2),
            "mae": round(self.mae, 2),
            "r2": round(self.r2, 4),
            "mape": round(self.mape, 2),
            "median_absolute_error": round(self.median_absolute_error, 2),
            "max_error": round(self.max_error, 2),
            "mean_residual": round(self.mean_residual, 2),
        }


@dataclass
class EvaluationReport:
    """Full evaluation report spanning all target stages."""

    per_stage: dict[str, StageMetrics]
    aggregate_rmse: float
    aggregate_mae: float
    aggregate_r2: float
    aggregate_mape: float
    ci_coverage: dict[str, float] | None = None  # fraction of actuals inside CI
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "per_stage": {k: v.to_dict() for k, v in self.per_stage.items()},
            "aggregate": {
                "rmse": round(self.aggregate_rmse, 2),
                "mae": round(self.aggregate_mae, 2),
                "r2": round(self.aggregate_r2, 4),
                "mape": round(self.aggregate_mape, 2),
            },
            "ci_coverage": (
                {k: round(v, 4) for k, v in self.ci_coverage.items()}
                if self.ci_coverage
                else None
            ),
            "metadata": self.metadata,
        }

    def summary_table(self) -> pd.DataFrame:
        """Return a tidy DataFrame with one row per stage + an aggregate row."""
        rows = []
        for stage in TARGET_STAGES:
            if stage in self.per_stage:
                rows.append(self.per_stage[stage].to_dict())

        rows.append({
            "stage": "AGGREGATE",
            "n_samples": rows[0]["n_samples"] if rows else 0,
            "rmse": round(self.aggregate_rmse, 2),
            "mae": round(self.aggregate_mae, 2),
            "r2": round(self.aggregate_r2, 4),
            "mape": round(self.aggregate_mape, 2),
            "median_absolute_error": None,
            "max_error": None,
            "mean_residual": None,
        })
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Core metric computation
# ---------------------------------------------------------------------------

def _compute_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean absolute percentage error (0-100 scale).

    Samples where ``y_true == 0`` are excluded to avoid division by zero.
    Returns 0.0 if no valid samples remain.
    """
    mask = y_true != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def compute_stage_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    stage: str,
) -> StageMetrics:
    """Compute all metrics for a single target stage.

    Parameters
    ----------
    y_true : 1-D array of actual durations.
    y_pred : 1-D array of predicted durations.
    stage  : Human-readable stage name (e.g. ``"entitlement_days"``).
    """
    y_true = np.asarray(y_true, dtype=np.float64).ravel()
    y_pred = np.asarray(y_pred, dtype=np.float64).ravel()

    if len(y_true) != len(y_pred):
        raise ValueError(
            f"Length mismatch: y_true has {len(y_true)}, y_pred has {len(y_pred)}"
        )

    n = len(y_true)
    residuals = y_true - y_pred

    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae = float(mean_absolute_error(y_true, y_pred))
    r2 = float(r2_score(y_true, y_pred)) if n >= 2 else 0.0
    mape = _compute_mape(y_true, y_pred)
    med_ae = float(np.median(np.abs(residuals)))
    max_err = float(np.max(np.abs(residuals))) if n > 0 else 0.0
    mean_res = float(np.mean(residuals))

    return StageMetrics(
        stage=stage,
        n_samples=n,
        rmse=rmse,
        mae=mae,
        r2=r2,
        mape=mape,
        median_absolute_error=med_ae,
        max_error=max_err,
        mean_residual=mean_res,
    )


# ---------------------------------------------------------------------------
# Full evaluation
# ---------------------------------------------------------------------------

def evaluate_predictions(
    y_true: pd.DataFrame | np.ndarray,
    y_pred: pd.DataFrame | np.ndarray,
    *,
    y_pred_lower: pd.DataFrame | np.ndarray | None = None,
    y_pred_upper: pd.DataFrame | np.ndarray | None = None,
    confidence_level: float | None = None,
) -> EvaluationReport:
    """Evaluate multi-stage predictions and build a full report.

    Parameters
    ----------
    y_true:
        Actual stage durations, shape ``(n, 3)`` with columns ordered
        per ``TARGET_STAGES``.
    y_pred:
        Predicted stage durations, same shape.
    y_pred_lower, y_pred_upper:
        Optional lower/upper bounds of confidence intervals.  When
        both are provided, CI coverage is computed.
    confidence_level:
        Nominal CI probability (recorded in metadata).

    Returns
    -------
    EvaluationReport
    """
    y_true_arr = np.asarray(y_true, dtype=np.float64)
    y_pred_arr = np.asarray(y_pred, dtype=np.float64)

    if y_true_arr.ndim == 1:
        y_true_arr = y_true_arr.reshape(-1, 1)
    if y_pred_arr.ndim == 1:
        y_pred_arr = y_pred_arr.reshape(-1, 1)

    n_stages = y_true_arr.shape[1]
    if n_stages != len(TARGET_STAGES):
        raise ValueError(
            f"Expected {len(TARGET_STAGES)} target columns, got {n_stages}"
        )

    # Per-stage metrics
    per_stage: dict[str, StageMetrics] = {}
    for idx, stage in enumerate(TARGET_STAGES):
        per_stage[stage] = compute_stage_metrics(
            y_true_arr[:, idx], y_pred_arr[:, idx], stage
        )

    # Aggregate metrics (flatten all stages into one vector)
    all_true = y_true_arr.ravel()
    all_pred = y_pred_arr.ravel()

    agg_rmse = float(np.sqrt(mean_squared_error(all_true, all_pred)))
    agg_mae = float(mean_absolute_error(all_true, all_pred))
    agg_r2 = float(r2_score(all_true, all_pred)) if len(all_true) >= 2 else 0.0
    agg_mape = _compute_mape(all_true, all_pred)

    # CI coverage
    ci_coverage: dict[str, float] | None = None
    if y_pred_lower is not None and y_pred_upper is not None:
        lower_arr = np.asarray(y_pred_lower, dtype=np.float64)
        upper_arr = np.asarray(y_pred_upper, dtype=np.float64)
        if lower_arr.ndim == 1:
            lower_arr = lower_arr.reshape(-1, 1)
        if upper_arr.ndim == 1:
            upper_arr = upper_arr.reshape(-1, 1)

        ci_coverage = {}
        for idx, stage in enumerate(TARGET_STAGES):
            in_interval = (
                (y_true_arr[:, idx] >= lower_arr[:, idx])
                & (y_true_arr[:, idx] <= upper_arr[:, idx])
            )
            ci_coverage[stage] = float(np.mean(in_interval))

        # Aggregate coverage
        all_in = (
            (y_true_arr >= lower_arr) & (y_true_arr <= upper_arr)
        )
        ci_coverage["aggregate"] = float(np.mean(all_in))

    metadata: dict[str, Any] = {
        "n_samples": int(y_true_arr.shape[0]),
        "n_stages": n_stages,
    }
    if confidence_level is not None:
        metadata["confidence_level"] = confidence_level

    report = EvaluationReport(
        per_stage=per_stage,
        aggregate_rmse=agg_rmse,
        aggregate_mae=agg_mae,
        aggregate_r2=agg_r2,
        aggregate_mape=agg_mape,
        ci_coverage=ci_coverage,
        metadata=metadata,
    )

    _log_report(report)
    return report


# ---------------------------------------------------------------------------
# Residual analysis helpers
# ---------------------------------------------------------------------------

def residual_dataframe(
    y_true: pd.DataFrame | np.ndarray,
    y_pred: pd.DataFrame | np.ndarray,
) -> pd.DataFrame:
    """Build a tidy DataFrame of residuals for further analysis / plotting.

    Returns columns: ``stage``, ``actual``, ``predicted``, ``residual``,
    ``abs_error``, ``pct_error``.
    """
    y_true_arr = np.asarray(y_true, dtype=np.float64)
    y_pred_arr = np.asarray(y_pred, dtype=np.float64)

    rows = []
    for idx, stage in enumerate(TARGET_STAGES):
        for i in range(y_true_arr.shape[0]):
            actual = y_true_arr[i, idx]
            pred = y_pred_arr[i, idx]
            resid = actual - pred
            abs_err = abs(resid)
            pct_err = (abs_err / actual * 100) if actual != 0 else 0.0
            rows.append({
                "stage": stage,
                "sample_idx": i,
                "actual": actual,
                "predicted": pred,
                "residual": resid,
                "abs_error": abs_err,
                "pct_error": pct_err,
            })

    return pd.DataFrame(rows)


def identify_outlier_predictions(
    y_true: pd.DataFrame | np.ndarray,
    y_pred: pd.DataFrame | np.ndarray,
    *,
    threshold_pct: float = 50.0,
) -> pd.DataFrame:
    """Return rows where the percentage error exceeds *threshold_pct*.

    Useful for finding projects whose durations are poorly predicted and
    may require manual review or additional features.
    """
    df = residual_dataframe(y_true, y_pred)
    outliers = df[df["pct_error"] > threshold_pct].sort_values(
        "pct_error", ascending=False
    )
    return outliers.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cross-validation evaluation helper
# ---------------------------------------------------------------------------

def evaluate_cv_results(
    cv_scores: dict[str, list[float]],
) -> dict[str, dict[str, float]]:
    """Summarize per-fold cross-validation scores.

    Parameters
    ----------
    cv_scores:
        Mapping of ``metric_name -> [fold_1_score, fold_2_score, ...]``.

    Returns
    -------
    dict mapping each metric to ``{"mean": ..., "std": ..., "min": ..., "max": ...}``.
    """
    summary: dict[str, dict[str, float]] = {}
    for metric, scores in cv_scores.items():
        arr = np.array(scores, dtype=np.float64)
        summary[metric] = {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "n_folds": len(scores),
        }
    return summary


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log_report(report: EvaluationReport) -> None:
    """Emit a summary of the evaluation report to the logger."""
    logger.info("=== Evaluation Report ===")
    for stage, m in report.per_stage.items():
        logger.info(
            "  %-25s  RMSE=%7.1f  MAE=%7.1f  R2=%6.3f  MAPE=%5.1f%%",
            stage,
            m.rmse,
            m.mae,
            m.r2,
            m.mape,
        )
    logger.info(
        "  %-25s  RMSE=%7.1f  MAE=%7.1f  R2=%6.3f  MAPE=%5.1f%%",
        "AGGREGATE",
        report.aggregate_rmse,
        report.aggregate_mae,
        report.aggregate_r2,
        report.aggregate_mape,
    )
    if report.ci_coverage:
        for stage, cov in report.ci_coverage.items():
            logger.info("  CI coverage %-20s  %.1f%%", stage, cov * 100)
