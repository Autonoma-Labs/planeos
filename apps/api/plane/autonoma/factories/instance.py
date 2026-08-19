# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Instance-level factories.

``Instance`` and ``InstanceConfiguration`` are singletons in Plane: the API
container runs ``register_instance``/``configure_instance`` on boot,
``Instance.objects.first()`` is how every request resolves "this instance", and
``instance_configurations.key`` is globally unique. Neither can be created
per test run, so these two factories adopt the rows the app already registered
and only ever apply values that are identical for every run. Their teardown is a
no-op — the instance row is shared infrastructure, not test data.

``InstanceAdmin`` is genuinely per-run: it points the shared instance at a
seeded user, and ``(instance, user)`` keeps that unique.
"""

from __future__ import annotations

from typing import Any, Optional

from django.core.management import call_command
from pydantic import BaseModel, ConfigDict

from autonoma import define_factory
from plane.license.models import Instance, InstanceAdmin, InstanceConfiguration
from plane.license.utils.encryption import encrypt_data

from ..support import acting_user, db_call, resolve_user


class InstanceInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instance_name: Optional[str] = None
    whitelist_emails: Optional[str] = None
    is_setup_done: Optional[bool] = None
    is_telemetry_enabled: Optional[bool] = None


def _instance_create(data: InstanceInput, ctx: Any) -> dict:
    instance = Instance.objects.first()
    if instance is None:
        # No instance registered yet (a bare database). Use the app's own
        # registration command rather than inserting the row by hand.
        call_command("register_instance", "autonoma-environment-factory")
        instance = Instance.objects.first()

    adopted = True

    # Only flags whose value is the same for every run are applied, so two
    # concurrent seeds can never disagree about the shared instance.
    updates = {}
    if data.is_setup_done is not None:
        updates["is_setup_done"] = data.is_setup_done
    if data.is_telemetry_enabled is not None:
        updates["is_telemetry_enabled"] = data.is_telemetry_enabled
    if data.whitelist_emails is not None:
        updates["whitelist_emails"] = data.whitelist_emails
    if updates:
        for field, value in updates.items():
            setattr(instance, field, value)
        instance.save(update_fields=list(updates))

    return {"id": str(instance.id), "instance_id": instance.instance_id, "adopted": adopted}


def _instance_teardown(record: dict, ctx: Any) -> None:
    # Never delete the singleton: every request in the process resolves through it.
    return None


Instance_ = define_factory(
    create=db_call(_instance_create),
    input_model=InstanceInput,
    teardown=db_call(_instance_teardown),
)


class InstanceConfigurationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    value: Optional[str] = None
    category: Optional[str] = None
    is_encrypted: bool = False


def _configuration_create(data: InstanceConfigurationInput, ctx: Any) -> dict:
    configuration, created = InstanceConfiguration.objects.get_or_create(
        key=data.key,
        defaults={"category": data.category or "AUTONOMA", "is_encrypted": data.is_encrypted},
    )

    if data.value is not None:
        configuration.value = encrypt_data(data.value) if configuration.is_encrypted else data.value
        configuration.save(update_fields=["value"])

    return {"id": str(configuration.id), "key": configuration.key, "created": created}


def _configuration_teardown(record: dict, ctx: Any) -> None:
    # Instance configuration is instance-wide, keyed on a globally unique column,
    # and re-created identically by ``configure_instance`` on every boot. Deleting
    # it would pull authentication settings out from under a concurrent run.
    return None


InstanceConfiguration_ = define_factory(
    create=db_call(_configuration_create),
    input_model=InstanceConfigurationInput,
    teardown=db_call(_configuration_teardown),
)


class InstanceAdminInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    role: int = 20
    is_verified: bool = True


def _admin_create(data: InstanceAdminInput, ctx: Any) -> dict:
    # Mirrors InstanceAdminEndpoint.post: resolve the singleton instance, then
    # attach the user to it.
    instance = Instance.objects.first()
    if instance is None:
        raise RuntimeError("Instance is not registered yet")

    user = resolve_user(data.user_id)
    with acting_user(user):
        admin = InstanceAdmin.objects.create(
            instance=instance,
            user=user,
            role=data.role,
            is_verified=data.is_verified,
        )

    return {"id": str(admin.id), "user_id": str(admin.user_id), "instance_id": str(admin.instance_id)}


def _admin_teardown(record: dict, ctx: Any) -> None:
    # InstanceAdmin.user is SET_NULL, so deleting the seeded user leaves the row
    # behind — remove it explicitly.
    InstanceAdmin.all_objects.filter(pk=record["id"]).delete()


InstanceAdmin_ = define_factory(
    create=db_call(_admin_create),
    input_model=InstanceAdminInput,
    teardown=db_call(_admin_teardown),
)
