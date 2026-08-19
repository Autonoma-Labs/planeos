# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Page factory.

``PageSerializer.create`` takes the body of the page from its serializer context —
the way ``PageViewSet.create`` passes it — and creates the ``ProjectPage`` link row
alongside the page itself.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.app.serializers import PageSerializer
from plane.db.models import Page

from ..support import acting_user, db_call, resolve_user


class PageInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    owned_by_id: str
    description_html: str = "<p></p>"
    description_json: Optional[dict] = None
    access: int = 0
    color: str = ""


def _create(data: PageInput, ctx: Any) -> dict:
    owner = resolve_user(data.owned_by_id)

    with acting_user(owner):
        serializer = PageSerializer(
            data={"name": data.name, "access": data.access, "color": data.color},
            context={
                "project_id": data.project_id,
                "owned_by_id": str(owner.id),
                "description_html": data.description_html,
                "description_json": data.description_json or {},
                "description_binary": None,
            },
        )
        serializer.is_valid(raise_exception=True)
        page = serializer.save()

    return {
        "id": str(page.id),
        "workspace_id": str(page.workspace_id),
        "project_id": str(data.project_id),
        "name": page.name,
        "owned_by_id": str(page.owned_by_id),
    }


def _teardown(record: dict, ctx: Any) -> None:
    Page.all_objects.filter(pk=record["id"]).delete()


Page_ = define_factory(
    create=db_call(_create),
    input_model=PageInput,
    teardown=db_call(_teardown),
)
