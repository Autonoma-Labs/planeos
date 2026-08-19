# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Workspace-level factories.

``Workspace`` runs the same two steps ``WorkSpaceViewSet.create`` does: save
through ``WorkSpaceSerializer`` (which enforces the slug and name rules) and add
the owner as an admin ``WorkspaceMember``.

The view also dispatches ``workspace_seed`` — a Celery task that fills a brand new
workspace with a demo project, issues, cycles and modules. That task is
deliberately not dispatched here: the scenario fixes exactly which projects and
issues exist, and a demo project would contradict it. See IMPLEMENTATION.md.

Teardown goes through ``all_objects`` — the plain manager that bypasses Plane's
soft-delete manager — so the row is really removed and Postgres cascades every
workspace-scoped row away with it, including anything a test created that was
never part of ``up``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import jwt
from django.conf import settings
from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.app.serializers import WorkSpaceSerializer
from plane.db.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberInvite,
    WorkspaceUserProperties,
)

from ..support import acting_user, db_call, resolve_user


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    slug: str
    owner_id: str
    organization_size: Optional[str] = None
    timezone: str = "UTC"


def _workspace_create(data: WorkspaceInput, ctx: Any) -> dict:
    owner = resolve_user(data.owner_id)

    with acting_user(owner):
        serializer = WorkSpaceSerializer(
            data={
                "name": data.name,
                "slug": data.slug,
                "organization_size": data.organization_size,
                "timezone": data.timezone,
            }
        )
        serializer.is_valid(raise_exception=True)
        workspace = serializer.save(owner=owner)

        # WorkSpaceViewSet.create adds the creator as an Admin member.
        WorkspaceMember.objects.create(workspace=workspace, member=owner, role=20, company_role="")

    return {
        "id": str(workspace.id),
        "slug": workspace.slug,
        "name": workspace.name,
        "workspace_id": str(workspace.id),
        "owner_id": str(workspace.owner_id),
    }


def _workspace_teardown(record: dict, ctx: Any) -> None:
    # all_objects is the plain manager, so this is a real delete rather than a
    # soft one, and the database cascade removes every workspace-scoped row.
    Workspace.all_objects.filter(pk=record["id"]).delete()


Workspace_ = define_factory(
    create=db_call(_workspace_create),
    input_model=WorkspaceInput,
    teardown=db_call(_workspace_teardown),
)


class WorkspaceMemberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    member_id: str
    role: int = 5
    company_role: Optional[str] = ""


def _member_create(data: WorkspaceMemberInput, ctx: Any) -> dict:
    member = resolve_user(data.member_id)

    with acting_user(member):
        # The workspace owner already holds an admin membership created alongside
        # the workspace, and (workspace, member) is unique — so adopt the existing
        # row instead of colliding with it.
        membership, _ = WorkspaceMember.objects.update_or_create(
            workspace_id=data.workspace_id,
            member=member,
            defaults={"role": data.role, "company_role": data.company_role or "", "is_active": True},
        )

    return {
        "id": str(membership.id),
        "workspace_id": str(membership.workspace_id),
        "member_id": str(membership.member_id),
        "role": membership.role,
    }


def _member_teardown(record: dict, ctx: Any) -> None:
    WorkspaceMember.all_objects.filter(pk=record["id"]).delete()


WorkspaceMember_ = define_factory(
    create=db_call(_member_create),
    input_model=WorkspaceMemberInput,
    teardown=db_call(_member_teardown),
)


class WorkspaceMemberInviteInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    email: str
    role: int = 5
    accepted: bool = False
    created_by_id: Optional[str] = None
    message: Optional[str] = None


def _invite_create(data: WorkspaceMemberInviteInput, ctx: Any) -> dict:
    # WorkspaceInvitationsViewset.create builds the row inline and then hands it to
    # an email task. The insert is copied here verbatim, including the signed token
    # the accept-invite link carries; the email side effect is dropped.
    actor = resolve_user(data.created_by_id)

    with acting_user(actor):
        invite = WorkspaceMemberInvite.objects.create(
            email=data.email.strip().lower(),
            workspace_id=data.workspace_id,
            token=jwt.encode(
                {"email": data.email, "timestamp": datetime.now().timestamp()},
                settings.SECRET_KEY,
                algorithm="HS256",
            ),
            role=data.role,
            accepted=data.accepted,
            message=data.message,
        )

    return {
        "id": str(invite.id),
        "workspace_id": str(invite.workspace_id),
        "email": invite.email,
        "token": invite.token,
    }


def _invite_teardown(record: dict, ctx: Any) -> None:
    WorkspaceMemberInvite.all_objects.filter(pk=record["id"]).delete()


WorkspaceMemberInvite_ = define_factory(
    create=db_call(_invite_create),
    input_model=WorkspaceMemberInviteInput,
    teardown=db_call(_invite_teardown),
)


class WorkspaceUserPropertiesInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    user_id: str
    filters: Optional[dict] = None
    display_filters: Optional[dict] = None
    display_properties: Optional[dict] = None


def _properties_create(data: WorkspaceUserPropertiesInput, ctx: Any) -> dict:
    # WorkspaceUserPropertiesEndpoint get_or_creates the row and then patches the
    # filters onto it; same two steps here.
    user = resolve_user(data.user_id)

    with acting_user(user):
        properties, _ = WorkspaceUserProperties.objects.get_or_create(workspace_id=data.workspace_id, user=user)

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
        "workspace_id": str(properties.workspace_id),
        "user_id": str(properties.user_id),
    }


def _properties_teardown(record: dict, ctx: Any) -> None:
    WorkspaceUserProperties.all_objects.filter(pk=record["id"]).delete()


WorkspaceUserProperties_ = define_factory(
    create=db_call(_properties_create),
    input_model=WorkspaceUserPropertiesInput,
    teardown=db_call(_properties_teardown),
)
