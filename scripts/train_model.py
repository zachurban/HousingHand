#!/usr/bin/env python3
"""Train the timeline prediction ML model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from config.settings import get_settings
from src.database.connection import get_session_factory
from src.ml.model_training import TrainingPipeline
from src.models.enums import PipelineStage
from src.models.project import Project

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the model training pipeline."""
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        # Fetch completed projects for training
        completed_stages = [PipelineStage.OPERATIONS, PipelineStage.LEASE_UP]
        projects = (
            db.query(Project)
            .filter(Project.current_stage.in_(completed_stages))
            .all()
        )

        logger.info(f"Found {len(projects)} completed projects for training")

        if len(projects) < 10:
            logger.warning(
                "Fewer than 10 completed projects available. "
                "Model quality may be limited. Proceeding anyway."
            )

        pipeline = TrainingPipeline()
        result = pipeline.train(projects)

        # Save model
        model_path = Path(settings.ml_model_path)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline.save_model(str(model_path))

        logger.info(f"Model saved to {model_path}")
        logger.info(f"Training results: {result}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
