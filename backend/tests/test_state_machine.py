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


def test_driver_app_labels_every_state():
    # The driver app has a Bangla and an English label per state; a new state must get both.
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "web/driver/app.js").read_text(encoding="utf-8")
    bn, en = re.search(r"const SL = \{\n  bn: \{(.*?)\},\n  en: \{(.*?)\},", js, re.S).groups()
    for labels in (bn, en):
        assert set(re.findall(r"([A-Z_]+):", labels)) == {s.value for s in State}
