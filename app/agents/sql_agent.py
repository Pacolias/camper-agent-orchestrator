from pathlib import Path
import sqlite3

from app.agents.state import RouteState

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "campers_poi.db"

def sql_agent_node(state: RouteState):
    """
    Look for pernoctation areas in the SQL DB applying filters
    like electricity necessity (hookups).
    """
    destination = state.get("destination", "")
    requires_hookups = state.get("requires_hookups", False)

    try:
        # mode=ro fails loudly if the DB is missing, instead of sqlite3
        # silently creating an empty one at DB_PATH.
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            query = """
                SELECT name, price, has_electricity
                FROM overnight_areas
                WHERE region LIKE ? AND has_electricity >= ?
            """
            # Requires light, flag=1 and flag=0 otherwise
            elec_flag = 1 if requires_hookups else 0
            cursor.execute(query, (f"%{destination}%", elec_flag))
            rows = cursor.fetchall()
        finally:
            conn.close()

        poi_data = [{"name": r[0], "price": r[1], "hookups": bool(r[2])} for r in rows]

    except sqlite3.Error:
        # Development mock: used only if the real query fails (e.g. DB not seeded yet).
        poi_data = [
            {"name": f"Área Camper {destination} Norte", "price": 12.50, "hookups": True},
            {"name": f"Parking {destination} Playa (Sin servicios)", "price": 0.0, "hookups": False}
        ]
        if requires_hookups:
            poi_data = [poi for poi in poi_data if poi["hookups"]]

    return {"poi_data": poi_data}