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

    # Àrea Camper Barcelona Beach, Cabrera de Mar — 25-27€/24h (low-season rate used), electricity included.
    # Source: park4night.com/en/place/80615
    ("Àrea Camper Barcelona Beach (Cabrera de Mar)", "Barcelona", 25.00, 1),

    # Xirivella Camper Park, Aldaia — all pitches wired, electricity included in the rate.
    # Source: park4night.com/en/place/516337
    ("Xirivella Camper Park (Aldaia)", "Valencia", 20.00, 1),

    # València Puerto parking (1F Sc Puerto) — plain guarded car park, no services.
    # Source: park4night.com/en/place/293507
    ("Parking València Puerto", "Valencia", 2.00, 0),

    # Área Natur Playa, 200m from the beach — base rate without hookup; electricity is a paid add-on.
    # Source: park4night.com/en/place/226739
    ("Área Natur Playa (Alicante)", "Alicante", 14.00, 1),

    # Área Autocaravanas Sevilla, Avenida Maestranza — 100 pitches, official municipal-adjacent area.
    # Source: park4night.com/en/place/399458
    ("Área Autocaravanas Sevilla", "Sevilla", 20.00, 1),

    # Area Camper Granada, Cájar — base rate without hookup; electricity billed at +4€/noche.
    # Source: park4night.com/en/place/241846
    ("Area Camper Granada (Cájar)", "Granada", 18.00, 1),

    # Camper Park Roquetas de Mar — 6A hookup with 4 kWh/día included on every pitch.
    # Source: park4night.com/en/place/174636
    ("Camper Park Roquetas de Mar", "Almería", 19.00, 1),

    # Área Autocaravanas Donosti (Berio) — low-season rate; no electrical hookups on site.
    # Source: park4night.com/en/place/6580
    ("Área Autocaravanas Donosti (Berio)", "San Sebastián", 6.00, 0),

    # Área Camper Bezana, Santa Cruz de Bezana — base rate without hookup; electricity billed at +4€/noche.
    # Source: park4night.com/en/place/651741
    ("Área Camper Bezana (Santander)", "Santander", 17.00, 1),

    # Estrada Os Fortes, A Coruña — free municipal overnight area, water + waste only, no electricity.
    # Source: park4night.com/en/place/439481
    ("Estrada Os Fortes (A Coruña)", "A Coruña", 0.00, 0),

    # Estrada de São Cornélio, Parque das Nações — guarded car park, no electricity.
    # Source: park4night.com/en/place/60576
    ("Estrada de São Cornélio (Lisboa)", "Lisboa", 10.00, 0),

    # Oporto Area Camper, Valbom — base rate without hookup; electricity billed at +5€/noite.
    # Source: park4night.com/en/place/551326
    ("Oporto Area Camper (Valbom)", "Porto", 20.00, 1),

    # ASA Peniche — base rate without hookup; 4A electricity billed at +4€/noite.
    # Source: park4night.com/en/place/35954
    ("ASA Peniche", "Peniche", 11.00, 1),

    # --- Extra density pass (park4night), Costa del Sol / Cádiz ---

    # La Cañada guarded day/night parking, N-340 — free, no hookup.
    # Source: park4night.com/en/place/241570
    ("Parking La Cañada (Marbella, N-340)", "Marbella", 0.00, 0),

    # Central paid parking, Calle Hernando de Carabeo — no electricity offered.
    # Source: park4night search results (place/422371)
    ("Parking Calle Hernando de Carabeo (Nerja)", "Nerja", 18.00, 0),

    # Motorhome plots near Caños de Meca beach — 40m² plots wired for electricity.
    # Source: park4night search results (Conil de la Frontera cluster)
    ("Área Camper Caños de Meca (Conil de la Frontera)", "Conil de la Frontera", 11.00, 1),

    # Asphalt parking, Carretera de Atlanterra — free, no services.
    # Source: park4night.com/es/place/271347
    ("Parking Carretera de Atlanterra (Zahara de los Atunes)", "Zahara de los Atunes", 0.00, 0),

    # --- Extra density pass, Levante / Murcia ---

    # Cabo de Gata Camper Park — low-season base rate; electricity billed at +5€/día.
    # Source: park4night.com/en/place/26189
    ("Cabo de Gata Camper Park", "Cabo de Gata", 10.00, 1),

    # Area Autocaravanas Cartagena — standard pitch without electricity (XXL wired pitch costs 21€).
    # Source: park4night.com/en/place/8284
    ("Area Autocaravanas Cartagena", "Cartagena", 12.00, 1),

    # Area Camper Gasolinera (Shell), Cartagena — electricity included in the rate.
    # Source: park4night.com/en/place/29344
    ("Area Camper Gasolinera Shell (Cartagena)", "Cartagena", 10.00, 1),

    # Calle Murcia open-ground parking, Águilas — free, no hookup.
    # Source: park4night.com/es/place/397763
    ("Parking Calle Murcia (Águilas)", "Águilas", 0.00, 0),

    # Área Autocaravanas Murcia — free municipal area, water fill/drain only.
    # Source: park4night.com/en/place/31723
    ("Área Autocaravanas Murcia", "Murcia", 0.00, 0),

    # --- Extra density pass, Costa Norte (Asturias/Galicia/País Vasco) ---

    # Municipal area, Avenida de la Paz, Llanes — 19 pitches, no electricity.
    # Source: areasac.es / asturias.com area listings
    ("Área Municipal Avenida de la Paz (Llanes)", "Llanes", 3.00, 0),

    # Camperpark Gijón — 62 pitches, all-inclusive rate with electric hookup.
    # Source: park4night.com/en/place/643879
    ("Camperpark Gijón", "Gijón", 24.00, 1),

    # Avenida da Marina Española parking, Vigo — no electricity offered.
    # Source: park4night search results (Vigo cluster)
    ("Parking Avenida da Marina Española (Vigo)", "Vigo", 12.00, 0),

    # Área de autocaravanas de Pontevedra — free municipal area, no electricity.
    # Source: park4night.com/en/place/47889
    ("Área de Autocaravanas de Pontevedra", "Pontevedra", 0.00, 0),

    # Municipal motorhome area, Zarautz — water/waste disposal, no electricity confirmed.
    # Source: park4night search results (Zarautz cluster)
    ("Área Municipal de Autocaravanas de Zarautz", "Zarautz", 5.00, 0),

    # Bilbaocaravanpark — base rate; electricity billed at +4€/día.
    # Source: park4night.com/en/place/17633
    ("Bilbaocaravanpark", "Bilbao", 17.00, 1),

    # --- Extra density pass, Cataluña / Levante / Centro ---

    # Avinguda Catalunya street parking, Tarragona — no services.
    # Source: park4night search results (Tarragona cluster)
    ("Parking Avinguda Catalunya (Tarragona)", "Tarragona", 5.00, 0),

    # Mas Fidel, Amer — low-season rate, no electricity confirmed.
    # Source: park4night search results (Girona/Amer cluster)
    ("Mas Fidel (Amer, Girona)", "Girona", 15.00, 0),

    # Autocaravaning Park Roses — low-season base rate; electricity billed at +4€/24h.
    # Source: park4night.com/en/place/71861
    ("Autocaravaning Park Roses", "Roses", 16.00, 1),

    # Camperplana Playa del Pinar, Castellón — 47 pitches, water + grey/black water, no electricity.
    # Source: park4night.com/en/place/32064
    ("Camperplana Playa del Pinar (Castellón)", "Castellón", 10.00, 0),

    # Área Camper La Rotonda, Peñíscola — no electricity confirmed.
    # Source: park4night.com/en/place/388821
    ("Área Camper La Rotonda (Peñíscola)", "Peñíscola", 13.50, 0),

    # Area Camper Madrid — base rate; electricity billed at +5€/noche.
    # Source: park4night.com/en/place/234143
    ("Area Camper Madrid", "Madrid", 24.00, 1),

    # Área de Autocaravanas de Alcalá de Henares — 1st/2nd night rate, no electricity confirmed.
    # Source: park4night.com/en/place/663723
    ("Área de Autocaravanas de Alcalá de Henares", "Alcalá de Henares", 15.00, 0),

    # --- Extra density pass, Portugal ---

    # Camping Ericeira — base rate for campervan + 2; electricity billed as a separate paid option.
    # Source: park4night.com/en/place/423944
    ("Camping Ericeira", "Ericeira", 27.40, 1),

    # Rua José Florindo free parking, Cascais — no services.
    # Source: park4night.com/en/place/120112
    ("Parking Rua José Florindo (Cascais)", "Cascais", 0.00, 0),

    # Private motorhome plot, Vila Nova de Milfontes — self-sufficient, no electricity.
    # Source: park4night.com/en/place/589090
    ("Área Privada Vila Nova de Milfontes", "Vila Nova de Milfontes", 10.00, 0),

    # Parque Autocaravanas Figueira da Foz — beachfront lot, water tap only, no electricity.
    # Source: park4night.com/en/place/5673
    ("Parque Autocaravanas Figueira da Foz", "Figueira da Foz", 8.00, 0),

    # SulPark Albufeira Caravans — includes water, electricity and services.
    # Source: park4night.com/en/place/478037
    ("SulPark Albufeira Caravans", "Albufeira", 12.00, 1),

    # Algarve Motorhome Park Tavira — 100 pitches ≥70m², individual electrical hookup included.
    # Source: park4night.com/en/place/166229
    ("Algarve Motorhome Park Tavira", "Tavira", 16.00, 1),

    # Rua da Veiga riverside parking, Viana do Castelo — free, no services.
    # Source: park4night search results (Viana do Castelo cluster)
    ("Parking Rua da Veiga (Viana do Castelo)", "Viana do Castelo", 0.00, 0),
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
