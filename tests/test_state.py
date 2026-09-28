import json

import pytest

from spreadsheet_cell_art.state import StateError, StateStore, atomic_json, locked


def test_atomic_save_failure_keeps_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json(path, {"old": 1})

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("spreadsheet_cell_art.state.os.replace", fail)
    with pytest.raises(OSError):
        atomic_json(path, {"new": 2})
    assert json.loads(path.read_text()) == {"old": 1}
    assert len(list(tmp_path.iterdir())) == 1


def test_create_state_cannot_overwrite_and_plan_must_match(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore.create(path, {"pixels": [1, 2]}, "input.jpg")
    assert store.data["phase"] == "prepared"
    assert StateStore.load(path, {"pixels": [1, 2]}).data == store.data
    with pytest.raises(StateError, match="一致"):
        StateStore.load(path, {"pixels": [1, 3]})
    with pytest.raises(StateError, match="既に"):
        StateStore.create(path, {}, "other.jpg")


def test_in_flight_creation_is_unknown_on_restart(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore.create(path, {}, "input.jpg")
    store.update(phase="creating")
    restored = StateStore.load(path, {})
    assert restored.data["phase"] == "creation_unknown"


def test_corrupted_state_rejected(tmp_path):
    path = tmp_path / "state.json"
    StateStore.create(path, {"rgb": [1, 2, 3]}, "input.jpg")
    data = json.loads(path.read_text())
    data["plan"]["rgb"][0] = 99
    path.write_text(json.dumps(data))
    with pytest.raises(StateError):
        StateStore.load(path)


def test_same_output_cannot_be_locked_twice(tmp_path):
    with locked(tmp_path):
        with pytest.raises(StateError, match="実行中"):
            with locked(tmp_path):
                pytest.fail("lock was bypassed")
    with locked(tmp_path):
        pass


def test_inspection_before_lock_does_not_modify_state(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore.create(path, {}, "input.jpg")
    store.update(phase="creating")
    before = path.read_bytes()
    StateStore.load(path, recover=False)
    assert path.read_bytes() == before
