import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "campers_poi.db"

# Real overnight camper/motorhome areas, sourced from areasac.es, official
# operator price lists and on-site reviews (checked September 2026). Prices
# are the base overnight rate quoted by each source; some venues charge
# electricity as a separate add-on (noted inline) but has_electricity only
# records whether the hookup is offered on site.
OVERNIGHT_AREAS = [
    # (name, region, price, has_electricity)

    # Área de Málaga Beach, La Cala del Moral — pernocta + electricidad + descarga de aguas.
    # Source: areasac.es/malaga/malaga/malaga_5974_1_ap.html
    ("Área de Málaga Beach (La Cala del Moral)", "Málaga", 16.00, 1),

    # Puerto Deportivo de Chipiona (Cádiz province), Red Andaluza de Áreas de Autocaravanas.
    # Base pernocta ~10€, electricity billed separately at ~0.08€/h.
    # Source: puertosdeandalucia.es (Red Andaluza de Áreas de Autocaravanas)
    ("Área de Autocaravanas Puerto Deportivo de Chipiona", "Cádiz", 10.00, 1),

    # Área de La Marina, Tarifa — no showers/electricity, water fill + drainage only.
    # Source: areasac.es/tarifa/cadiz/tarifa_6605_1_ap.html
    ("Área de La Marina (Tarifa)", "Tarifa", 15.00, 0),

    # Orbitur Sagres, "Quick Stop" motorhome pitch rate (18h-9:30h), low season 2026.
    # Electricity available as a paid add-on (-50% on the Quick Stop rate).
    # Source: official Orbitur Sagres 2026 price list (orbitur.pt)
    ("Orbitur Sagres — Quick Stop autocaravana", "Sagres", 15.25, 1),

    # Camping-Car Park ASA near Praia do Burgau, first motorhome service area in the Algarve.
    # Water/drainage service area; no confirmed per-pitch electrical hookup.
    # Source: cpa-autocaravanas.com / publituris.pt (2026)
    ("ASA Camping-Car Park Lagos (Praia do Burgau)", "Lagos", 20.00, 0),

    # Faro Campervan Park, Montenegro — 27 pitches with water + electricity + WiFi.
    # Source: on-site reviews (TripAdvisor) and farocampervanpark.com
    ("Faro Campervan Park (Montenegro)", "Faro", 13.00, 1),

    # Camper Park Playas de Luz, Isla Cristina (Huelva) — electricity billed separately at 4€/día.
    # Source: areasac.es/isla-cristina/huelva/isla-cristina_6992_1_ap.html
    ("Camper Park Playas de Luz (Isla Cristina)", "Huelva", 12.00, 1),

    # Área del Puerto Deportivo, Ayamonte (Huelva) — electricity billed separately at 1.92€/día.
    # Source: areasac.es/ayamonte/huelva/ayamonte_4675_1_ap.html
    ("Área del Puerto Deportivo de Ayamonte", "Huelva", 13.15, 1),
]

def run_seed():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS overnight_areas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                region TEXT NOT NULL,
                price REAL NOT NULL,
                has_electricity INTEGER NOT NULL
            )
        """)
        cursor.execute("DELETE FROM overnight_areas")
        cursor.executemany(
            "INSERT INTO overnight_areas (name, region, price, has_electricity) VALUES (?, ?, ?, ?)",
            OVERNIGHT_AREAS
        )
        conn.commit()
        print(f"Seeded {len(OVERNIGHT_AREAS)} overnight areas into {DB_PATH}")
    finally:
        conn.close()

if __name__ == "__main__":
    run_seed()
