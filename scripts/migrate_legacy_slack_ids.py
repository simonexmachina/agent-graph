"""One-off SQLite migration for legacy single-workspace Slack IDs.

Rewrites legacy Slack entity/person IDs in-place to the workspace-qualified
format introduced by multi-account connector support.

Usage:
    python3 scripts/migrate_legacy_slack_ids.py [--db /path/to/agentgraph.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentgraph.auth.credentials import load_platform_accounts, save_platform_accounts
from agentgraph.config import get_settings
from agentgraph_connector_slack.auth import list_slack_accounts


@dataclass(frozen=True)
class SlackAccount:
    account_id: str
    team_id: str
    user_id: str | None
    label: str


def _team_id_from_xoxc(token: str) -> str | None:
    parts = token.split("-")
    return parts[1] if len(parts) >= 2 else None


def resolve_single_slack_account() -> SlackAccount:
    raw_accounts = load_platform_accounts("slack")
    if len(raw_accounts) != 1:
        raise RuntimeError(
            f"Expected exactly 1 Slack account for one-off migration, found {len(raw_accounts)}"
        )
    raw = dict(raw_accounts[0])
    team_id = raw.get("team_id")
    if not team_id:
        token = raw.get("xoxc_token")
        if isinstance(token, str):
            team_id = _team_id_from_xoxc(token)
    if not team_id:
        raise RuntimeError("Slack credentials are missing team_id and it could not be inferred from xoxc_token")

    user_id = raw.get("user_id")
    account_id = raw.get("account_id")
    if not account_id or account_id == "slack":
        account_id = f"slack:{team_id}:{user_id}" if user_id else f"slack:{team_id}"

    changed = False
    if raw.get("team_id") != team_id:
        raw["team_id"] = team_id
        changed = True
    if raw.get("account_id") != account_id:
        raw["account_id"] = account_id
        changed = True
    if changed:
        save_platform_accounts("slack", [raw], default_account_id=str(account_id))

    accounts = list_slack_accounts()
    if len(accounts) != 1:
        raise RuntimeError(
            f"Expected exactly 1 Slack account for one-off migration, found {len(accounts)}"
        )
    account = accounts[0]
    account_id = account.get("account_id")
    team_id = account.get("team_id")
    if not account_id or not team_id:
        raise RuntimeError("Slack credentials are missing account_id/team_id; re-run Slack auth first")
    return SlackAccount(
        account_id=str(account_id),
        team_id=str(team_id),
        user_id=str(account["user_id"]) if account.get("user_id") else None,
        label=str(account.get("label") or team_id),
    )


def _channel_ref(team_id: str, channel_id: str) -> str:
    return f"{team_id}/{channel_id}"


def _message_ref(team_id: str, channel_id: str, ts: str) -> str:
    return f"{team_id}/{channel_id}:{ts}"


def _user_ref(team_id: str, user_id: str) -> str:
    return f"slack:{team_id}/{user_id}"


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception as exc:  # pragma: no cover - defensive, validated by migration failure
        raise RuntimeError(f"Unreadable metadata JSON: {raw!r}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected object metadata, got {type(value).__name__}")
    return value


def _rewrite_slack_entity_id(entity_type: str, old_id: str, team_id: str) -> str:
    if "/" in old_id:
        return old_id
    if entity_type == "Channel":
        return _channel_ref(team_id, old_id)
    if entity_type == "Message":
        channel_id, sep, ts = old_id.partition(":")
        if not sep or not channel_id or not ts:
            raise RuntimeError(f"Legacy Slack message ID has unexpected format: {old_id}")
        return _message_ref(team_id, channel_id, ts)
    raise RuntimeError(f"Unsupported legacy Slack entity type: {entity_type}")


def _rewrite_slack_metadata(entity_type: str, metadata: dict[str, Any], account: SlackAccount) -> dict[str, Any]:
    updated = dict(metadata)
    updated["team_id"] = account.team_id
    updated["account_id"] = account.account_id

    channel_id = updated.get("channel_id")
    if isinstance(channel_id, str) and "/" in channel_id:
        updated["channel_id"] = channel_id.split("/", 1)[1]

    if entity_type == "Channel":
        if isinstance(channel_id, str) and channel_id:
            updated["channel_id"] = channel_id

    return updated


def _rewrite_canonical_person(metadata: dict[str, Any], old_id: str, account: SlackAccount) -> tuple[str, dict[str, Any]]:
    _, _, user_id = old_id.partition(":")
    if not user_id or "/" in user_id:
        return old_id, metadata
    updated = dict(metadata)
    updated["slack_user_id"] = f"{account.team_id}/{user_id}"
    return _user_ref(account.team_id, user_id), updated


def migrate_sqlite(
    db_path: Path,
    account: SlackAccount,
    *,
    dry_run: bool = False,
    make_backup: bool = True,
) -> dict[str, int | str]:
    if not db_path.exists():
        raise RuntimeError(f"SQLite database not found: {db_path}")

    backup_path = db_path.with_suffix(db_path.suffix + ".pre_slack_id_migration.bak")
    if make_backup and not dry_run:
        shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        conn.execute("BEGIN IMMEDIATE")

        legacy_slack_rows = conn.execute(
            """
            SELECT id, entity_type, platform_entity_id, metadata
            FROM entities
            WHERE platform = 'slack' AND instr(platform_entity_id, '/') = 0
            """
        ).fetchall()

        person_rows = conn.execute(
            """
            SELECT id, platform_entity_id, metadata
            FROM entities
            WHERE platform = 'canonical'
              AND entity_type = 'Person'
              AND platform_entity_id LIKE 'slack:%'
              AND instr(substr(platform_entity_id, 7), '/') = 0
            """
        ).fetchall()

        entity_updates: list[tuple[str, str, str]] = []
        metadata_updates: list[tuple[str, str]] = []
        person_updates: list[tuple[str, str, str]] = []

        for row in legacy_slack_rows:
            entity_id = str(row["id"])
            entity_type = str(row["entity_type"])
            old_platform_id = str(row["platform_entity_id"])
            new_platform_id = _rewrite_slack_entity_id(entity_type, old_platform_id, account.team_id)
            entity_updates.append((new_platform_id, entity_id, old_platform_id))

            metadata = _load_metadata(row["metadata"])
            updated_metadata = _rewrite_slack_metadata(entity_type, metadata, account)
            metadata_updates.append((json.dumps(updated_metadata), entity_id))

        for row in person_rows:
            entity_id = str(row["id"])
            old_platform_id = str(row["platform_entity_id"])
            metadata = _load_metadata(row["metadata"])
            new_platform_id, updated_metadata = _rewrite_canonical_person(metadata, old_platform_id, account)
            person_updates.append((new_platform_id, json.dumps(updated_metadata), entity_id))

        target_slack_ids = [new_id for new_id, _, old_id in entity_updates if new_id != old_id]
        if target_slack_ids:
            placeholders = ",".join("?" for _ in target_slack_ids)
            collisions = conn.execute(
                f"""
                SELECT platform_entity_id
                FROM entities
                WHERE platform = 'slack'
                  AND platform_entity_id IN ({placeholders})
                  AND instr(platform_entity_id, '/') > 0
                """,
                target_slack_ids,
            ).fetchall()
            if collisions:
                ids = ", ".join(str(row["platform_entity_id"]) for row in collisions)
                raise RuntimeError(f"Aborting migration due to existing Slack ID collisions: {ids}")

        target_person_ids = [new_id for new_id, _, _ in person_updates if new_id.startswith("slack:")]
        if target_person_ids:
            placeholders = ",".join("?" for _ in target_person_ids)
            collisions = conn.execute(
                f"""
                SELECT platform_entity_id
                FROM entities
                WHERE platform = 'canonical'
                  AND platform_entity_id IN ({placeholders})
                """,
                target_person_ids,
            ).fetchall()
            collision_set = {str(row["platform_entity_id"]) for row in collisions}
            old_set = {str(row["platform_entity_id"]) for row in person_rows}
            if collision_set - old_set:
                ids = ", ".join(sorted(collision_set))
                raise RuntimeError(f"Aborting migration due to existing canonical Slack person collisions: {ids}")

        for new_platform_id, entity_id, _old_platform_id in entity_updates:
            conn.execute(
                "UPDATE entities SET platform_entity_id = ? WHERE id = ?",
                [new_platform_id, entity_id],
            )
        for metadata_json, entity_id in metadata_updates:
            conn.execute(
                "UPDATE entities SET metadata = ? WHERE id = ?",
                [metadata_json, entity_id],
            )
        for new_platform_id, metadata_json, entity_id in person_updates:
            conn.execute(
                "UPDATE entities SET platform_entity_id = ?, metadata = ? WHERE id = ?",
                [new_platform_id, metadata_json, entity_id],
            )

        legacy_cursor = conn.execute(
            "SELECT cursor FROM sync_state WHERE source = ?",
            ["slack"],
        ).fetchone()
        new_cursor_key = f"slack:{account.account_id}"
        cursor_updates = 0
        if legacy_cursor is not None:
            existing_new_cursor = conn.execute(
                "SELECT 1 FROM sync_state WHERE source = ?",
                [new_cursor_key],
            ).fetchone()
            if existing_new_cursor is not None:
                raise RuntimeError(f"Refusing to overwrite existing sync cursor {new_cursor_key}")
            conn.execute(
                "INSERT INTO sync_state (source, cursor, updated_at) VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                [new_cursor_key, legacy_cursor["cursor"]],
            )
            conn.execute("DELETE FROM sync_state WHERE source = ?", ["slack"])
            cursor_updates = 1

        result = {
            "db_path": str(db_path),
            "backup_path": str(backup_path) if make_backup and not dry_run else "",
            "slack_entities_rewritten": len(entity_updates),
            "canonical_persons_rewritten": len(person_updates),
            "sync_cursors_rewritten": cursor_updates,
        }

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(settings.backend_sqlite_path).expanduser(),
        help="Path to the AgentGraph SQLite database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without committing changes",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip writing a .bak copy before mutating the database",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account = resolve_single_slack_account()
    result = migrate_sqlite(
        args.db,
        account,
        dry_run=args.dry_run,
        make_backup=not args.no_backup,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
