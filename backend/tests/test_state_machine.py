import itertools

import pytest

from app.state_machine import InvalidTransition, State, can_transition, transition

S = State
ALLOWED = {
    (S.DISPATCHED, S.EN_ROUTE_PICKUP), (S.DISPATCHED, S.CANCELLED),
    (S.EN_ROUTE_PICKUP, S.AT_SCENE), (S.EN_ROUTE_PICKUP, S.CANCELLED),
    (S.AT_SCENE, S.TRANSPORTING_PATIENT), (S.AT_SCENE, S.CANCELLED),
    (S.TRANSPORTING_PATIENT, S.AT_HOSPITAL),
    (S.AT_HOSPITAL, S.COMPLETED),
}


@pytest.mark.parametrize("src,dst", list(itertools.product(State, State)))
def test_every_pair(src, dst):
    if (src, dst) in ALLOWED:
        assert transition(src, dst) == dst
    else:
        assert not can_transition(src, dst)
        with pytest.raises(InvalidTransition):
            transition(src, dst)


@pytest.mark.parametrize("src", [S.COMPLETED, S.CANCELLED])
def test_terminal_accepts_none(src):
    assert not any(can_transition(src, d) for d in State)


def test_driver_mock_matches_state_machine():
    import importlib.util
    from pathlib import Path
    from app.state_machine import TRANSITIONS, required_role
    sp = importlib.util.spec_from_file_location("mock_server", Path(__file__).resolve().parent.parent / "web/driver/mock_server.py")
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    assert m.FLOW == {s.value: sorted(n.value for n in x if required_role(n) == "driver") for s, x in TRANSITIONS.items()}
