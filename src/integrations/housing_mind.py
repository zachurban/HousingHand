"""Webhook handler for HousingMind query metadata integration."""

import hashlib
import hmac
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from config.settings import get_settings
from src.models.project import Project

logger = logging.getLogger(__name__)


@dataclass
class QueryEvent:
    """A query event from HousingMind about a project or jurisdiction."""

    project_id: str | None
    jurisdiction: str
    query_category: str
    query_text: str
    timestamp: str
    user_type: str = ""


class HousingMindWebhookHandler:
    """Handles incoming webhooks from HousingMind to track query patterns."""

    def __init__(self, webhook_secret: str | None = None):
        settings = get_settings()
        self.webhook_secret = webhook_secret or settings.housing_mind_webhook_secret

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the webhook signature using HMAC-SHA256."""
        if not self.webhook_secret:
            logger.warning("No webhook secret configured; skipping verification")
            return True

        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected}", signature)

    def parse_event(self, payload: dict) -> QueryEvent:
        """Parse a webhook payload into a QueryEvent."""
        return QueryEvent(
            project_id=payload.get("project_id"),
            jurisdiction=payload.get("jurisdiction", ""),
            query_category=payload.get("query_category", "general"),
            query_text=payload.get("query_text", ""),
            timestamp=payload.get("timestamp", ""),
            user_type=payload.get("user_type", ""),
        )

    def process_event(self, db: Session, event: QueryEvent) -> None:
        """Process a query event by updating project query metrics."""
        if not event.project_id:
            return

        project = db.get(Project, event.project_id)
        if project is None:
            logger.info(f"Query event for unknown project: {event.project_id}")
            return

        # Increment query counter
        project.housing_mind_queries = (project.housing_mind_queries or 0) + 1

        # Update top query categories
        categories = project.top_query_categories or {}
        categories[event.query_category] = categories.get(event.query_category, 0) + 1
        project.top_query_categories = categories

        db.commit()
        logger.info(
            f"Updated query metrics for project {project.project_slug}: "
            f"total={project.housing_mind_queries}"
        )
