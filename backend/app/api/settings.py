"""
Settings API — manage dynamic application settings.

Endpoints:
  GET  /api/settings          → list all settings (grouped by category)
  GET  /api/settings/defaults → list SETTING_DEFAULTS
  PUT  /api/settings/{key}    → update a setting (key must exist in SETTING_DEFAULTS)
  POST /api/settings/reset/{key} → reset a setting to its default value
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SETTING_DEFAULTS, Settings, get_settings
from app.modules.pipeline.prompts import AGENT_PROMPT_DEFAULTS
from app.core.database import get_db
from app.models.settings import AppSetting

router = APIRouter(prefix="/settings", tags=["settings"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

_VALID_TYPES = {"str", "int", "float", "bool", "json", "secret", "text"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SettingOut(BaseModel):
    key: str
    value: str
    value_type: str
    description: str
    updated_by: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingUpdate(BaseModel):
    value: str


def _allows_empty_value(key: str) -> bool:
    if key.startswith("agent."):
        return True
    if key.endswith(".prompt"):
        return True
    default_value, _, _ = SETTING_DEFAULTS.get(key, ("", "", ""))
    return default_value == ""


def _merged_settings(rows: list[AppSetting]) -> list[SettingOut]:
    """Return all known settings, filling in defaults for keys not yet in DB."""
    by_key = {row.key: row for row in rows}
    merged: list[SettingOut] = []
    for key, (default_value, value_type, desc) in sorted(SETTING_DEFAULTS.items()):
        row = by_key.get(key)
        if row is not None:
            merged.append(SettingOut.model_validate(row))
        else:
            merged.append(
                SettingOut(
                    key=key,
                    value=default_value,
                    value_type=value_type,
                    description=desc,
                    updated_by=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
    return merged


class DefaultSettingOut(BaseModel):
    key: str
    default_value: str
    value_type: str
    description: str
    category: str


class GroupedSettingsOut(BaseModel):
    category: str
    settings: list[SettingOut]


class AgentPromptDefaultsOut(BaseModel):
    agents: dict[str, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category(key: str) -> str:
    return key.split(".")[0] if "." in key else "_other"


def _group_settings(settings: list[SettingOut]) -> list[GroupedSettingsOut]:
    groups: dict[str, list[SettingOut]] = {}
    for item in settings:
        cat = _category(item.key)
        groups.setdefault(cat, []).append(item)
    return [
        GroupedSettingsOut(category=cat, settings=items)
        for cat, items in sorted(groups.items())
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/prompt-defaults",
    response_model=AgentPromptDefaultsOut,
    summary="Built-in default system prompts for pipeline agents",
)
async def list_prompt_defaults() -> AgentPromptDefaultsOut:
    return AgentPromptDefaultsOut(agents=AGENT_PROMPT_DEFAULTS)


@router.get(
    "/defaults",
    response_model=list[DefaultSettingOut],
    summary="Built-in default values for all known settings",
)
async def list_defaults() -> list[DefaultSettingOut]:
    """Return all keys defined in SETTING_DEFAULTS with their defaults."""
    return [
        DefaultSettingOut(
            key=key,
            default_value=default,
            value_type=vtype,
            description=desc,
            category=_category(key),
        )
        for key, (default, vtype, desc) in sorted(SETTING_DEFAULTS.items())
    ]


@router.get(
    "/",
    response_model=list[GroupedSettingsOut],
    summary="All settings stored in DB, grouped by category prefix",
)
async def list_settings(
    svc: SettingsDep,
    db: AsyncSession = Depends(get_db),
) -> list[GroupedSettingsOut]:
    rows = list(await db.scalars(select(AppSetting).order_by(AppSetting.key)))
    return _group_settings(_merged_settings(rows))


@router.put(
    "/{key}",
    response_model=SettingOut,
    summary="Update a setting value (key must exist in SETTING_DEFAULTS)",
)
async def update_setting(
    key: str,
    body: SettingUpdate,
    svc: SettingsDep,
    db: AsyncSession = Depends(get_db),
) -> SettingOut:
    if key not in SETTING_DEFAULTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setting key '{key}'. See /api/settings/defaults for valid keys.",
        )

    if not body.value.strip() and not _allows_empty_value(key):
        raise HTTPException(status_code=400, detail="value cannot be empty")

    default_value, value_type, default_desc = SETTING_DEFAULTS[key]

    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row:
        row.value = body.value
        row.updated_by = "api"
    else:
        row = AppSetting(
            key=key,
            value=body.value,
            value_type=value_type,
            description=default_desc,
            updated_by="api",
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    # Invalidate Redis cache so next read reflects the new value
    await svc.refresh(key)

    return SettingOut.model_validate(row)


@router.post(
    "/reset/{key}",
    response_model=SettingOut,
    summary="Reset a setting to its built-in default value",
)
async def reset_setting(
    key: str,
    svc: SettingsDep,
    db: AsyncSession = Depends(get_db),
) -> SettingOut:
    if key not in SETTING_DEFAULTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setting key '{key}'. See /api/settings/defaults for valid keys.",
        )

    default_value, value_type, default_desc = SETTING_DEFAULTS[key]

    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row:
        row.value = default_value
        row.value_type = value_type
        row.updated_by = "api"
    else:
        row = AppSetting(
            key=key,
            value=default_value,
            value_type=value_type,
            description=default_desc,
            updated_by="api",
        )
        db.add(row)

    await db.commit()
    await db.refresh(row)

    await svc.refresh(key)

    return SettingOut.model_validate(row)
