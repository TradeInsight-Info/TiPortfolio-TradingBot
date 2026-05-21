"""
Flask CLI commands for local development.
"""

import os

import click
from flask import current_app


def register_commands(app) -> None:
    @app.cli.command("sim-reset")
    def sim_reset() -> None:
        """Delete all rebalance events and portfolio config (requires TIPORTFOLIO_MODE=simulated)."""
        if os.getenv("TIPORTFOLIO_MODE") != "simulated":
            click.echo("Error: sim-reset requires TIPORTFOLIO_MODE=simulated.", err=True)
            raise SystemExit(1)

        from app.portfolio_config import PortfolioConfigRepository
        from app.rebalance import RebalanceRepository

        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        deleted = repo.delete_all()
        PortfolioConfigRepository(current_app.config["DB_SESSION"]).delete_all()
        click.echo(f"Deleted {deleted} rebalance event(s) and portfolio config.")
