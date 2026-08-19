# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""User factory.

Users are created through the real sign-up path — ``EmailProvider.authenticate()``
on ``plane.authentication.adapter.credential.CredentialAdapter`` — so the seeded
user gets a properly hashed password, a ``Profile``, a
``UserNotificationPreference`` (post_save signal) and the same
``last_login_*``/``is_active`` bookkeeping a real sign-up produces. That is what
makes the credentials Autonoma hands the test runner actually work.

The provider deliberately ignores first/last name on sign-up (Plane collects them
in onboarding), so the names from the recipe are applied afterwards the way
``UpdateUserOnBoardEndpoint`` does.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.authentication.provider.credentials.email import EmailProvider
from plane.db.models import Profile, Session, User

from ..support import acting_user, db_call, stub_request

# Every seeded user shares one strong password so the auth callback can hand the
# runner working credentials. zxcvbn scores it 4/4, which the sign-up path requires.
DEFAULT_PASSWORD = "Autonoma-Plane-Seed-2f9x"


class UserInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str
    first_name: str = ""
    last_name: str = ""
    display_name: Optional[str] = None
    password: str = DEFAULT_PASSWORD
    is_onboarded: bool = True
    is_email_verified: bool = True


def _create(data: UserInput, ctx: Any) -> dict:
    request = stub_request()

    provider = EmailProvider(request=request, key=data.email, code=data.password, is_signup=True)
    user = provider.authenticate()

    # Names are set after sign-up, the way onboarding does it.
    user.first_name = data.first_name
    user.last_name = data.last_name
    user.display_name = data.display_name or User.get_display_name(data.email)
    user.is_email_verified = data.is_email_verified
    user.save(update_fields=["first_name", "last_name", "display_name", "is_email_verified"])

    # is_onboarded lives on the profile the sign-up path created; without it every
    # test would land on the onboarding wizard instead of the workspace.
    Profile.objects.filter(user=user).update(is_onboarded=data.is_onboarded)

    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": user.display_name,
        "password": data.password,
    }


def _teardown(record: dict, ctx: Any) -> None:
    user = User.objects.filter(pk=record["id"]).first()
    if user is None:
        return

    # sessions.user_id is a plain char column, not a foreign key, so sessions do
    # not cascade with the user.
    Session.objects.filter(user_id=str(user.id)).delete()

    with acting_user(None):
        # User is not a soft-delete model: this is a real cascading delete, which
        # takes the profile, notification preferences, memberships and API tokens
        # with it.
        user.delete()


User_ = define_factory(
    create=db_call(_create),
    input_model=UserInput,
    teardown=db_call(_teardown),
)
