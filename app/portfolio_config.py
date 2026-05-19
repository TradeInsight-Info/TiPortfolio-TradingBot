from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Generator

from sqlalchemy import Column, Integer, Numeric, DateTime
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base


class PortfolioConfig(Base):
    __tablename__ = "portfolio_config"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    initial_amount = Column(Numeric(12, 4), nullable=False)
    recorded_at    = Column(DateTime(timezone=True), nullable=False)


class PortfolioConfigRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _tx(self) -> Generator[Session, None, None]:
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self) -> PortfolioConfig | None:
        with self._tx() as session:
            row = session.query(PortfolioConfig).first()
            if row is not None:
                session.expunge(row)
            return row

    def get_initial_amount(self) -> Decimal | None:
        row = self.get()
        return Decimal(str(row.initial_amount)) if row else None

    def set_initial_amount(self, amount: Decimal) -> None:
        with self._tx() as session:
            row = session.query(PortfolioConfig).first()
            if row is None:
                session.add(PortfolioConfig(
                    initial_amount=amount,
                    recorded_at=datetime.now(timezone.utc),
                ))
            else:
                row.initial_amount = amount
