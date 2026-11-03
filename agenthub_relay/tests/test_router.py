import pytest

from agenthub_relay.config import AgentConfig, ConfigSnapshot
from agenthub_relay.router import Router, RoutingError


@pytest.fixture
def router():
    snapshot = ConfigSnapshot(
        version=1,
        agents={1: AgentConfig(1, "hash", active=True)},
        identities={(10, "peer"): 5},
        bindings={(5, 10): 1},
    )
    return Router(snapshot)


def test_resolve_external(router):
    route = router.resolve_external(10, "peer")
    assert route.agent_id == 1
    assert route.user_id == 5
    assert route.thread_key == "agenthub:channel:10:peer:peer:agent:1"


def test_missing_identity(router):
    with pytest.raises(RoutingError) as exc:
        router.resolve_external(10, "unknown")
    assert exc.value.code == "IDENTITY_NOT_FOUND"


def test_missing_binding(router):
    router.snapshot.bindings.clear()
    with pytest.raises(RoutingError) as exc:
        router.resolve_external(10, "peer")
    assert exc.value.code == "BINDING_NOT_FOUND"


def test_inactive_agent(router):
    router.snapshot.agents[1] = AgentConfig(1, "hash", active=False)
    with pytest.raises(RoutingError) as exc:
        router.resolve_external(10, "peer")
    assert exc.value.code == "AGENT_INACTIVE"


def test_resolve_command(router):
    route = router.resolve_command(1, "thread:1")
    assert route.agent_id == 1
    assert route.thread_key == "thread:1"
    assert route.reply_mode == "thread"
