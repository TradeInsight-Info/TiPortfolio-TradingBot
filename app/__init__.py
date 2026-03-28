import os
from flask import Flask
from dotenv import load_dotenv
from app.database import init_db
from app import models

load_dotenv()

REQUIRED_VARS = ["ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_MODE"]

def create_app():
    # Check required env vars at startup, not at runtime
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing)}")

    app = Flask(__name__)
    app.config["ALPACA_API_KEY"]    = os.getenv("ALPACA_API_KEY")
    app.config["ALPACA_API_SECRET"] = os.getenv("ALPACA_API_SECRET")
    app.config["ALPACA_MODE"]       = os.getenv("ALPACA_MODE")

    init_db(app)
    
    from app.routes import bp
    app.register_blueprint(bp)

    return app