# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Saved-view factories.

Both serializers compile the raw filter dict into the stored ``query`` column via
``plane.utils.issue_filters.issue_filters``, which is exactly why they are worth
going through: a hand-written insert would leave ``query`` empty and the saved view
would return every work item.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.app.serializers import AnalyticViewSerializer, IssueViewSerializer
from plane.db.models import AnalyticView, IssueView

from ..support import acting_user, db_call, resolve_user


class IssueViewInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    name: str
    owned_by_id: str
    project_id: Optional[str] = None
    description: str = ""
    filters: dict = {}
    display_filters: Optional[dict] = None
    access: int = 1


def _view_create(data: IssueViewInput, ctx: Any) -> dict:
    owner = resolve_user(data.owned_by_id)

    payload: dict[str, Any] = {
        "name": data.name,
        "description": data.description,
        "filters": data.filters,
    }
    if data.display_filters is not None:
        payload["display_filters"] = data.display_filters

    with acting_user(owner):
        serializer = IssueViewSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        view = serializer.save(
            workspace_id=data.workspace_id,
            project_id=data.project_id,
            owned_by=owner,
            access=data.access,
        )

    return {
        "id": str(view.id),
        "workspace_id": str(view.workspace_id),
        "project_id": str(view.project_id) if view.project_id else None,
        "name": view.name,
    }


def _view_teardown(record: dict, ctx: Any) -> None:
    IssueView.all_objects.filter(pk=record["id"]).delete()


IssueView_ = define_factory(
    create=db_call(_view_create),
    input_model=IssueViewInput,
    teardown=db_call(_view_teardown),
)


class AnalyticViewInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspace_id: str
    name: str
    created_by_id: Optional[str] = None
    description: str = ""
    query_dict: dict = {}


def _analytic_create(data: AnalyticViewInput, ctx: Any) -> dict:
    actor = resolve_user(data.created_by_id)

    with acting_user(actor):
        serializer = AnalyticViewSerializer(
            data={
                "name": data.name,
                "description": data.description,
                "query_dict": data.query_dict,
            }
        )
        serializer.is_valid(raise_exception=True)
        view = serializer.save(workspace_id=data.workspace_id)

    return {"id": str(view.id), "workspace_id": str(view.workspace_id), "name": view.name}


def _analytic_teardown(record: dict, ctx: Any) -> None:
    AnalyticView.all_objects.filter(pk=record["id"]).delete()


AnalyticView_ = define_factory(
    create=db_call(_analytic_create),
    input_model=AnalyticViewInput,
    teardown=db_call(_analytic_teardown),
)
