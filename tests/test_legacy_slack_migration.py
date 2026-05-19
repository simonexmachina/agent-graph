from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_script_module() -> object:
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "migrate_legacy_slack_ids.py"
    spec = importlib.util.spec_from_file_location("migrate_legacy_slack_ids", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    schema = (Path(__file__).resolve().parent.parent / "agentgraph" / "backends" / "sqlite" / "schema.sql").read_text()
    conn.executescript(schema)
    return conn


def test_migrate_sqlite_rewrites_legacy_slack_ids(tmp_path: Path) -> None:
    module = _load_script_module()
    db_path = tmp_path / "agentgraph.db"
    conn = _init_db(db_path)
    conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, metadata, last_accessed)
        VALUES
          ('chan-1', 'Channel', 'slack', 'C123', '{"channel_id":"C123"}', '2026-01-01T00:00:00Z'),
          ('msg-1', 'Message', 'slack', 'C123:1712345678.123', '{"channel_id":"C123","ts":"1712345678.123"}', '2026-01-01T00:00:00Z'),
          ('person-1', 'Person', 'canonical', 'slack:U999', '{"slack_user_id":"U999"}', '2026-01-01T00:00:00Z')
        """
    )
    conn.execute(
        "INSERT INTO sync_state (source, cursor, updated_at) VALUES (?, ?, ?)",
        ["slack", '{"cursor":"abc"}', "2026-01-01T00:00:00Z"],
    )
    conn.commit()
    conn.close()

    account = module.SlackAccount(
        account_id="slack:T123:U999",
        team_id="T123",
        user_id="U999",
        label="workspace",
    )
    result = module.migrate_sqlite(db_path, account, make_backup=False)

    assert result["slack_entities_rewritten"] == 2
    assert result["canonical_persons_rewritten"] == 1
    assert result["sync_cursors_rewritten"] == 1

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT entity_type, platform, platform_entity_id, metadata FROM entities ORDER BY id"
    ).fetchall()
    assert rows[0][2] == "T123/C123"
    assert rows[1][2] == "T123/C123:1712345678.123"
    assert rows[2][2] == "slack:T123/U999"
    assert '"team_id": "T123"' in rows[0][3]
    assert '"account_id": "slack:T123:U999"' in rows[1][3]

    cursor_rows = conn.execute("SELECT source, cursor FROM sync_state").fetchall()
    assert cursor_rows == [("slack:slack:T123:U999", '{"cursor":"abc"}')]
    conn.close()


def test_migrate_sqlite_dry_run_rolls_back(tmp_path: Path) -> None:
    module = _load_script_module()
    db_path = tmp_path / "agentgraph.db"
    conn = _init_db(db_path)
    conn.execute(
        """
        INSERT INTO entities (id, entity_type, platform, platform_entity_id, metadata, last_accessed)
        VALUES ('chan-1', 'Channel', 'slack', 'C123', '{}', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    conn.close()

    account = module.SlackAccount(
        account_id="slack:T123:U999",
        team_id="T123",
        user_id="U999",
        label="workspace",
    )
    result = module.migrate_sqlite(db_path, account, dry_run=True, make_backup=False)

    assert result["slack_entities_rewritten"] == 1

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT platform_entity_id FROM entities WHERE id = 'chan-1'"
    ).fetchone()
    assert row == ("C123",)
    conn.close()
