from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from .. import db

router = APIRouter()


class TariffIn(BaseModel):
    utility_type: str = "strom"
    name: str | None = None
    grundpreis_monat: float
    arbeitspreis_ct_kwh: float


@router.get("")
def get_current_tariff(utility_type: str = "strom"):
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT * FROM tariffs WHERE utility_type = ? AND valid_from <= ? ORDER BY valid_from DESC LIMIT 1",
            (utility_type, datetime.now().isoformat()),
        )
        row = cur.fetchone()
        return dict(row) if row else None


@router.put("")
def set_tariff(tariff: TariffIn):
    now = datetime.now().isoformat()
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO tariffs (utility_type, name, grundpreis_monat, arbeitspreis_ct_kwh, valid_from) "
            "VALUES (?, ?, ?, ?, ?)",
            (tariff.utility_type, tariff.name, tariff.grundpreis_monat, tariff.arbeitspreis_ct_kwh, now),
        )
        cur.execute("SELECT * FROM tariffs WHERE id = ?", (cur.lastrowid,))
        return dict(cur.fetchone())
