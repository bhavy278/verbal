"""Verbal text simulator CLI.

Commands:
  * ``seed-catalog``   — load + persist the pilot pizza menu
  * ``run-scenarios``  — run the >=10 canonical scenarios as a test suite
  * ``repl``           — interactive voice-style ordering over the mock agent
"""

from __future__ import annotations

import asyncio

import typer

from ..catalog.loader import seed_catalog
from ..voice.orchestrator import SimulateOrchestrator
from ..config import get_settings
from .scenarios import run_all

app = typer.Typer(help="Verbal text simulator")


@app.command("seed-catalog")
def seed_catalog_cmd() -> None:
    """Load and persist the pilot pizza menu fixture."""
    catalog = asyncio.run(seed_catalog())
    typer.echo(f"Seeded catalog {catalog.id} with {len(catalog.items)} items.")


@app.command("run-scenarios")
def run_scenarios_cmd() -> None:
    """Run every canonical scenario and report pass/fail."""
    results = asyncio.run(run_all())
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        extra = r.get("detail") if r["passed"] else r.get("error")
        typer.echo(f"[{mark}] {r['scenario']}: {extra}")
    typer.echo(f"\n{passed}/{len(results)} scenarios passed.")
    if passed != len(results):
        raise typer.Exit(code=1)


@app.command("repl")
def repl_cmd(tenant: str = typer.Option(None, help="Tenant id")) -> None:
    """Interactive ordering session driven by the mock voice agent."""
    asyncio.run(_repl(tenant or get_settings().default_tenant_id))


async def _repl(tenant_id: str) -> None:
    await seed_catalog()
    orch = SimulateOrchestrator(tenant_id)
    greeting = await orch.start()
    typer.echo(f"\n\U0001F355 {greeting['reply']}")
    typer.echo("(type your order; 'quit' to exit)\n")
    loop = asyncio.get_event_loop()
    while True:
        try:
            text = await loop.run_in_executor(None, input, "you> ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() in ("quit", "exit"):
            break
        result = await orch.handle_user(text)
        typer.echo(f"verbal> {result['reply']}")
        if result.get("tool_calls"):
            names = ", ".join(tc["tool"] for tc in result["tool_calls"])
            typer.echo(f"        [tools: {names}]")
        order = result.get("order")
        if order and order.get("quote"):
            typer.echo(f"        [total: {order['quote']['total']['display']} | status: {order['status']}]")
    await orch.end()
    typer.echo("\nGoodbye!")


if __name__ == "__main__":
    app()
