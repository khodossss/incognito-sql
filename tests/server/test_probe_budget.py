"""The L3 probe budget end to end: it counts accepted probes, never answers."""

from .conftest import GatewayFactory

PROBE = "SELECT id FROM people WHERE full_name > 'M' ORDER BY id"


def test_probes_past_the_budget_are_refused(make_gateway: GatewayFactory) -> None:
    gw = make_gateway("limits: {probe_budget: 2}\n")
    assert "error" not in gw.query(PROBE, "c1")
    assert gw.query("SELECT upper(full_name) FROM people", "c1")["error"] == "pii_operation"
    assert "error" not in gw.query(PROBE, "c2")  # the refused query spent nothing
    assert gw.query(PROBE, "c3")["error"] == "probe_budget"  # the window is the installation's
    assert "error" not in gw.query("SELECT id FROM people ORDER BY id", "c1")  # no probe


STRICT_ONE_PROBE = "protection: strict\nlimits: {probe_budget: 1}\n"


def test_strict_refuses_probes_before_they_spend(make_gateway: GatewayFactory) -> None:
    gw = make_gateway(STRICT_ONE_PROBE)
    for _ in range(3):
        assert gw.query(PROBE, "c1")["error"] == "pii_operation"
