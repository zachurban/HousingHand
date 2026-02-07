"""Random Forest model for affordable-housing stage-duration prediction.

Wraps three :class:`~sklearn.ensemble.RandomForestRegressor` estimators
(one per target stage) and exposes a unified ``train / predict / save / load``
interface.  Confidence intervals are derived from individual-tree predictions
(quantile estimation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from src.ml.feature_engineering import TARGET_STAGES, build_feature_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes for structured output
# ---------------------------------------------------------------------------

@dataclass
class StagePrediction:
    """Point prediction + confidence interval for a single stage."""

    stage: str
    predicted_days: float
    lower_bound: float
    upper_bound: float
    confidence_level: float  # e.g. 0.90 for a 90 % interval


@dataclass
class TimelinePrediction:
    """Combined prediction for all three stages of a single project."""

    entitlement: StagePrediction
    financing: StagePrediction
    construction: StagePrediction
    total_predicted_days: float
    predicted_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary (JSON-friendly)."""
        return {
            "entitlement": {
                "predicted_days": round(self.entitlement.predicted_days, 1),
                "lower_bound": round(self.entitlement.lower_bound, 1),
                "upper_bound": round(self.entitlement.upper_bound, 1),
                "confidence_level": self.entitlement.confidence_level,
            },
            "financing": {
                "predicted_days": round(self.financing.predicted_days, 1),
                "lower_bound": round(self.financing.lower_bound, 1),
                "upper_bound": round(self.financing.upper_bound, 1),
                "confidence_level": self.financing.confidence_level,
            },
            "construction": {
                "predicted_days": round(self.construction.predicted_days, 1),
                "lower_bound": round(self.construction.lower_bound, 1),
                "upper_bound": round(self.construction.upper_bound, 1),
                "confidence_level": self.construction.confidence_level,
            },
            "total_predicted_days": round(self.total_predicted_days, 1),
            "predicted_at": self.predicted_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Default hyper-parameters
# ---------------------------------------------------------------------------

DEFAULT_RF_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 18,
    "min_samples_split": 8,
    "min_samples_leaf": 4,
    "max_features": "sqrt",
    "random_state": 42,
    "n_jobs": -1,
}


# ---------------------------------------------------------------------------
# Model wrapper
# ---------------------------------------------------------------------------

class TimelineModel:
    """Multi-output Random Forest model for stage-duration prediction.

    Internally maintains one ``RandomForestRegressor`` per target stage so
    that hyper-parameters can (optionally) be tuned per-stage, and so
    that confidence intervals can be extracted from each forest
    independently.

    Parameters
    ----------
    rf_params:
        Keyword arguments forwarded to each ``RandomForestRegressor``.
        Defaults to :data:`DEFAULT_RF_PARAMS`.
    confidence_level:
        Width of the prediction interval expressed as a probability
        (e.g. ``0.90`` for a 90 % CI).  Quantiles are computed from
        the individual-tree predictions.
    """

    def __init__(
        self,
        rf_params: dict[str, Any] | None = None,
        confidence_level: float = 0.90,
    ) -> None:
        self.rf_params = rf_params or dict(DEFAULT_RF_PARAMS)
        self.confidence_level = confidence_level

        # One estimator per target stage
        self._models: dict[str, RandomForestRegressor] = {}
        self._is_fitted: bool = False
        self._feature_names: list[str] = []
        self._train_timestamp: datetime | None = None

        # Per-stage training metadata (populated after fit)
        self._train_stats: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.DataFrame | np.ndarray,
    ) -> "TimelineModel":
        """Fit one Random Forest per target stage.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
        y : array-like of shape (n_samples, 3)
            Columns must be ordered as ``TARGET_STAGES``
            (entitlement_days, financing_days, construction_days).

        Returns
        -------
        self
        """
        if isinstance(X, pd.DataFrame):
            self._feature_names = list(X.columns)
            X_arr = X.values.astype(np.float64)
        else:
            X_arr = np.asarray(X, dtype=np.float64)
            schema = build_feature_schema()
            self._feature_names = schema.all_columns

        if isinstance(y, pd.DataFrame):
            y_arr = y.values.astype(np.float64)
        else:
            y_arr = np.asarray(y, dtype=np.float64)

        if y_arr.shape[1] != len(TARGET_STAGES):
            raise ValueError(
                f"y must have {len(TARGET_STAGES)} columns matching TARGET_STAGES, "
                f"got {y_arr.shape[1]}"
            )

        # Replace any remaining NaNs in X with 0 (defensive)
        X_arr = np.nan_to_num(X_arr, nan=0.0)

        for idx, stage in enumerate(TARGET_STAGES):
            logger.info("Training RandomForest for %s ...", stage)
            rf = RandomForestRegressor(**self.rf_params)
            rf.fit(X_arr, y_arr[:, idx])
            self._models[stage] = rf

            # Capture basic training stats
            self._train_stats[stage] = {
                "n_samples": int(X_arr.shape[0]),
                "y_mean": float(np.mean(y_arr[:, idx])),
                "y_std": float(np.std(y_arr[:, idx])),
                "y_min": float(np.min(y_arr[:, idx])),
                "y_max": float(np.max(y_arr[:, idx])),
            }

        self._is_fitted = True
        self._train_timestamp = datetime.utcnow()
        logger.info(
            "Training complete. %d samples, %d features, %d trees/stage.",
            X_arr.shape[0],
            X_arr.shape[1],
            self.rf_params.get("n_estimators", "?"),
        )
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        X: pd.DataFrame | np.ndarray,
        *,
        confidence_level: float | None = None,
    ) -> list[TimelinePrediction]:
        """Generate timeline predictions with confidence intervals.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
        confidence_level:
            Override the instance-level confidence_level for this call.

        Returns
        -------
        list[TimelinePrediction]
            One prediction object per input row.
        """
        self._check_fitted()

        if isinstance(X, pd.DataFrame):
            X_arr = X.values.astype(np.float64)
        else:
            X_arr = np.asarray(X, dtype=np.float64)

        X_arr = np.nan_to_num(X_arr, nan=0.0)

        cl = confidence_level if confidence_level is not None else self.confidence_level
        lower_q = (1.0 - cl) / 2.0
        upper_q = 1.0 - lower_q

        # Collect per-tree predictions for quantile estimation
        stage_predictions: dict[str, dict[str, np.ndarray]] = {}
        for stage in TARGET_STAGES:
            rf = self._models[stage]
            # Each tree predicts independently
            tree_preds = np.array(
                [tree.predict(X_arr) for tree in rf.estimators_]
            )  # shape: (n_trees, n_samples)

            stage_predictions[stage] = {
                "mean": np.mean(tree_preds, axis=0),
                "lower": np.quantile(tree_preds, lower_q, axis=0),
                "upper": np.quantile(tree_preds, upper_q, axis=0),
            }

        results: list[TimelinePrediction] = []
        n_samples = X_arr.shape[0]

        for i in range(n_samples):
            stage_preds: dict[str, StagePrediction] = {}
            for stage in TARGET_STAGES:
                sp = StagePrediction(
                    stage=stage,
                    predicted_days=float(max(stage_predictions[stage]["mean"][i], 0)),
                    lower_bound=float(max(stage_predictions[stage]["lower"][i], 0)),
                    upper_bound=float(max(stage_predictions[stage]["upper"][i], 0)),
                    confidence_level=cl,
                )
                stage_preds[stage] = sp

            total = sum(sp.predicted_days for sp in stage_preds.values())

            results.append(
                TimelinePrediction(
                    entitlement=stage_preds["entitlement_days"],
                    financing=stage_preds["financing_days"],
                    construction=stage_preds["construction_days"],
                    total_predicted_days=total,
                )
            )

        return results

    def predict_dataframe(
        self,
        X: pd.DataFrame | np.ndarray,
        *,
        confidence_level: float | None = None,
    ) -> pd.DataFrame:
        """Return predictions as a flat DataFrame (convenient for analysis).

        Columns: ``<stage>_pred``, ``<stage>_lower``, ``<stage>_upper``
        for each target stage, plus ``total_pred``.
        """
        preds = self.predict(X, confidence_level=confidence_level)
        rows = []
        for p in preds:
            row: dict[str, float] = {}
            for stage_pred in (p.entitlement, p.financing, p.construction):
                prefix = stage_pred.stage.replace("_days", "")
                row[f"{prefix}_pred"] = stage_pred.predicted_days
                row[f"{prefix}_lower"] = stage_pred.lower_bound
                row[f"{prefix}_upper"] = stage_pred.upper_bound
            row["total_pred"] = p.total_predicted_days
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Feature importance
    # ------------------------------------------------------------------

    def feature_importances(self) -> pd.DataFrame:
        """Return a DataFrame of feature importances across all stages.

        Columns: ``feature``, plus one column per stage with the MDI
        importance from that stage's forest, plus ``mean_importance``.
        """
        self._check_fitted()
        data: dict[str, list[float]] = {"feature": self._feature_names}
        all_importances: list[np.ndarray] = []

        for stage in TARGET_STAGES:
            imp = self._models[stage].feature_importances_
            col_name = stage.replace("_days", "") + "_importance"
            data[col_name] = imp.tolist()
            all_importances.append(imp)

        data["mean_importance"] = np.mean(all_importances, axis=0).tolist()
        df = pd.DataFrame(data).sort_values("mean_importance", ascending=False)
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        """Persist the model to disk using joblib.

        The saved artifact includes the fitted estimators, feature
        schema, training stats, and hyper-parameters so that inference
        is fully self-contained.

        Parameters
        ----------
        path:
            File path for the output ``.joblib`` file.

        Returns
        -------
        pathlib.Path
            Resolved path of the saved file.
        """
        self._check_fitted()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        artifact = {
            "models": self._models,
            "rf_params": self.rf_params,
            "confidence_level": self.confidence_level,
            "feature_names": self._feature_names,
            "target_stages": TARGET_STAGES,
            "train_stats": self._train_stats,
            "train_timestamp": self._train_timestamp,
            "version": "1.0.0",
        }

        joblib.dump(artifact, path)
        logger.info("Model saved to %s", path)
        return path.resolve()

    @classmethod
    def load(cls, path: str | Path) -> "TimelineModel":
        """Reconstruct a :class:`TimelineModel` from a joblib artifact.

        Parameters
        ----------
        path:
            Path to the ``.joblib`` file produced by :meth:`save`.

        Returns
        -------
        TimelineModel
        """
        path = Path(path)
        artifact: dict[str, Any] = joblib.load(path)

        instance = cls(
            rf_params=artifact["rf_params"],
            confidence_level=artifact.get("confidence_level", 0.90),
        )
        instance._models = artifact["models"]
        instance._feature_names = artifact["feature_names"]
        instance._train_stats = artifact.get("train_stats", {})
        instance._train_timestamp = artifact.get("train_timestamp")
        instance._is_fitted = True

        logger.info(
            "Model loaded from %s (trained %s, version %s).",
            path,
            instance._train_timestamp,
            artifact.get("version", "unknown"),
        )
        return instance

    # ------------------------------------------------------------------
    # Metadata / introspection
    # ------------------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def train_stats(self) -> dict[str, dict[str, float]]:
        return dict(self._train_stats)

    @property
    def train_timestamp(self) -> datetime | None:
        return self._train_timestamp

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of model metadata."""
        return {
            "is_fitted": self._is_fitted,
            "n_features": len(self._feature_names),
            "target_stages": TARGET_STAGES,
            "rf_params": self.rf_params,
            "confidence_level": self.confidence_level,
            "train_timestamp": (
                self._train_timestamp.isoformat() if self._train_timestamp else None
            ),
            "train_stats": self._train_stats,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_fitted(self) -> None:
        if not self._is_fitted:
            raise RuntimeError(
                "TimelineModel has not been trained yet. Call .train() first."
            )

    def __repr__(self) -> str:
        status = "fitted" if self._is_fitted else "unfitted"
        n_trees = self.rf_params.get("n_estimators", "?")
        return f"<TimelineModel({status}, trees={n_trees}, ci={self.confidence_level})>"
