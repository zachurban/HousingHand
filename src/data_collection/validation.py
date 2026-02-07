"""Data quality validation for project records."""

import logging
from dataclasses import dataclass, field
from datetime import date

from src.models.project import Project

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a project record."""

    is_valid: bool
    quality_score: float  # 0.0 to 1.0
    completeness_score: float  # 0.0 to 1.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DataValidator:
    """Validates project data quality and completeness."""

    # Fields that should always be present
    REQUIRED_FIELDS = [
        "project_name",
        "total_units",
        "current_stage",
    ]

    # Fields important for analytics
    ANALYTICS_FIELDS = [
        "city",
        "state",
        "jurisdiction",
        "affordable_units",
        "building_type",
        "developer_org",
        "concept_start",
    ]

    # Fields needed for cost analytics
    COST_FIELDS = [
        "total_development_cost",
        "hard_costs",
        "soft_costs",
        "land_acquisition_cost",
    ]

    def validate_project(self, project: Project) -> ValidationResult:
        """Run all validation checks on a project."""
        errors: list[str] = []
        warnings: list[str] = []

        # Required field checks
        for field_name in self.REQUIRED_FIELDS:
            value = getattr(project, field_name, None)
            if value is None or value == "":
                errors.append(f"Missing required field: {field_name}")

        # Unit counts consistency
        if project.total_units is not None and project.total_units < 0:
            errors.append("total_units cannot be negative")

        if project.affordable_units is not None and project.total_units is not None:
            if project.affordable_units > project.total_units:
                errors.append("affordable_units exceeds total_units")

        # Unit mix should add up
        unit_mix_sum = sum([
            project.studio_units or 0,
            project.one_br_units or 0,
            project.two_br_units or 0,
            project.three_br_units or 0,
            project.four_plus_br_units or 0,
        ])
        if unit_mix_sum > 0 and project.total_units and unit_mix_sum != project.total_units:
            warnings.append(
                f"Unit mix sum ({unit_mix_sum}) does not match "
                f"total_units ({project.total_units})"
            )

        # AMI mix should not exceed affordable units
        ami_sum = sum([
            project.ami_30_units or 0,
            project.ami_40_units or 0,
            project.ami_50_units or 0,
            project.ami_60_units or 0,
            project.ami_80_units or 0,
        ])
        if ami_sum > 0 and project.affordable_units and ami_sum > project.affordable_units:
            warnings.append(
                f"AMI unit sum ({ami_sum}) exceeds "
                f"affordable_units ({project.affordable_units})"
            )

        # Timeline consistency
        self._validate_timeline(project, errors, warnings)

        # Cost consistency
        self._validate_costs(project, warnings)

        # Calculate scores
        completeness = self._calculate_completeness(project)
        quality = 1.0 if not errors else max(0.0, 1.0 - (len(errors) * 0.2))

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            quality_score=quality,
            completeness_score=completeness,
            errors=errors,
            warnings=warnings,
        )

    def _validate_timeline(
        self,
        project: Project,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Validate timeline date consistency."""
        stages = [
            ("concept", project.concept_start, project.concept_complete),
            ("pre_development", project.pre_development_start, project.pre_development_complete),
            ("entitlement", project.entitlement_start, project.entitlement_complete),
            ("financing", project.financing_start, project.financing_complete),
            ("construction", project.construction_start, project.construction_complete),
            ("lease_up", project.lease_up_start, project.lease_up_complete),
        ]

        prev_end: date | None = None
        for stage_name, start, end in stages:
            if start and end:
                if end < start:
                    errors.append(
                        f"{stage_name} end date ({end}) is before "
                        f"start date ({start})"
                    )
            if start and prev_end and start < prev_end:
                warnings.append(
                    f"{stage_name} start ({start}) overlaps with "
                    f"previous stage end ({prev_end})"
                )
            if end:
                prev_end = end

    def _validate_costs(self, project: Project, warnings: list[str]) -> None:
        """Validate cost data consistency."""
        if project.total_development_cost and project.total_units:
            cpu = project.total_development_cost / project.total_units
            if cpu < 50_000:
                warnings.append(
                    f"Cost per unit ({cpu:,.0f}) seems unusually low"
                )
            if cpu > 1_000_000:
                warnings.append(
                    f"Cost per unit ({cpu:,.0f}) seems unusually high"
                )

        if project.hard_costs and project.soft_costs and project.total_development_cost:
            component_sum = (
                (project.hard_costs or 0)
                + (project.soft_costs or 0)
                + (project.land_acquisition_cost or 0)
                + (project.financing_costs or 0)
                + (project.developer_fee or 0)
                + (project.reserves or 0)
            )
            if component_sum > 0:
                diff_pct = abs(component_sum - project.total_development_cost) / project.total_development_cost * 100
                if diff_pct > 10:
                    warnings.append(
                        f"Cost components sum ({component_sum:,.0f}) differs from "
                        f"total ({project.total_development_cost:,.0f}) by {diff_pct:.1f}%"
                    )

    def _calculate_completeness(self, project: Project) -> float:
        """Calculate what fraction of important fields are populated."""
        all_fields = self.REQUIRED_FIELDS + self.ANALYTICS_FIELDS + self.COST_FIELDS
        filled = 0
        for field_name in all_fields:
            value = getattr(project, field_name, None)
            if value is not None and value != "" and value != 0:
                filled += 1
        return round(filled / len(all_fields), 2)
