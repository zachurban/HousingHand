"""Training pipeline for the HousingHand timeline prediction model.

Provides a structured pipeline that:

1. Accepts raw Project ORM objects (or pre-built feature / target matrices).
2. Splits data into train / test sets.
3. Runs k-fold cross-validation on the training set.
4. Trains the final model on the full training set.
5. Evaluates on the held-out test set.
6. Persists the trained model artifact.

Hyperparameter notes
--------------------
The default Random Forest configuration was chosen for a balance of
accuracy and training speed on the typical HousingHand dataset size
(hundreds to low-thousands of projects):

* ``n_estimators=300`` -- enough trees for stable quantile intervals
  without excessive memory.
* ``max_depth=18`` -- deep enough to capture non-linear interactions
  (e.g. friction * building_type) without severe overfitting on <2 k
  samples.
* ``min_samples_split=8, min_samples_leaf=4`` -- regularization guards
  against noisy duration outliers.
* ``max_features="sqrt"`` -- decorrelates trees and improves CI coverage.

For larger datasets (>5 k rows) consider increasing ``n_estimators`` to
500 and relaxing ``min_samples_leaf`` to 2.  A Bayesian optimisation
sweep over ``max_depth``, ``min_samples_leaf``, and ``n_estimators`` is
recommended before production deployment.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold, train_test_split

from src.ml.feature_engineering import (
    TARGET_STAGES,
    build_feature_schema,
    extract_features_dataframe,
    extract_targets,
    prepare_training_data,
)
from src.ml.model_evaluation import (
    EvaluationReport,
    evaluate_cv_results,
    evaluate_predictions,
)
from src.ml.timeline_model import DEFAULT_RF_PARAMS, TimelineModel
from src.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TrainingConfig:
    """All tunables for a training run, gathered in one place."""

    # Train / test split
    test_size: float = 0.20
    split_random_state: int = 42

    # Cross-validation
    cv_folds: int = 5
    cv_shuffle: bool = True
    cv_random_state: int = 42

    # Random Forest hyperparameters (forwarded to TimelineModel)
    rf_params: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RF_PARAMS))

    # Confidence interval width
    confidence_level: float = 0.90

    # Artifact persistence
    model_output_path: str | None = None  # if set, model is saved here after training

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of this config."""
        return {
            "test_size": self.test_size,
            "cv_folds": self.cv_folds,
            "confidence_level": self.confidence_level,
            "rf_params": self.rf_params,
            "model_output_path": self.model_output_path,
        }


# ---------------------------------------------------------------------------
# Training result container
# ---------------------------------------------------------------------------

@dataclass
class TrainingResult:
    """Everything produced by a single training pipeline run."""

    model: TimelineModel
    config: TrainingConfig

    # Data dimensions
    n_total_samples: int = 0
    n_train_samples: int = 0
    n_test_samples: int = 0

    # Cross-validation results (per-stage, per-fold)
    cv_scores: dict[str, dict[str, float]] = field(default_factory=dict)

    # Held-out test evaluation
    test_evaluation: EvaluationReport | None = None

    # Timing
    training_duration_seconds: float = 0.0

    # Artifact path (populated if model was saved)
    model_path: Path | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "n_total_samples": self.n_total_samples,
            "n_train_samples": self.n_train_samples,
            "n_test_samples": self.n_test_samples,
            "cv_scores": self.cv_scores,
            "test_evaluation": (
                self.test_evaluation.to_dict() if self.test_evaluation else None
            ),
            "training_duration_seconds": round(self.training_duration_seconds, 2),
            "model_path": str(self.model_path) if self.model_path else None,
            "config": self.config.describe(),
        }


# ---------------------------------------------------------------------------
# Cross-validation helper
# ---------------------------------------------------------------------------

def _run_cross_validation(
    X_train: np.ndarray,
    y_train: np.ndarray,
    config: TrainingConfig,
) -> dict[str, dict[str, float]]:
    """Run K-Fold CV and return summarized per-stage scores.

    For each fold, a fresh ``TimelineModel`` is trained and evaluated.
    Returns a nested dict:  ``stage -> {"rmse_mean", "rmse_std", ...}``.
    """
    kf = KFold(
        n_splits=config.cv_folds,
        shuffle=config.cv_shuffle,
        random_state=config.cv_random_state,
    )

    # Accumulators: stage -> metric_name -> [fold_scores]
    fold_scores: dict[str, dict[str, list[float]]] = {
        stage: {"rmse": [], "mae": [], "r2": []}
        for stage in TARGET_STAGES
    }

    for fold_idx, (train_idx, val_idx) in enumerate(kf.split(X_train)):
        logger.info("CV fold %d / %d", fold_idx + 1, config.cv_folds)

        X_fold_train = X_train[train_idx]
        y_fold_train = y_train[train_idx]
        X_fold_val = X_train[val_idx]
        y_fold_val = y_train[val_idx]

        fold_model = TimelineModel(
            rf_params=config.rf_params,
            confidence_level=config.confidence_level,
        )
        fold_model.train(X_fold_train, y_fold_val if y_fold_train is None else y_fold_train)

        # Predict and evaluate
        pred_df = fold_model.predict_dataframe(X_fold_val)

        for stage_idx, stage in enumerate(TARGET_STAGES):
            prefix = stage.replace("_days", "")
            y_actual = y_fold_val[:, stage_idx]
            y_predicted = pred_df[f"{prefix}_pred"].values

            residuals = y_actual - y_predicted
            rmse = float(np.sqrt(np.mean(residuals ** 2)))
            mae = float(np.mean(np.abs(residuals)))
            ss_res = float(np.sum(residuals ** 2))
            ss_tot = float(np.sum((y_actual - np.mean(y_actual)) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

            fold_scores[stage]["rmse"].append(rmse)
            fold_scores[stage]["mae"].append(mae)
            fold_scores[stage]["r2"].append(r2)

    # Summarize fold scores
    cv_summary: dict[str, dict[str, float]] = {}
    for stage in TARGET_STAGES:
        stage_key = stage.replace("_days", "")
        for metric in ("rmse", "mae", "r2"):
            scores = fold_scores[stage][metric]
            cv_summary[f"{stage_key}_{metric}_mean"] = float(np.mean(scores))
            cv_summary[f"{stage_key}_{metric}_std"] = float(np.std(scores))

    # Also flatten for the evaluate_cv_results helper
    flat_cv: dict[str, list[float]] = {}
    for stage in TARGET_STAGES:
        stage_key = stage.replace("_days", "")
        for metric in ("rmse", "mae", "r2"):
            flat_cv[f"{stage_key}_{metric}"] = fold_scores[stage][metric]

    detailed = evaluate_cv_results(flat_cv)
    return detailed


# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------

def run_training_pipeline(
    projects: Sequence[Project],
    *,
    external_signals: dict[Any, dict[str, float]] | None = None,
    config: TrainingConfig | None = None,
) -> TrainingResult:
    """End-to-end training pipeline from raw Project objects.

    Steps
    -----
    1. Feature extraction + target extraction.
    2. Drop rows with incomplete targets.
    3. Train / test split.
    4. K-fold cross-validation on training set.
    5. Final model training on full training set.
    6. Evaluation on held-out test set.
    7. (Optional) save the model artifact.

    Parameters
    ----------
    projects:
        Iterable of ``Project`` ORM instances.
    external_signals:
        Per-project external market data (see ``feature_engineering``).
    config:
        Training hyperparameters.  Uses sensible defaults if omitted.

    Returns
    -------
    TrainingResult
    """
    if config is None:
        config = TrainingConfig()

    t0 = time.perf_counter()

    logger.info("Starting training pipeline with %d projects.", len(projects))

    # 1. Prepare data
    X, y = prepare_training_data(
        projects,
        external_signals=external_signals,
        drop_incomplete_targets=True,
    )

    n_total = len(X)
    logger.info("Usable samples after dropping incomplete targets: %d", n_total)

    if n_total < config.cv_folds + 2:
        raise ValueError(
            f"Not enough usable samples ({n_total}) for {config.cv_folds}-fold CV. "
            f"Need at least {config.cv_folds + 2}."
        )

    # 2. Train / test split
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=config.test_size,
        random_state=config.split_random_state,
    )

    n_train = len(X_train)
    n_test = len(X_test)
    logger.info("Split: %d train, %d test (%.0f%% held out).", n_train, n_test, config.test_size * 100)

    # Convert to numpy for sklearn
    X_train_arr = X_train.values.astype(np.float64)
    y_train_arr = y_train.values.astype(np.float64)
    X_test_arr = X_test.values.astype(np.float64)
    y_test_arr = y_test.values.astype(np.float64)

    # 3. Cross-validation
    logger.info("Running %d-fold cross-validation ...", config.cv_folds)
    cv_scores = _run_cross_validation(X_train_arr, y_train_arr, config)

    # 4. Train final model on full training set
    logger.info("Training final model on full training set ...")
    model = TimelineModel(
        rf_params=config.rf_params,
        confidence_level=config.confidence_level,
    )
    model.train(X_train, y_train)

    # 5. Evaluate on held-out test set
    logger.info("Evaluating on held-out test set ...")
    pred_df = model.predict_dataframe(X_test_arr, confidence_level=config.confidence_level)

    # Build y_pred array aligned with TARGET_STAGES
    y_pred_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_pred"].values
        for stage in TARGET_STAGES
    ])

    y_lower_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_lower"].values
        for stage in TARGET_STAGES
    ])

    y_upper_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_upper"].values
        for stage in TARGET_STAGES
    ])

    test_eval = evaluate_predictions(
        y_test_arr,
        y_pred_arr,
        y_pred_lower=y_lower_arr,
        y_pred_upper=y_upper_arr,
        confidence_level=config.confidence_level,
    )

    elapsed = time.perf_counter() - t0

    # 6. Optionally save model
    model_path: Path | None = None
    if config.model_output_path:
        model_path = model.save(config.model_output_path)

    result = TrainingResult(
        model=model,
        config=config,
        n_total_samples=n_total,
        n_train_samples=n_train,
        n_test_samples=n_test,
        cv_scores=cv_scores,
        test_evaluation=test_eval,
        training_duration_seconds=elapsed,
        model_path=model_path,
    )

    logger.info("Pipeline complete in %.1fs.", elapsed)
    return result


# ---------------------------------------------------------------------------
# Convenience: train from pre-built matrices
# ---------------------------------------------------------------------------

def train_from_dataframes(
    X: pd.DataFrame,
    y: pd.DataFrame,
    *,
    config: TrainingConfig | None = None,
) -> TrainingResult:
    """Train from pre-built feature / target DataFrames (skip ORM extraction).

    Useful when features have already been computed or when working with
    CSV exports rather than a live database.
    """
    if config is None:
        config = TrainingConfig()

    t0 = time.perf_counter()

    n_total = len(X)
    if n_total < config.cv_folds + 2:
        raise ValueError(
            f"Not enough samples ({n_total}) for {config.cv_folds}-fold CV."
        )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=config.test_size,
        random_state=config.split_random_state,
    )

    n_train = len(X_train)
    n_test = len(X_test)

    X_train_arr = X_train.values.astype(np.float64)
    y_train_arr = y_train.values.astype(np.float64)
    X_test_arr = X_test.values.astype(np.float64)
    y_test_arr = y_test.values.astype(np.float64)

    # Cross-validation
    cv_scores = _run_cross_validation(X_train_arr, y_train_arr, config)

    # Final model
    model = TimelineModel(
        rf_params=config.rf_params,
        confidence_level=config.confidence_level,
    )
    model.train(X_train, y_train)

    # Test evaluation
    pred_df = model.predict_dataframe(X_test_arr, confidence_level=config.confidence_level)

    y_pred_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_pred"].values
        for stage in TARGET_STAGES
    ])
    y_lower_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_lower"].values
        for stage in TARGET_STAGES
    ])
    y_upper_arr = np.column_stack([
        pred_df[f"{stage.replace('_days', '')}_upper"].values
        for stage in TARGET_STAGES
    ])

    test_eval = evaluate_predictions(
        y_test_arr,
        y_pred_arr,
        y_pred_lower=y_lower_arr,
        y_pred_upper=y_upper_arr,
        confidence_level=config.confidence_level,
    )

    elapsed = time.perf_counter() - t0

    model_path: Path | None = None
    if config.model_output_path:
        model_path = model.save(config.model_output_path)

    return TrainingResult(
        model=model,
        config=config,
        n_total_samples=n_total,
        n_train_samples=n_train,
        n_test_samples=n_test,
        cv_scores=cv_scores,
        test_evaluation=test_eval,
        training_duration_seconds=elapsed,
        model_path=model_path,
    )


# ---------------------------------------------------------------------------
# Retrain helper (full dataset, no held-out test -- for final deployment)
# ---------------------------------------------------------------------------

def retrain_production_model(
    projects: Sequence[Project],
    *,
    external_signals: dict[Any, dict[str, float]] | None = None,
    config: TrainingConfig | None = None,
    output_path: str = "models/timeline_model.joblib",
) -> TimelineModel:
    """Train on **all** available data and save for production inference.

    No test split or CV is performed -- this is intended for producing
    the final artifact after hyper-parameters have been validated via
    :func:`run_training_pipeline`.
    """
    if config is None:
        config = TrainingConfig()

    X, y = prepare_training_data(
        projects,
        external_signals=external_signals,
        drop_incomplete_targets=True,
    )

    logger.info("Retraining production model on %d samples.", len(X))

    model = TimelineModel(
        rf_params=config.rf_params,
        confidence_level=config.confidence_level,
    )
    model.train(X, y)
    model.save(output_path)

    logger.info("Production model saved to %s.", output_path)
    return model
