"""Mission state machine. Pure: no I/O. Source: docs/api-spec/openapi.yaml enum + architecture diagram."""
from enum import Enum


class State(str, Enum):
    DISPATCHED = "DISPATCHED"
    EN_ROUTE_PICKUP = "EN_ROUTE_PICKUP"
    AT_SCENE = "AT_SCENE"
    TRANSPORTING_PATIENT = "TRANSPORTING_PATIENT"
    AT_HOSPITAL = "AT_HOSPITAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


S = State
TRANSITIONS: dict[State, frozenset[State]] = {
    S.DISPATCHED: frozenset({S.EN_ROUTE_PICKUP, S.CANCELLED}),
    S.EN_ROUTE_PICKUP: frozenset({S.AT_SCENE, S.CANCELLED}),
    S.AT_SCENE: frozenset({S.TRANSPORTING_PATIENT, S.CANCELLED}),
    S.TRANSPORTING_PATIENT: frozenset({S.AT_HOSPITAL}),
    S.AT_HOSPITAL: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}
INITIAL = S.DISPATCHED


class InvalidTransition(ValueError):
    pass


def can_transition(src: State, dst: State) -> bool:
    return dst in TRANSITIONS[src]


def transition(src: State, dst: State) -> State:
    if not can_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value}")
    return dst


def required_role(dst: State) -> str:
    """The one authorization rule: only dispatchers cancel; only drivers advance. Used by PATCH and /meta/transitions."""
    return "dispatcher" if dst is State.CANCELLED else "driver"
