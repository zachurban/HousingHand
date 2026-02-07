"""HousingMind ecosystem webhook handler.

Receives inbound webhook events from sibling services (HousingLens,
HousingEar, HousingMind orchestrator) and processes them asynchronously.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from src.api.dependencies import get_db
from src.models.enums import OverallHealth, PipelineStage
from src.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class WebhookEventType(str, Enum):
    """Known event types dispatched by the HousingMind ecosystem."""

    FRICTION_SCORE_UPDATED = "friction_score_updated"
    HEARING_DETECTED = "hearing_detected"
    POLICY_CHANGE_DETECTED = "policy_change_detected"
    PROJECT_STAGE_INFERRED = "project_stage_inferred"
    FUNDING_ALERT = "funding_alert"
    RISK_ASSESSMENT_UPDATED = "risk_assessment_updated"
    QUERY_VOLUME_SPIKE = "query_volume_spike"


class WebhookPayload(BaseModel):
    """Inbound webhook payload from any HousingMind service."""

    event_type: WebhookEventType = Field(
        ..., description="The type of event being reported"
    )
    source_service: str = Field(
        ..., description="Originating service name (e.g. 'housing_lens')"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the event",
    )
    project_id: UUID | None = Field(
        None, description="Associated project ID, if applicable"
    )
    jurisdiction: str | None = Field(
        None, description="Jurisdiction the event pertains to"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload data",
    )

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "event_type": "friction_score_updated",
                "source_service": "housing_lens",
                "project_id": "b1e4a7c0-1234-5678-abcd-ef0123456789",
                "jurisdiction": "San Francisco, CA",
                "data": {
                    "new_friction_score": 72,
                    "previous_friction_score": 65,
                    "contributing_factors": ["parking_minimum", "design_review"],
                },
            }
        ]
    }}


class WebhookResponse(BaseModel):
    """Acknowledgement returned to the calling service."""

    accepted: bool = True
    message: str = "Event received and queued for processing"
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(
    body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    """Verify HMAC-SHA256 webhook signature.

    Raises ``HTTPException(403)`` when the signature is missing or invalid.
    """
    if not secret:
        # Secret not configured -- skip verification (dev / test mode).
        return
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Webhook-Signature header",
        )
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _handle_friction_score_updated(
    db: Session, payload: WebhookPayload
) -> None:
    """Update a project's jurisdiction friction score from HousingLens."""
    if payload.project_id is None:
        logger.warning("friction_score_updated event missing project_id")
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        logger.warning(
            "friction_score_updated: project %s not found", payload.project_id
        )
        return

    new_score = payload.data.get("new_friction_score")
    if new_score is not None:
        project.jurisdiction_friction_score = int(new_score)

    friction_points = payload.data.get("contributing_factors")
    if friction_points is not None:
        project.primary_friction_points = {"factors": friction_points}

    project.updated_at = datetime.utcnow()
    db.commit()
    logger.info(
        "Updated friction score for project %s to %s",
        payload.project_id,
        new_score,
    )


def _handle_hearing_detected(
    db: Session, payload: WebhookPayload
) -> None:
    """Record a newly detected public hearing from HousingEar."""
    if payload.project_id is None:
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        return

    project.public_meetings_attended = (project.public_meetings_attended or 0) + 1

    hearing_type = payload.data.get("hearing_type", "")
    if hearing_type == "variance":
        project.variance_hearings = (project.variance_hearings or 0) + 1
    if hearing_type == "design_review":
        project.design_review_iterations = (
            project.design_review_iterations or 0
        ) + 1

    project.updated_at = datetime.utcnow()
    db.commit()
    logger.info(
        "Recorded hearing for project %s (type=%s)",
        payload.project_id,
        hearing_type,
    )


def _handle_project_stage_inferred(
    db: Session, payload: WebhookPayload
) -> None:
    """Update project stage based on HousingMind ML inference."""
    if payload.project_id is None:
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        return

    inferred_stage = payload.data.get("inferred_stage")
    confidence = payload.data.get("confidence")

    if inferred_stage is not None:
        try:
            new_stage = PipelineStage(inferred_stage)
        except ValueError:
            logger.warning("Invalid inferred stage: %s", inferred_stage)
            return

        project.current_stage = new_stage
        if confidence is not None:
            project.prediction_confidence = float(confidence)
        project.prediction_last_updated = datetime.utcnow()
        project.updated_at = datetime.utcnow()
        db.commit()
        logger.info(
            "Inferred stage for project %s -> %s (confidence=%.2f)",
            payload.project_id,
            new_stage.value,
            confidence or 0,
        )


def _handle_risk_assessment_updated(
    db: Session, payload: WebhookPayload
) -> None:
    """Update risk score and overall health from a fresh assessment."""
    if payload.project_id is None:
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        return

    risk_score = payload.data.get("risk_score")
    risk_factors = payload.data.get("risk_factors")
    overall_health = payload.data.get("overall_health")

    if risk_score is not None:
        project.risk_score = float(risk_score)
    if risk_factors is not None:
        project.risk_factors = risk_factors
    if overall_health is not None:
        try:
            project.overall_health = OverallHealth(overall_health)
        except ValueError:
            logger.warning("Invalid overall_health value: %s", overall_health)

    health_score = payload.data.get("health_score")
    if health_score is not None:
        project.health_score = float(health_score)

    project.updated_at = datetime.utcnow()
    db.commit()
    logger.info(
        "Updated risk assessment for project %s (score=%.2f)",
        payload.project_id,
        risk_score or 0,
    )


def _handle_funding_alert(
    db: Session, payload: WebhookPayload
) -> None:
    """Process a funding-related alert (gap warning, new opportunity, etc.)."""
    if payload.project_id is None:
        logger.info(
            "Funding alert for jurisdiction %s: %s",
            payload.jurisdiction,
            payload.data.get("alert_message", ""),
        )
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        return

    new_gap = payload.data.get("funding_gap")
    if new_gap is not None:
        project.funding_gap = float(new_gap)

    project.updated_at = datetime.utcnow()
    db.commit()
    logger.info("Processed funding alert for project %s", payload.project_id)


def _handle_query_volume_spike(
    db: Session, payload: WebhookPayload
) -> None:
    """Record an unusual spike in HousingMind queries about a project."""
    if payload.project_id is None:
        return

    project = db.get(Project, payload.project_id)
    if project is None:
        return

    additional_queries = payload.data.get("query_count", 0)
    project.housing_mind_queries = (
        project.housing_mind_queries or 0
    ) + int(additional_queries)

    categories = payload.data.get("top_categories")
    if categories is not None:
        project.top_query_categories = {"categories": categories}

    project.updated_at = datetime.utcnow()
    db.commit()
    logger.info(
        "Recorded query spike for project %s (+%d queries)",
        payload.project_id,
        additional_queries,
    )


_EVENT_HANDLERS: dict[WebhookEventType, Any] = {
    WebhookEventType.FRICTION_SCORE_UPDATED: _handle_friction_score_updated,
    WebhookEventType.HEARING_DETECTED: _handle_hearing_detected,
    WebhookEventType.PROJECT_STAGE_INFERRED: _handle_project_stage_inferred,
    WebhookEventType.RISK_ASSESSMENT_UPDATED: _handle_risk_assessment_updated,
    WebhookEventType.FUNDING_ALERT: _handle_funding_alert,
    WebhookEventType.QUERY_VOLUME_SPIKE: _handle_query_volume_spike,
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/housingmind",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive HousingMind ecosystem events",
)
async def receive_housingmind_webhook(
    request: Request,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_webhook_signature: str | None = Header(None),
) -> WebhookResponse:
    """Receive and process webhook events from HousingMind ecosystem services.

    Supported event types:

    * **friction_score_updated** -- HousingLens recalculated a jurisdiction's
      friction score relevant to a tracked project.
    * **hearing_detected** -- HousingEar detected a public hearing that
      pertains to a tracked project.
    * **policy_change_detected** -- A policy or zoning reform was detected.
    * **project_stage_inferred** -- ML model inferred a project moved to a
      new pipeline stage.
    * **funding_alert** -- A funding gap warning or new opportunity alert.
    * **risk_assessment_updated** -- Fresh risk scoring for a project.
    * **query_volume_spike** -- Unusual spike in HousingMind queries about a
      project.

    The endpoint validates the ``X-Webhook-Signature`` header (HMAC-SHA256)
    when the ``housing_mind_webhook_secret`` setting is configured.
    """
    body = await request.body()
    _verify_signature(body, x_webhook_signature, settings.housing_mind_webhook_secret)

    handler = _EVENT_HANDLERS.get(payload.event_type)
    if handler is not None:
        try:
            handler(db, payload)
        except Exception:
            logger.exception(
                "Error processing webhook event %s", payload.event_type
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error processing webhook event",
            )
    else:
        logger.info(
            "No handler registered for event type %s -- acknowledged but not processed",
            payload.event_type,
        )

    return WebhookResponse(
        event_type=payload.event_type.value,
    )
