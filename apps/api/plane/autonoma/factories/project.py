# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Project-level factories.

``Project`` reproduces ``ProjectViewSet.create`` end to end: the serializer (which
validates the name/identifier and writes the ``ProjectIdentifier`` row), the
creator's admin ``ProjectMember``, a second admin membership for the project lead,
and the six ``DEFAULT_STATES``. When ``intake_view`` is on it also creates the
default ``Intake``, the way ``ProjectViewSet.partial_update`` does — ``IntakeIssue``
cannot exist without it.

Because the app creates the default states itself, the ``State`` factory adopts an
existing state with the same name rather than colliding with it: in Plane a second
"Backlog" in one project is impossible, so the default state *is* the scenario's
state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import jwt
from django.conf import settings
from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.api.serializers import LabelCreateUpdateSerializer
from plane.api.serializers import StateSerializer
from plane.app.serializers import ProjectSerializer
from plane.db.models import (
    DEFAULT_STATES,
    Intake,
    Label,
    Project,
    ProjectMember,
    ProjectMemberInvite,
    State,
)
from plane.db.models.project import ROLE

from ..support import acting_user, db_call, resolve_user


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    name: str
    identifier: str
    created_by_id: str
    description: str = ""
    network: int = 2
    project_lead_id: Optional[str] = None
    default_assignee_id: Optional[str] = None
    module_view: bool = True
    cycle_view: bool = True
    issue_views_view: bool = True
    page_view: bool = True
    intake_view: bool = False
    timezone: str = "UTC"


def _project_create(data: ProjectInput, ctx: Any) -> dict:
    creator = resolve_user(data.created_by_id)

    with acting_user(creator):
        serializer = ProjectSerializer(
            data={
                "name": data.name,
                "identifier": data.identifier,
                "description": data.description,
                "network": data.network,
                "project_lead": data.project_lead_id,
                "default_assignee": data.default_assignee_id,
                "module_view": data.module_view,
                "cycle_view": data.cycle_view,
                "issue_views_view": data.issue_views_view,
                "page_view": data.page_view,
                "intake_view": data.intake_view,
                "timezone": data.timezone,
            },
            context={"workspace_id": data.workspace_id},
        )
        serializer.is_valid(raise_exception=True)
        project = serializer.save()

        # The creator becomes a project admin.
        ProjectMember.objects.create(project=project, member=creator, role=ROLE.ADMIN.value)

        # ...and so does the lead, when it is somebody else.
        if data.project_lead_id and str(data.project_lead_id) != str(creator.id):
            ProjectMember.objects.create(
                project=project,
                member_id=data.project_lead_id,
                role=ROLE.ADMIN.value,
            )

        State.objects.bulk_create(
            [
                State(
                    name=state["name"],
                    color=state["color"],
                    project=project,
                    sequence=state["sequence"],
                    workspace=project.workspace,
                    group=state["group"],
                    default=state.get("default", False),
                    created_by=creator,
                )
                for state in DEFAULT_STATES
            ]
        )

        # ProjectViewSet.partial_update creates the default intake when the feature
        # is switched on; do the same so IntakeIssue has somewhere to live.
        if data.intake_view:
            Intake.objects.create(name=f"{project.name} Intake", project=project, is_default=True)

    return {
        "id": str(project.id),
        "workspace_id": str(project.workspace_id),
        "name": project.name,
        "identifier": project.identifier,
    }


def _project_teardown(record: dict, ctx: Any) -> None:
    Project.all_objects.filter(pk=record["id"]).delete()


Project_ = define_factory(
    create=db_call(_project_create),
    input_model=ProjectInput,
    teardown=db_call(_project_teardown),
)


class ProjectMemberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    member_id: str
    role: int = 15
    is_active: bool = True


def _member_create(data: ProjectMemberInput, ctx: Any) -> dict:
    member = resolve_user(data.member_id)

    with acting_user(member):
        # (project, member) is unique and project creation already enrolled the
        # creator and the lead, so adopt an existing membership when there is one.
        # ProjectMember.save creates the matching ProjectUserProperty row.
        membership, _ = ProjectMember.objects.update_or_create(
            project_id=data.project_id,
            member=member,
            defaults={"role": data.role, "is_active": data.is_active},
        )

    return {
        "id": str(membership.id),
        "project_id": str(membership.project_id),
        "workspace_id": str(membership.workspace_id),
        "member_id": str(membership.member_id),
        "role": membership.role,
    }


def _member_teardown(record: dict, ctx: Any) -> None:
    ProjectMember.all_objects.filter(pk=record["id"]).delete()


ProjectMember_ = define_factory(
    create=db_call(_member_create),
    input_model=ProjectMemberInput,
    teardown=db_call(_member_teardown),
)


class ProjectMemberInviteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    email: str
    role: int = 5
    accepted: bool = False
    created_by_id: Optional[str] = None


def _invite_create(data: ProjectMemberInviteInput, ctx: Any) -> dict:
    # ProjectInvitationsViewset.create builds this row inline before handing it to
    # an email task; the insert (including the signed invite token) is reproduced
    # here and the email side effect dropped.
    actor = resolve_user(data.created_by_id)
    project = Project.objects.get(pk=data.project_id)

    with acting_user(actor):
        invite = ProjectMemberInvite.objects.create(
            email=data.email.strip().lower(),
            project=project,
            workspace_id=project.workspace_id,
            token=jwt.encode(
                {"email": data.email, "timestamp": datetime.now().timestamp()},
                settings.SECRET_KEY,
                algorithm="HS256",
            ),
            role=data.role,
            accepted=data.accepted,
        )

    return {
        "id": str(invite.id),
        "project_id": str(invite.project_id),
        "workspace_id": str(invite.workspace_id),
        "email": invite.email,
    }


def _invite_teardown(record: dict, ctx: Any) -> None:
    ProjectMemberInvite.all_objects.filter(pk=record["id"]).delete()


ProjectMemberInvite_ = define_factory(
    create=db_call(_invite_create),
    input_model=ProjectMemberInviteInput,
    teardown=db_call(_invite_teardown),
)


class StateInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    group: str = "backlog"
    color: str = "#60646C"
    sequence: Optional[float] = None
    default: bool = False
    description: str = ""
    created_by_id: Optional[str] = None


def _state_create(data: StateInput, ctx: Any) -> dict:
    actor = resolve_user(data.created_by_id)

    with acting_user(actor):
        existing = State.all_state_objects.filter(
            project_id=data.project_id, name=data.name, deleted_at__isnull=True
        ).first()
        if existing is not None:
            # Created with the project as one of DEFAULT_STATES. (name, project) is
            # unique, so this row is the scenario's state.
            return {
                "id": str(existing.id),
                "project_id": str(existing.project_id),
                "workspace_id": str(existing.workspace_id),
                "name": existing.name,
                "group": existing.group,
                "adopted": True,
            }

        if data.group == "triage":
            # StateSerializer refuses to create triage states; the app writes them
            # inline (ProjectViewSet.create, IntakeIssueViewSet.create), so do the
            # same here.
            state = State(
                project_id=data.project_id,
                name=data.name,
                group=data.group,
                color=data.color,
                default=data.default,
                description=data.description,
                is_triage=True,
            )
            if data.sequence is not None:
                state.sequence = data.sequence
            state.save()
        else:
            serializer = StateSerializer(
                data={
                    "name": data.name,
                    "group": data.group,
                    "color": data.color,
                    "default": data.default,
                    "description": data.description,
                    **({"sequence": data.sequence} if data.sequence is not None else {}),
                },
                context={"project_id": data.project_id},
            )
            serializer.is_valid(raise_exception=True)
            state = serializer.save(project_id=data.project_id)

    return {
        "id": str(state.id),
        "project_id": str(state.project_id),
        "workspace_id": str(state.workspace_id),
        "name": state.name,
        "group": state.group,
        "adopted": False,
    }


def _state_teardown(record: dict, ctx: Any) -> None:
    # An adopted default state belongs to the project and goes away with it.
    if record.get("adopted"):
        return
    State.all_state_objects.filter(pk=record["id"]).delete()


State_ = define_factory(
    create=db_call(_state_create),
    input_model=StateInput,
    teardown=db_call(_state_teardown),
)


class LabelInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    color: str = "#60646C"
    description: str = ""
    created_by_id: Optional[str] = None


def _label_create(data: LabelInput, ctx: Any) -> dict:
    # LabelListCreateAPIEndpoint.post saves through LabelCreateUpdateSerializer with
    # project_id. Label inherits ProjectBaseModel, whose save() fills the workspace
    # in from the project.
    actor = resolve_user(data.created_by_id)

    with acting_user(actor):
        serializer = LabelCreateUpdateSerializer(
            data={"name": data.name, "color": data.color, "description": data.description}
        )
        serializer.is_valid(raise_exception=True)
        label = serializer.save(project_id=data.project_id)

    return {
        "id": str(label.id),
        "project_id": str(label.project_id),
        "workspace_id": str(label.workspace_id),
        "name": label.name,
    }


def _label_teardown(record: dict, ctx: Any) -> None:
    Label.all_objects.filter(pk=record["id"]).delete()


Label_ = define_factory(
    create=db_call(_label_create),
    input_model=LabelInput,
    teardown=db_call(_label_teardown),
)
