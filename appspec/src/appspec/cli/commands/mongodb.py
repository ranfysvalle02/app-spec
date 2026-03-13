"""MongoDB persistence commands: push, search, stats, audit."""

from __future__ import annotations

import click
from rich.table import Table

from appspec.cli.main import main, console, _load_spec


@main.command()
@click.option("--uri", required=True, help="MongoDB connection URI")
def push(uri: str):
    """Persist the current spec to MongoDB."""
    import asyncio

    spec, folder = _load_spec()

    async def _push():
        from appspec.store.mongodb import AppSpecStore

        store = AppSpecStore(uri)
        await store.connect()
        try:
            doc_id = await store.persist(spec)
            console.print(f"\n[green]Pushed spec to MongoDB: {doc_id}[/green]")
        finally:
            await store.close()

    asyncio.run(_push())


@main.command("search")
@click.argument("query")
@click.option("--uri", required=True, help="MongoDB connection URI")
@click.option("--limit", default=10, help="Maximum results")
def search_specs(query: str, uri: str, limit: int):
    """Full-text search across all specs in MongoDB."""
    import asyncio

    async def _search():
        from appspec.store.mongodb import AppSpecStore

        store = AppSpecStore(uri)
        await store.connect()
        try:
            results = await store.search(query, limit=limit)
            if not results:
                console.print("[yellow]No matching specs found.[/yellow]")
                return
            table = Table(title=f"Search: '{query}'")
            table.add_column("Slug", style="bold cyan")
            table.add_column("App Name")
            table.add_column("Description")
            table.add_column("Score", justify="right")
            for doc in results:
                table.add_row(
                    doc.get("slug", ""),
                    doc.get("app_name", ""),
                    (doc.get("description", "") or "")[:60],
                    f"{doc.get('score', 0):.2f}",
                )
            console.print(table)
        finally:
            await store.close()

    asyncio.run(_search())


@main.command("stats")
@click.option("--uri", required=True, help="MongoDB connection URI")
def stats(uri: str):
    """Show analytics across all specs stored in MongoDB."""
    import asyncio

    async def _stats():
        from appspec.store.mongodb import AppSpecStore

        store = AppSpecStore(uri)
        await store.connect()
        try:
            data = await store.analytics()
            table = Table(title="AppSpec Analytics")
            table.add_column("Metric", style="bold")
            table.add_column("Value", justify="right")
            table.add_row("Total Specs", str(data.get("total_specs", 0)))
            table.add_row("Total Entities", str(data.get("total_entities", 0)))
            table.add_row("Total Endpoints", str(data.get("total_endpoints", 0)))
            table.add_row("Auth Enabled", str(data.get("auth_enabled_count", 0)))
            if data.get("total_specs", 0) > 0:
                avg_entities = data["total_entities"] / data["total_specs"]
                avg_endpoints = data["total_endpoints"] / data["total_specs"]
                table.add_row("Avg Entities/Spec", f"{avg_entities:.1f}")
                table.add_row("Avg Endpoints/Spec", f"{avg_endpoints:.1f}")
                auth_pct = (data["auth_enabled_count"] / data["total_specs"]) * 100
                table.add_row("Auth Coverage", f"{auth_pct:.0f}%")
            console.print(table)
        finally:
            await store.close()

    asyncio.run(_stats())


@main.command("audit")
@click.option("--uri", required=True, help="MongoDB connection URI")
def audit(uri: str):
    """Run governance audit across all specs in MongoDB."""
    import asyncio

    async def _audit():
        from appspec.store.mongodb import AppSpecStore

        store = AppSpecStore(uri)
        await store.connect()
        try:
            findings = await store.audit()
            if not findings:
                console.print("\n[green]No governance issues found.[/green]")
                return

            table = Table(title="Governance Audit")
            table.add_column("Slug", style="bold cyan")
            table.add_column("Severity")
            table.add_column("Issue")
            table.add_column("Detail")
            for f in findings:
                severity_style = "red" if f["severity"] == "warning" else "yellow"
                table.add_row(
                    f["slug"],
                    f"[{severity_style}]{f['severity'].upper()}[/{severity_style}]",
                    f["issue"],
                    f.get("detail", ""),
                )
            console.print(table)
            console.print(f"\n{len(findings)} finding(s) across stored specs.")
        finally:
            await store.close()

    asyncio.run(_audit())
