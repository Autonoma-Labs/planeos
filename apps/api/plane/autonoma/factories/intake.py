# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Intake factory.

``IntakeIssueViewSet.create`` creates the underlying work item in the project's
triage state through ``IssueCreateSerializer`` and then links it to the project's
default ``Intake``. Both steps happen here; the intake row itself is created with
the project (see ``project.py``).

``snoozed_till`` is compared against the clock when the intake list separates
snoozed items from open ones, so it is supplied as a day offset.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.app.serializers import IssueCreateSerializer
from plane.db.models import Intake, IntakeIssue, Project, State, StateGroup
from plane.db.models.intake import SourceType

from ..support import acting_user, db_call, offset_datetime, resolve_user


class IntakeIssueInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    created_by_id: str
    description_html: str = "<p></p>"
    priority: str = "none"
    # -2 pending, -1 rejected, 0 snoozed, 1 accepted, 2 duplicate
    status: int = -2
    source: str = SourceType.IN_APP
    source_email: Optional[str] = None
    snoozed_in_days: Optional[float] = None


def _create(data: IntakeIssueInput, ctx: Any) -> dict:
    creator = resolve_user(data.created_by_id)
    project = Project.objects.get(pk=data.project_id)

    with acting_user(creator):
        triage_state = State.triage_objects.filter(project_id=project.id).first()
        if triage_state is None:
            triage_state = State.objects.create(
                name="Triage",
                group=StateGroup.TRIAGE.value,
                project_id=project.id,
                workspace_id=project.workspace_id,
                color="#4E5355",
                sequence=65000,
                default=False,
            )

        intake = Intake.objects.filter(project_id=project.id).first()
        if intake is None:
            raise RuntimeError(f'project "{project.name}" has no intake; set intake_view on the project record')

        serializer = IssueCreateSerializer(
            data={
                "name": data.name,
                "priority": data.priority,
                "description_html": data.description_html,
                "state_id": str(triage_state.id),
            },
            context={
                "project_id": str(project.id),
                "workspace_id": str(project.workspace_id),
                "default_assignee_id": project.default_assignee_id,
                "allow_triage_state": True,
            },
        )
        serializer.is_valid(raise_exception=True)
        issue = serializer.save()

        intake_issue = IntakeIssue.objects.create(
            intake_id=intake.id,
            project_id=project.id,
            issue_id=issue.id,
            status=data.status,
            source=data.source,
            source_email=data.source_email,
            snoozed_till=offset_datetime(days=data.snoozed_in_days),
        )

    return {
        "id": str(intake_issue.id),
        "intake_id": str(intake_issue.intake_id),
        "issue_id": str(intake_issue.issue_id),
        "project_id": str(intake_issue.project_id),
        "workspace_id": str(intake_issue.workspace_id),
        "name": issue.name,
    }


def _teardown(record: dict, ctx: Any) -> None:
    from plane.db.models import Issue

    IntakeIssue.all_objects.filter(pk=record["id"]).delete()
    # The work item behind the intake entry is created by this factory, so it is
    # this factory's job to remove it.
    Issue.all_objects.filter(pk=record["issue_id"]).delete()


IntakeIssue_ = define_factory(
    create=db_call(_create),
    input_model=IntakeIssueInput,
    teardown=db_call(_teardown),
)
