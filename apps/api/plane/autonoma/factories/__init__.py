# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Registry of Autonoma environment factories.

Keys are the model names Autonoma sends in a scenario's ``create`` payload; they
match the entity names in the Autonoma entity audit. Every model that appears in a
recipe needs an entry here.
"""

from .cycle import Cycle_, CycleIssue_, CycleUserProperties_
from .instance import Instance_, InstanceAdmin_, InstanceConfiguration_
from .intake import IntakeIssue_
from .issue import (
    Issue_,
    IssueComment_,
    IssueLink_,
    IssueRelation_,
    IssueSubscriber_,
)
from .module import Module_, ModuleIssue_, ModuleLink_, ModuleUserProperties_
from .page import Page_
from .project import (
    Label_,
    Project_,
    ProjectMember_,
    ProjectMemberInvite_,
    State_,
)
from .user import User_
from .views import AnalyticView_, IssueView_
from .workspace import (
    Workspace_,
    WorkspaceMember_,
    WorkspaceMemberInvite_,
    WorkspaceUserProperties_,
)
from .workspace_extras import (
    APIToken_,
    DeployBoard_,
    DraftIssue_,
    ExporterHistory_,
    FileAsset_,
    UserFavorite_,
    Webhook_,
)

factories = {
    "AnalyticView": AnalyticView_,
    "APIToken": APIToken_,
    "Cycle": Cycle_,
    "CycleIssue": CycleIssue_,
    "CycleUserProperties": CycleUserProperties_,
    "DeployBoard": DeployBoard_,
    "DraftIssue": DraftIssue_,
    "ExporterHistory": ExporterHistory_,
    "FileAsset": FileAsset_,
    "Instance": Instance_,
    "InstanceAdmin": InstanceAdmin_,
    "InstanceConfiguration": InstanceConfiguration_,
    "IntakeIssue": IntakeIssue_,
    "Issue": Issue_,
    "IssueComment": IssueComment_,
    "IssueLink": IssueLink_,
    "IssueRelation": IssueRelation_,
    "IssueSubscriber": IssueSubscriber_,
    "IssueView": IssueView_,
    "Label": Label_,
    "Module": Module_,
    "ModuleIssue": ModuleIssue_,
    "ModuleLink": ModuleLink_,
    "ModuleUserProperties": ModuleUserProperties_,
    "Page": Page_,
    "Project": Project_,
    "ProjectMember": ProjectMember_,
    "ProjectMemberInvite": ProjectMemberInvite_,
    "State": State_,
    "User": User_,
    "UserFavorite": UserFavorite_,
    "Webhook": Webhook_,
    "Workspace": Workspace_,
    "WorkspaceMember": WorkspaceMember_,
    "WorkspaceMemberInvite": WorkspaceMemberInvite_,
    "WorkspaceUserProperties": WorkspaceUserProperties_,
}

__all__ = ["factories"]
