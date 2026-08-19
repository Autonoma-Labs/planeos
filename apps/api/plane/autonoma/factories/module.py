# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Module factories.

``Module`` goes through ``ModuleWriteSerializer``, which rejects a duplicate name in
the project and creates the ``ModuleMember`` rows for ``member_ids``.

A module's status is an explicit column rather than something derived from the
clock, but its burn-down chart is drawn across ``start_date``..``target_date``, so
the dates are still supplied as day offsets: an "in progress" module whose window
sits entirely in the past would render as finished work.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.api.serializers.module import ModuleLinkSerializer
from plane.app.serializers import ModuleWriteSerializer
from plane.db.models import Issue, Module, ModuleIssue, ModuleLink, ModuleUserProperties, Project

from ..support import acting_user, db_call, offset_date, resolve_user


class ModuleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    created_by_id: str
    description: str = ""
    status: str = "backlog"
    lead_id: Optional[str] = None
    member_ids: list[str] = []
    # Offsets in days from the moment of seeding.
    starts_in_days: Optional[float] = None
    target_in_days: Optional[float] = None


def _module_create(data: ModuleInput, ctx: Any) -> dict:
    creator = resolve_user(data.created_by_id)
    project = Project.objects.get(pk=data.project_id)

    payload: dict[str, Any] = {
        "name": data.name,
        "description": data.description,
        "status": data.status,
    }
    if data.lead_id:
        payload["lead_id"] = data.lead_id
    if data.member_ids:
        payload["member_ids"] = data.member_ids

    start_date = offset_date(data.starts_in_days)
    target_date = offset_date(data.target_in_days)
    if start_date:
        payload["start_date"] = start_date.isoformat()
    if target_date:
        payload["target_date"] = target_date.isoformat()

    with acting_user(creator):
        serializer = ModuleWriteSerializer(data=payload, context={"project": project})
        serializer.is_valid(raise_exception=True)
        module = serializer.save()

    return {
        "id": str(module.id),
        "project_id": str(module.project_id),
        "workspace_id": str(module.workspace_id),
        "name": module.name,
        "start_date": start_date.isoformat() if start_date else None,
        "target_date": target_date.isoformat() if target_date else None,
    }


def _module_teardown(record: dict, ctx: Any) -> None:
    Module.all_objects.filter(pk=record["id"]).delete()


Module_ = define_factory(
    create=db_call(_module_create),
    input_model=ModuleInput,
    teardown=db_call(_module_teardown),
)


class ModuleIssueInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    module_id: str
    issue_id: str
    created_by_id: Optional[str] = None


def _module_issue_create(data: ModuleIssueInput, ctx: Any) -> dict:
    # ModuleIssueViewSet.create_module_issues writes these rows inline with
    # bulk_create; reproduced here without the activity task.
    actor = resolve_user(data.created_by_id)
    module = Module.objects.get(pk=data.module_id)
    issue = Issue.objects.get(pk=data.issue_id)

    with acting_user(actor):
        module_issue = ModuleIssue.objects.create(
            module_id=module.id,
            issue_id=issue.id,
            project_id=module.project_id,
            workspace_id=module.workspace_id,
        )

    return {
        "id": str(module_issue.id),
        "module_id": str(module_issue.module_id),
        "issue_id": str(module_issue.issue_id),
        "project_id": str(module_issue.project_id),
        "workspace_id": str(module_issue.workspace_id),
    }


def _module_issue_teardown(record: dict, ctx: Any) -> None:
    ModuleIssue.all_objects.filter(pk=record["id"]).delete()


ModuleIssue_ = define_factory(
    create=db_call(_module_issue_create),
    input_model=ModuleIssueInput,
    teardown=db_call(_module_issue_teardown),
)


class ModuleLinkInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    module_id: str
    url: str
    title: Optional[str] = None
    created_by_id: Optional[str] = None


def _module_link_create(data: ModuleLinkInput, ctx: Any) -> dict:
    actor = resolve_user(data.created_by_id)
    module = Module.objects.get(pk=data.module_id)

    with acting_user(actor):
        serializer = ModuleLinkSerializer(data={"url": data.url, "title": data.title})
        serializer.is_valid(raise_exception=True)
        link = serializer.save(module_id=module.id, project_id=module.project_id, workspace_id=module.workspace_id)

    return {
        "id": str(link.id),
        "module_id": str(link.module_id),
        "project_id": str(link.project_id),
        "workspace_id": str(link.workspace_id),
        "url": link.url,
    }


def _module_link_teardown(record: dict, ctx: Any) -> None:
    ModuleLink.all_objects.filter(pk=record["id"]).delete()


ModuleLink_ = define_factory(
    create=db_call(_module_link_create),
    input_model=ModuleLinkInput,
    teardown=db_call(_module_link_teardown),
)


class ModuleUserPropertiesInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    module_id: str
    user_id: str
    filters: Optional[dict] = None
    display_filters: Optional[dict] = None
    display_properties: Optional[dict] = None


def _properties_create(data: ModuleUserPropertiesInput, ctx: Any) -> dict:
    # ModuleUserPropertiesEndpoint.get creates the row, .patch writes the filters.
    user = resolve_user(data.user_id)
    module = Module.objects.get(pk=data.module_id)

    with acting_user(user):
        properties, _ = ModuleUserProperties.objects.get_or_create(
            user=user, module_id=module.id, project_id=module.project_id
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
        "module_id": str(properties.module_id),
        "user_id": str(properties.user_id),
        "project_id": str(properties.project_id),
        "workspace_id": str(properties.workspace_id),
    }


def _properties_teardown(record: dict, ctx: Any) -> None:
    ModuleUserProperties.all_objects.filter(pk=record["id"]).delete()


ModuleUserProperties_ = define_factory(
    create=db_call(_properties_create),
    input_model=ModuleUserPropertiesInput,
    teardown=db_call(_properties_teardown),
)
