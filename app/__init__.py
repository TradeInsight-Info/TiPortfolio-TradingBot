import logging
import logging.config
import os

from flask import Flask
from dotenv import load_dotenv
from app.database import init_db
from app import models, portfolio_config  # noqa: F401

load_dotenv()

REQUIRED_VARS = ["ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_MODE", "WEBHOOK_SECRET"]

def _setup_logging() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                # Single consistent format for all loggers
                "format": "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        # Suppress werkzeug's own internal timestamp (the bracket part)
        # by overriding its logger — level stays INFO, format is controlled by us
        "loggers": {
            "werkzeug": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False,  # prevent double-printing
            },
        },
    })

def create_app():
    _setup_logging()

    app_mode = os.getenv("TIPORTFOLIO_MODE", "live")

    # Alpaca credentials are only required for live/paper trading
    if app_mode != "simulated":
        missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
        if missing:
            raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    app = Flask(__name__)
    app.config["APP_MODE"]          = app_mode
    app.config["ALPACA_API_KEY"]    = os.getenv("ALPACA_API_KEY", "")
    app.config["ALPACA_API_SECRET"] = os.getenv("ALPACA_API_SECRET", "")
    app.config["ALPACA_MODE"]       = os.getenv("ALPACA_MODE", "paper")
    app.config["WEBHOOK_SECRET"]    = os.getenv("WEBHOOK_SECRET")
    app.config["ALLOWED_ORIGINS"]   = os.getenv("ALLOWED_ORIGINS", "")
    app.config["SENTRY_DSN"]        = os.getenv("SENTRY_DSN")

    sentry_dsn = app.config["SENTRY_DSN"]
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=sentry_dsn, integrations=[FlaskIntegration()], traces_sample_rate=0.1)

    init_db(app)

    from app.routes import bp
    app.register_blueprint(bp)

    from app.webhook import bp as webhook_bp
    app.register_blueprint(webhook_bp)

    from app.benchmark import bp as benchmark_bp
    app.register_blueprint(benchmark_bp)

    from app.positions import bp as positions_bp
    app.register_blueprint(positions_bp)

    from app.commands import register_commands
    register_commands(app)
    allowed_origins = app.config["ALLOWED_ORIGINS"]
    if allowed_origins:
        from flask_cors import CORS
        CORS(app, origins=allowed_origins.split(","), methods=["GET"])

    # Log the active trading mode so the operator can confirm 
    # which account (paper or live) is active without inspecting the env file.
    logging.getLogger(__name__).info(
        "Alpaca trading mode: %s  (base URL: %s)",
        app.config["ALPACA_MODE"],
        "https://paper-api.alpaca.markets" if app.config["ALPACA_MODE"] == "paper"
        else "https://api.alpaca.markets",
    )

    return app