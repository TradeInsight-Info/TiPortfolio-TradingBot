import logging
import os
from flask import Flask
from dotenv import load_dotenv
from app.database import init_db
from app import models, portfolio_config  # noqa: F401

load_dotenv()

REQUIRED_VARS = ["ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_MODE"]

def create_app():
    # Check required env vars at startup, not at runtime
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    # Set up logging — must be called before any logger.info/debug/warning
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app = Flask(__name__)
    app.config["ALPACA_API_KEY"]    = os.getenv("ALPACA_API_KEY")
    app.config["ALPACA_API_SECRET"] = os.getenv("ALPACA_API_SECRET")
    app.config["ALPACA_MODE"]       = os.getenv("ALPACA_MODE")
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

    allowed_origins = app.config["ALLOWED_ORIGINS"]
    if allowed_origins:
        from flask_cors import CORS
        CORS(app, origins=allowed_origins.split(","), methods=["GET"])

    return app