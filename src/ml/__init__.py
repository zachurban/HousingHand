"""HousingHand ML module -- timeline prediction for affordable housing projects.

Public API
----------
Model layer:
    TimelineModel          -- Random Forest wrapper (train / predict / save / load)
    StagePrediction        -- Single-stage prediction with CI bounds
    TimelinePrediction     -- Combined 3-stage prediction result

Feature engineering:
    extract_project_features   -- Single-project feature dict
    extract_features_dataframe -- Batch feature matrix
    extract_targets            -- Target (y) matrix from projects
    prepare_training_data      -- One-call (X, y) builder
    build_feature_schema       -- Canonical column ordering

Training pipeline:
    run_training_pipeline      -- Full train/CV/evaluate from ORM objects
    train_from_dataframes      -- Train from pre-built DataFrames
    retrain_production_model   -- Final artifact with no held-out split
    TrainingConfig             -- Hyperparameter configuration
    TrainingResult             -- Pipeline output container

Evaluation:
    evaluate_predictions       -- RMSE / MAE / R2 / MAPE + CI coverage
    compute_stage_metrics      -- Metrics for a single stage
    residual_dataframe         -- Tidy residuals for plotting
    identify_outlier_predictions -- Flag poorly predicted projects
    EvaluationReport           -- Full evaluation container
    StageMetrics               -- Per-stage metric container
"""

from src.ml.feature_engineering import (
    TARGET_STAGES,
    build_feature_schema,
    extract_features_dataframe,
    extract_project_features,
    extract_targets,
    prepare_training_data,
)
from src.ml.model_evaluation import (
    EvaluationReport,
    StageMetrics,
    compute_stage_metrics,
    evaluate_predictions,
    identify_outlier_predictions,
    residual_dataframe,
)
from src.ml.model_training import (
    TrainingConfig,
    TrainingResult,
    retrain_production_model,
    run_training_pipeline,
    train_from_dataframes,
)
from src.ml.timeline_model import (
    StagePrediction,
    TimelineModel,
    TimelinePrediction,
)

__all__ = [
    # Model
    "TimelineModel",
    "StagePrediction",
    "TimelinePrediction",
    # Features
    "extract_project_features",
    "extract_features_dataframe",
    "extract_targets",
    "prepare_training_data",
    "build_feature_schema",
    "TARGET_STAGES",
    # Training
    "run_training_pipeline",
    "train_from_dataframes",
    "retrain_production_model",
    "TrainingConfig",
    "TrainingResult",
    # Evaluation
    "evaluate_predictions",
    "compute_stage_metrics",
    "residual_dataframe",
    "identify_outlier_predictions",
    "EvaluationReport",
    "StageMetrics",
]
