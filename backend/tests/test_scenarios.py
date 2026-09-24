"""Integration: run every canonical simulator scenario against Mongo."""

import pytest

from verbal.simulator.scenarios import run_all


@pytest.mark.asyncio
async def test_all_scenarios_pass():
    results = await run_all()
    failures = [r for r in results if not r["passed"]]
    assert not failures, f"Scenario failures: {failures}"
    assert len(results) >= 10
