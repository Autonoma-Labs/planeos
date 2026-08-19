# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Shared plumbing for the Autonoma environment factories.

Autonoma's SDK handler is awaited inside ``asyncio.run()`` (see
``autonoma_django.create_django_handler``), so a factory that touched the ORM
directly would trip Django's ``SynchronousOnlyOperation`` guard. Every factory is
therefore written as a plain synchronous function and wrapped with
:func:`db_call`, which hands it to a dedicated seeding thread where the ORM runs
exactly as it does inside a normal request.

The factories call the app's own creation code (serializers, view helpers), and
that code reads the acting user from ``crum`` the way
``crum.CurrentRequestUserMiddleware`` sets it per request. :func:`acting_user`
reproduces that, and :func:`stub_request` builds the minimal request object the
serializers and auth adapters expect.
"""

from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from asgiref.sync import sync_to_async
from crum import impersonate
from django.conf import settings
from django.db import close_old_connections
from django.test import RequestFactory
from django.utils import timezone

from plane.db.models import User

# Marker stored on every row this integration creates, so a query can always
# tell seeded rows apart from anything else in the database.
TEST_SOURCE = "autonoma"


# The SDK's Django adapter is a SYNCHRONOUS view that drives the protocol with
# ``asyncio.run()``. Under ASGI that view is already executing on a worker thread
# that asgiref owns — Plane's middleware stack is sync-only (CorsMiddleware,
# crum), so Django bridges the async chain back to sync with ``async_to_sync``,
# which pins the request to a ``CurrentThreadExecutor``. Re-entering asgiref from
# there with ``thread_sensitive=True`` asks that executor to run work on the very
# thread it is blocking in, and asgiref refuses: "You cannot submit onto
# CurrentThreadExecutor from its own thread".
#
# So the ORM work goes to a thread of our own instead. One worker means one
# thread, so a whole ``up``/``down`` shares a single database connection the way
# a request does, and no event loop is running there — which is all Django's
# ``SynchronousOnlyOperation`` guard actually asks for.
_seed_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autonoma-seed")


def db_call(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run a synchronous ORM function from the SDK's async handler."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return sync_to_async(_run_in_sync_thread, thread_sensitive=False, executor=_seed_executor)(
            fn, args, kwargs
        )

    return wrapper


def _run_in_sync_thread(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    close_old_connections()
    return fn(*args, **kwargs)


def stub_request(user: Optional[User] = None, path: str = "/api/autonoma") -> Any:
    """Build the request object the app's creation code reads.

    Serializers and the authentication adapters take a request for the host, the
    client IP and the user agent. Nothing in the seeding path returns a response,
    so a ``RequestFactory`` request with a live session store is enough.
    """
    from plane.db.models.session import SessionStore

    request = RequestFactory().post(path)
    request.session = SessionStore()
    request.user = user
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.META["HTTP_USER_AGENT"] = "autonoma-environment-factory"
    request.META["HTTP_HOST"] = _app_host()
    return request


def _app_host() -> str:
    base = getattr(settings, "APP_BASE_URL", None) or getattr(settings, "WEB_URL", None) or "http://localhost:3000"
    return base.split("://")[-1].split("/")[0]


@contextmanager
def acting_user(user: Optional[User]):
    """Impersonate ``user`` for the duration of the block.

    ``plane.db.models.BaseModel.save`` fills ``created_by``/``updated_by`` from
    ``crum.get_current_user()``, which ``crum.CurrentRequestUserMiddleware`` sets
    per request. Seeding runs outside the request cycle, so we set it ourselves
    rather than leaving every seeded row unattributed. ``crum.impersonate``
    restores the previous value on the way out.
    """
    with impersonate(user):
        yield user


def resolve_user(user_id: Optional[str]) -> Optional[User]:
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


# ---------------------------------------------------------------------------
# time offsets
# ---------------------------------------------------------------------------
#
# The recipe is stored once and replayed unchanged before every run, so any value
# the app compares against "now" has to be derived at seeding time. Factories take
# an offset in days/minutes and add it to the current clock here.


def offset_datetime(days: Optional[float] = None, minutes: Optional[float] = None) -> Optional[datetime]:
    if days is None and minutes is None:
        return None
    delta = timedelta(days=days or 0, minutes=minutes or 0)
    return timezone.now() + delta


def offset_date(days: Optional[float] = None) -> Optional[date]:
    moment = offset_datetime(days=days)
    return None if moment is None else timezone.localtime(moment).date()
