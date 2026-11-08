"""Restarting the console must respect a user's removal of the bundled version."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.run_models import WorkflowRegistration
from app.run_store import RunStore

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'workflows/chrome-wikipedia-football.v1.json'


def run_seed(monkeypatch, database_dsn):
    monkeypatch.setenv('EMULYTIX_DATABASE_URL', database_dsn)
    script = (ROOT / 'scripts/start-console.sh').read_text()
    code = script.split("exec -T console-api python -c '\n", 1)[1].split("\n'", 1)[0]
    exec(compile(code.replace('/workflows/chrome-wikipedia-football.v1.json', str(TEMPLATE)), 'startup-workflow-seed', 'exec'), {})


def test_startup_keeps_a_removed_bundled_version_removed(database_dsn, monkeypatch, capsys):
    run_seed(monkeypatch, database_dsn)
    assert 'disponible' in capsys.readouterr().out
    store = RunStore(database_dsn)
    store.delete_workflow('chrome-wikipedia-football', 1, None)
    deleted = store.get_workflow('chrome-wikipedia-football', 1)['deleted_at']
    run_seed(monkeypatch, database_dsn)
    assert 'disponible' not in capsys.readouterr().out
    assert store.list_workflows(100, 0) == []
    assert store.get_workflow('chrome-wikipedia-football', 1)['deleted_at'] == deleted


def test_startup_still_detects_conflicting_bundled_content(database_dsn, monkeypatch):
    workflow = WorkflowRegistration.model_validate_json(TEMPLATE.read_text())
    workflow.steps[0].id = 'different-first-step'
    RunStore(database_dsn).register_workflow(workflow)
    with pytest.raises(HTTPException) as error:
        run_seed(monkeypatch, database_dsn)
    assert error.value.status_code == 409
