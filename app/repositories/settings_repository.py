from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.setting import Setting


class SettingsRepository:
    def get_many(self, session: Session, keys: set[str]) -> dict[str, Any]:
        if not keys:
            return {}

        statement = select(Setting).where(Setting.key.in_(keys))
        return {setting.key: setting.value_json for setting in session.scalars(statement)}

    def upsert_many(self, session: Session, values: dict[str, Any]) -> dict[str, Any]:
        if not values:
            return {}

        existing = {
            setting.key: setting
            for setting in session.scalars(
                select(Setting).where(Setting.key.in_(set(values.keys())))
            )
        }

        for key, value in values.items():
            if key in existing:
                existing[key].value_json = value
            else:
                session.add(Setting(key=key, value_json=value))

        session.flush()
        return values

