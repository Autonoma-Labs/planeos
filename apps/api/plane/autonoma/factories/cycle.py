# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Cycle factories.

A cycle's status is *derived from the clock*: ``CycleViewSet.get_queryset``
annotates CURRENT / UPCOMING / COMPLETED from
``start_date <= now <= end_date`` / ``start_date > now`` / ``end_date < now``, the
"active cycle" filter selects on the same comparison, and
``CycleIssueViewSet.create`` refuses to add issues once ``end_date < now``. So the
recipe carries day offsets, never instants, and this factory adds them to the
current time — a stored date would silently move a sprint from active to completed
a week after the recipe was written.

Cycles are created through ``CycleCreateSerializer``, which converts the dates into
the project's timezone the way the API endpoint does.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.api.serializers import CycleCreateSerializer
from plane.db.models import Cycle, CycleIssue, CycleUserProperties, Issue, Project

from ..support import acting_user, db_call, offset_datetime, resolve_user


class CycleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    owned_by_id: str
    description: str = ""
    # Offsets in days from the moment of seeding. Negative values are in the past.
    starts_in_days: Optional[float] = None
    ends_in_days: Optional[float] = None


def _cycle_create(data: CycleInput, ctx: Any) -> dict:
    owner = resolve_user(data.owned_by_id)
    project = Project.objects.get(pk=data.project_id)

    start_date = offset_datetime(days=data.starts_in_days)
    end_date = offset_datetime(days=data.ends_in_days)

    payload: dict[str, Any] = {
        "name": data.name,
        "description": data.description,
        "owned_by": str(owner.id),
    }
    # The endpoint requires both dates or neither.
    if start_date and end_date:
        payload["start_date"] = start_date.isoformat()
        payload["end_date"] = end_date.isoformat()

    with acting_user(owner):
        serializer = CycleCreateSerializer(data=payload, context={"project_id": str(project.id), "project": project})
        serializer.is_valid(raise_exception=True)
        cycle = serializer.save(project_id=project.id)

    return {
        "id": str(cycle.id),
        "project_id": str(cycle.project_id),
        "workspace_id": str(cycle.workspace_id),
        "name": cycle.name,
        "start_date": cycle.start_date.isoformat() if cycle.start_date else None,
        "end_date": cycle.end_date.isoformat() if cycle.end_date else None,
    }


def _cycle_teardown(record: dict, ctx: Any) -> None:
    Cycle.all_objects.filter(pk=record["id"]).delete()


Cycle_ = define_factory(
    create=db_call(_cycle_create),
    input_model=CycleInput,
    teardown=db_call(_cycle_teardown),
)


class CycleIssueInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cycle_id: str
    issue_id: str
    created_by_id: Optional[str] = None


def _cycle_issue_create(data: CycleIssueInput, ctx: Any) -> dict:
    # CycleIssueViewSet.create builds these rows inline with bulk_create after
    # checking the cycle has not already ended; that check is kept so a recipe that
    # attaches an issue to a finished sprint fails loudly instead of seeding a state
    # the UI cannot produce.
    actor = resolve_user(data.created_by_id)
    cycle = Cycle.objects.get(pk=data.cycle_id)
    issue = Issue.objects.get(pk=data.issue_id)

    from django.utils import timezone

    if cycle.end_date is not None and cycle.end_date < timezone.now():
        raise ValueError(f'cycle "{cycle.name}" has already ended, so no issues can be added to it')

    with acting_user(actor):
        cycle_issue = CycleIssue.objects.create(
            cycle_id=cycle.id,
            issue_id=issue.id,
            project_id=cycle.project_id,
            workspace_id=cycle.workspace_id,
        )

    return {
        "id": str(cycle_issue.id),
        "cycle_id": str(cycle_issue.cycle_id),
        "issue_id": str(cycle_issue.issue_id),
        "project_id": str(cycle_issue.project_id),
        "workspace_id": str(cycle_issue.workspace_id),
    }


def _cycle_issue_teardown(record: dict, ctx: Any) -> None:
    CycleIssue.all_objects.filter(pk=record["id"]).delete()


CycleIssue_ = define_factory(
    create=db_call(_cycle_issue_create),
    input_model=CycleIssueInput,
    teardown=db_call(_cycle_issue_teardown),
)


class CycleUserPropertiesInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cycle_id: str
    user_id: str
    filters: Optional[dict] = None
    display_filters: Optional[dict] = None
    display_properties: Optional[dict] = None


def _properties_create(data: CycleUserPropertiesInput, ctx: Any) -> dict:
    # CycleUserPropertiesEndpoint.get creates the row with get_or_create and .patch
    # writes the filters onto it; both steps here.
    user = resolve_user(data.user_id)
    cycle = Cycle.objects.get(pk=data.cycle_id)

    with acting_user(user):
        properties, _ = CycleUserProperties.objects.get_or_create(
            user=user, cycle_id=cycle.id, project_id=cycle.project_id
        )

        changed = []
        for field in ("filters", "display_filters", "display_properties"):
            value = getattr(data, field)
            if value is not None:
                setattr(properties, field, value)
                changed.append(field)
        if changed:
            properties.save(update_fields=changed)

    return {
        "id": str(properties.id),
        "cycle_id": str(properties.cycle_id),
        "user_id": str(properties.user_id),
        "project_id": str(properties.project_id),
        "workspace_id": str(properties.workspace_id),
    }


def _properties_teardown(record: dict, ctx: Any) -> None:
    CycleUserProperties.all_objects.filter(pk=record["id"]).delete()


CycleUserProperties_ = define_factory(
    create=db_call(_properties_create),
    input_model=CycleUserPropertiesInput,
    teardown=db_call(_properties_teardown),
)
