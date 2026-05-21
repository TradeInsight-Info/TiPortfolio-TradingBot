"""
Flask CLI commands for local development.
"""

import os

import click
from flask import current_app


def register_commands(app) -> None:
    @app.cli.command("sim-reset")
    @click.option("--all", "reset_all", is_flag=True, help="Also delete portfolio config.")
    def sim_reset(reset_all: bool) -> None:
        """Delete simulated rebalance data (requires TIPORTFOLIO_MODE=simulated)."""
        if os.getenv("TIPORTFOLIO_MODE") != "simulated":
            click.echo("Error: sim-reset requires TIPORTFOLIO_MODE=simulated.", err=True)
            raise SystemExit(1)

        from app.portfolio_config import PortfolioConfigRepository
        from app.rebalance import RebalanceRepository

        repo = RebalanceRepository(current_app.config["DB_SESSION"])
        if reset_all:
            deleted = repo.delete_all()
            PortfolioConfigRepository(current_app.config["DB_SESSION"]).delete_all()
            click.echo(f"Deleted {deleted} rebalance event(s) and portfolio config.")
        else:
            deleted = repo.delete_simulated()
            click.echo(f"Deleted {deleted} simulated rebalance event(s).")
