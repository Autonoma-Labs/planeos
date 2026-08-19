# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Autonoma Environment Factory endpoint.

Autonoma seeds and tears down isolated test data for an end-to-end run by calling
one signed endpoint — mounted at ``/api/autonoma`` in ``plane/urls.py``. The SDK
owns the protocol (``discover``/``up``/``down``), the HMAC verification and the
teardown ordering; this module supplies the factory registry, the scope field and
the auth callback.

Requests are authenticated by an HMAC signature over the body, keyed on
``AUTONOMA_SHARED_SECRET``. There is no on/off switch: an unsigned or tampered
request is rejected with 401 wherever the endpoint runs.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from django.conf import settings

from autonoma import AuthContext, HandlerConfig
from autonoma_django import create_django_handler
from plane.authentication.utils.login import user_login
from plane.db.models import User

from .factories import factories
from .support import db_call, stub_request


def _authenticate(user: Optional[dict], ctx: AuthContext) -> dict:
    """Hand the test runner real credentials for the seeded user.

    Plane authenticates browser traffic with a Django session cookie, so this issues
    a genuine session through the app's own ``user_login`` — the same call the
    sign-in views make — and returns the cookie. The password is returned as well so
    a test that wants to exercise the sign-in screen can log in for real; the user
    factory created the account through the real sign-up path, so it works.
    """
    account = User.objects.filter(pk=user["id"]).first() if user else None
    if account is None:
        return {}

    request = stub_request(user=account)
    user_login(request=request, user=account, is_app=True)

    cookie: dict[str, Any] = {
        "name": settings.SESSION_COOKIE_NAME,
        "value": request.session.session_key,
        "path": settings.SESSION_COOKIE_PATH or "/",
        "httpOnly": bool(settings.SESSION_COOKIE_HTTPONLY),
        "sameSite": settings.SESSION_COOKIE_SAMESITE or "Lax",
    }
    if settings.SESSION_COOKIE_DOMAIN:
        cookie["domain"] = settings.SESSION_COOKIE_DOMAIN

    payload: dict[str, Any] = {"cookies": [cookie]}

    password = user.get("password")
    if password:
        payload["credentials"] = {"email": account.email, "password": password}

    return payload


config = HandlerConfig(
    # Almost every table in plane.db hangs off the workspace, and teardown deletes
    # the workspace so the database cascade takes the rest with it.
    scope_field="workspace_id",
    shared_secret=os.environ.get("AUTONOMA_SHARED_SECRET", ""),
    signing_secret=os.environ.get("AUTONOMA_SIGNING_SECRET", ""),
    factories=factories,
    auth=db_call(_authenticate),
    sdk={"orm": "django-orm"},
)

autonoma_endpoint = create_django_handler(config)
