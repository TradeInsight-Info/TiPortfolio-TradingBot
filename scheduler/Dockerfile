FROM python:3.12-slim

RUN pip install --no-cache-dir tiportfolio

WORKDIR /app

COPY strategies/ /app/strategies/

CMD ["python", "/app/strategies/market_vix_rebalance.py"]
