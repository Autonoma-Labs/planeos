# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Work-item factories.

``Issue`` goes through ``IssueCreateSerializer``, so the seeded issue gets its
``IssueSequence`` row (``Issue.save``), its ``IssueAssignee`` and ``IssueLabel``
rows, the project's default assignee when the recipe names none, and the
serializer's own validation (assignees and labels must belong to the project,
the state must be the project's, start date cannot pass target date).

Issue start/target dates are compared against the clock — ``UserWorkspaceDashboard``
partitions "My Issues" into overdue (``target_date__lt=now``) and upcoming
(``start_date__gte=now``) — so the recipe supplies day offsets and the factory turns
them into dates at seeding time.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.app.serializers import IssueCreateSerializer, IssueLinkSerializer
from plane.api.serializers import IssueCommentCreateSerializer
from plane.db.models import (
    Issue,
    IssueComment,
    IssueLink,
    IssueRelation,
    IssueSubscriber,
    Project,
)
from plane.utils.issue_relation_mapper import get_actual_relation

from ..support import acting_user, db_call, offset_date, resolve_user


class IssueInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str
    name: str
    created_by_id: str
    state_id: Optional[str] = None
    priority: str = "none"
    description_html: str = "<p></p>"
    assignee_ids: list[str] = []
    label_ids: list[str] = []
    parent_id: Optional[str] = None
    # Offsets in days from the moment of seeding; the app compares both against now.
    starts_in_days: Optional[float] = None
    target_in_days: Optional[float] = None


def _issue_create(data: IssueInput, ctx: Any) -> dict:
    creator = resolve_user(data.created_by_id)
    project = Project.objects.get(pk=data.project_id)

    payload: dict[str, Any] = {
        "name": data.name,
        "priority": data.priority,
        "description_html": data.description_html,
    }
    if data.state_id:
        payload["state_id"] = data.state_id
    if data.parent_id:
        payload["parent_id"] = data.parent_id
    if data.assignee_ids:
        payload["assignee_ids"] = data.assignee_ids
    if data.label_ids:
        payload["label_ids"] = data.label_ids

    start_date = offset_date(data.starts_in_days)
    target_date = offset_date(data.target_in_days)
    if start_date:
        payload["start_date"] = start_date.isoformat()
    if target_date:
        payload["target_date"] = target_date.isoformat()

    with acting_user(creator):
        serializer = IssueCreateSerializer(
            data=payload,
            context={
                "project_id": str(project.id),
                "workspace_id": str(project.workspace_id),
                "default_assignee_id": project.default_assignee_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        issue = serializer.save()

    return {
        "id": str(issue.id),
        "project_id": str(issue.project_id),
        "workspace_id": str(issue.workspace_id),
        "name": issue.name,
        "sequence_id": issue.sequence_id,
        "start_date": start_date.isoformat() if start_date else None,
        "target_date": target_date.isoformat() if target_date else None,
    }


def _issue_teardown(record: dict, ctx: Any) -> None:
    Issue.all_objects.filter(pk=record["id"]).delete()


Issue_ = define_factory(
    create=db_call(_issue_create),
    input_model=IssueInput,
    teardown=db_call(_issue_teardown),
)


class IssueCommentInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issue_id: str
    actor_id: str
    comment_html: str = "<p></p>"
    comment_json: Optional[dict] = None
    access: str = "INTERNAL"


def _comment_create(data: IssueCommentInput, ctx: Any) -> dict:
    # IssueCommentListCreateAPIEndpoint.post saves through
    # IssueCommentCreateSerializer with project/issue/actor, then re-stamps the
    # actor and created_by. IssueComment.save creates the Description row that
    # holds the rich-text body.
    actor = resolve_user(data.actor_id)
    issue = Issue.objects.get(pk=data.issue_id)

    payload: dict[str, Any] = {"comment_html": data.comment_html, "access": data.access}
    if data.comment_json is not None:
        payload["comment_json"] = data.comment_json

    with acting_user(actor):
        serializer = IssueCommentCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(project_id=issue.project_id, issue_id=issue.id, actor=actor)

        comment.created_by_id = actor.id
        comment.actor_id = actor.id
        comment.save(update_fields=["created_by", "actor"])

    return {
        "id": str(comment.id),
        "issue_id": str(comment.issue_id),
        "project_id": str(comment.project_id),
        "workspace_id": str(comment.workspace_id),
        "actor_id": str(comment.actor_id),
    }


def _comment_teardown(record: dict, ctx: Any) -> None:
    IssueComment.all_objects.filter(pk=record["id"]).delete()


IssueComment_ = define_factory(
    create=db_call(_comment_create),
    input_model=IssueCommentInput,
    teardown=db_call(_comment_teardown),
)


class IssueLinkInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issue_id: str
    url: str
    title: Optional[str] = None
    created_by_id: Optional[str] = None


def _link_create(data: IssueLinkInput, ctx: Any) -> dict:
    actor = resolve_user(data.created_by_id)
    issue = Issue.objects.get(pk=data.issue_id)

    with acting_user(actor):
        serializer = IssueLinkSerializer(data={"url": data.url, "title": data.title})
        serializer.is_valid(raise_exception=True)
        link = serializer.save(project_id=issue.project_id, issue_id=issue.id)

    return {
        "id": str(link.id),
        "issue_id": str(link.issue_id),
        "project_id": str(link.project_id),
        "workspace_id": str(link.workspace_id),
        "url": link.url,
    }


def _link_teardown(record: dict, ctx: Any) -> None:
    IssueLink.all_objects.filter(pk=record["id"]).delete()


IssueLink_ = define_factory(
    create=db_call(_link_create),
    input_model=IssueLinkInput,
    teardown=db_call(_link_teardown),
)


class IssueRelationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issue_id: str
    related_issue_id: str
    relation_type: str = "blocked_by"
    created_by_id: Optional[str] = None


def _relation_create(data: IssueRelationInput, ctx: Any) -> dict:
    # IssueRelationViewSet.create flips the two ends for the "blocking" family and
    # normalises the relation type through get_actual_relation before inserting.
    actor = resolve_user(data.created_by_id)
    issue = Issue.objects.get(pk=data.issue_id)

    flipped = data.relation_type in ["blocking", "start_after", "finish_after"]
    issue_id = data.related_issue_id if flipped else data.issue_id
    related_issue_id = data.issue_id if flipped else data.related_issue_id

    with acting_user(actor):
        relation = IssueRelation.objects.create(
            issue_id=issue_id,
            related_issue_id=related_issue_id,
            relation_type=get_actual_relation(data.relation_type),
            project_id=issue.project_id,
            workspace_id=issue.workspace_id,
        )

    return {
        "id": str(relation.id),
        "issue_id": str(relation.issue_id),
        "related_issue_id": str(relation.related_issue_id),
        "project_id": str(relation.project_id),
        "workspace_id": str(relation.workspace_id),
        "relation_type": relation.relation_type,
    }


def _relation_teardown(record: dict, ctx: Any) -> None:
    IssueRelation.all_objects.filter(pk=record["id"]).delete()


IssueRelation_ = define_factory(
    create=db_call(_relation_create),
    input_model=IssueRelationInput,
    teardown=db_call(_relation_teardown),
)


class IssueSubscriberInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    issue_id: str
    subscriber_id: str


def _subscriber_create(data: IssueSubscriberInput, ctx: Any) -> dict:
    # IssueSubscriberViewSet.perform_create saves the serializer with the project
    # and issue from the URL; the serializer itself adds no logic.
    subscriber = resolve_user(data.subscriber_id)
    issue = Issue.objects.get(pk=data.issue_id)

    with acting_user(subscriber):
        subscription = IssueSubscriber.objects.create(
            issue_id=issue.id,
            subscriber=subscriber,
            project_id=issue.project_id,
        )

    return {
        "id": str(subscription.id),
        "issue_id": str(subscription.issue_id),
        "project_id": str(subscription.project_id),
        "workspace_id": str(subscription.workspace_id),
        "subscriber_id": str(subscription.subscriber_id),
    }


def _subscriber_teardown(record: dict, ctx: Any) -> None:
    IssueSubscriber.all_objects.filter(pk=record["id"]).delete()


IssueSubscriber_ = define_factory(
    create=db_call(_subscriber_create),
    input_model=IssueSubscriberInput,
    teardown=db_call(_subscriber_teardown),
)
