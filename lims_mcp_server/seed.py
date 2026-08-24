"""Populate the LIMS database with synthetic (but plausible) demo data.

Simulates a food-safety laboratory with 10 recurring clients, a catalog of
10 physicochemical/microbiological parameters, and 50-100 samples spread
over the last ~75 days in varying stages (received / in_analysis /
finalized), each with realistic pass/fail results.

Run with:
    python -m lims_mcp_server.seed [--samples N] [--seed N]
"""
import argparse
import json
import random
from datetime import date, timedelta

from .database import get_connection, get_db_path

CLIENTS = [
    "Alimentos del Sur S.A.",
    "Lacteos San Miguel",
    "Exportadora Agricola Peten",
    "Restaurante El Fogon",
    "Procesadora Avicola Kaqchikel",
    "Panificadora Dona Marta",
    "Embutidos La Ceiba",
    "Congelados del Pacifico",
    "Bebidas Naturales Xelaju",
    "Frutas Tropicales Izabal",
]

FOOD_TYPES = [
    "queso fresco", "leche pasteurizada", "pollo crudo", "carne molida",
    "vegetales congelados", "pan de molde", "embutidos", "jugo natural",
    "cafe tostado", "camaron congelado", "yogurt natural", "salsa picante",
]

# (code, display name, unit, reference method)
PARAMETERS = [
    ("ph", "pH", "", "AOAC 981.12"),
    ("fecal_coliforms", "Coliformes fecales", "NMP/g", "AOAC 966.24"),
    ("salmonella", "Salmonella spp.", "presencia/25g", "AOAC 2016.01"),
    ("total_aerobic_count", "Recuento de aerobios totales", "UFC/g", "AOAC 990.12"),
    ("moisture", "Humedad", "%", "AOAC 925.09"),
    ("water_activity", "Actividad de agua (aw)", "aw", "AOAC 978.18"),
    ("staph_aureus", "Staphylococcus aureus", "UFC/g", "AOAC 2003.07"),
    ("e_coli", "Escherichia coli", "NMP/g", "AOAC 991.14"),
    ("listeria", "Listeria monocytogenes", "presencia/25g", "AOAC 993.09"),
    ("yeast_mold", "Mohos y levaduras", "UFC/g", "AOAC 997.02"),
]

STATUS_CHOICES = ["received", "in_analysis", "finalized"]
STATUS_WEIGHTS = [0.2, 0.3, 0.5]


def _generate_value(code, rng, force_fail):
    """Return (value_str, result_status) for one parameter, biased to fail
    ~12% of the time so demo data has a realistic mix of pass/fail results."""
    if code == "ph":
        v = rng.uniform(2.5, 5.5) if force_fail else rng.uniform(4.0, 7.5)
        return f"{v:.2f}", "fail" if not (3.5 <= v <= 8.5) else "pass"
    if code in ("fecal_coliforms", "e_coli"):
        v = rng.randint(15, 500) if force_fail else rng.randint(0, 10)
        return str(v), "fail" if v > 10 else "pass"
    if code in ("salmonella", "listeria"):
        present = force_fail or rng.random() < 0.05
        return ("Presente", "fail") if present else ("Ausente", "pass")
    if code == "total_aerobic_count":
        v = rng.randint(150000, 900000) if force_fail else rng.randint(100, 90000)
        return str(v), "fail" if v > 100000 else "pass"
    if code == "moisture":
        v = rng.uniform(4.0, 60.0)
        return f"{v:.1f}", "pass"
    if code == "water_activity":
        v = rng.uniform(0.86, 0.99) if force_fail else rng.uniform(0.5, 0.85)
        return f"{v:.2f}", "fail" if v > 0.85 else "pass"
    if code == "staph_aureus":
        v = rng.randint(150, 800) if force_fail else rng.randint(0, 90)
        return str(v), "fail" if v > 100 else "pass"
    if code == "yeast_mold":
        v = rng.randint(1200, 5000) if force_fail else rng.randint(0, 900)
        return str(v), "fail" if v > 1000 else "pass"
    v = rng.randint(0, 100)
    return str(v), "pass"


def seed(num_samples=80, seed_value=42):
    rng = random.Random(seed_value)
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM results")
    cur.execute("DELETE FROM samples")
    cur.execute("DELETE FROM analysis_parameters")
    cur.execute("DELETE FROM clients")

    for name in CLIENTS:
        cur.execute("INSERT INTO clients (name) VALUES (?)", (name,))
    for code, name, unit, method in PARAMETERS:
        cur.execute(
            "INSERT INTO analysis_parameters (code, name, unit, method) VALUES (?, ?, ?, ?)",
            (code, name, unit, method),
        )
    conn.commit()

    cur.execute("SELECT id, name FROM clients")
    client_rows = cur.fetchall()
    cur.execute("SELECT id, code FROM analysis_parameters")
    param_ids = {r["code"]: r["id"] for r in cur.fetchall()}

    today = date.today()
    counters = {}

    for _ in range(num_samples):
        client = rng.choice(client_rows)
        food_type = rng.choice(FOOD_TYPES)
        received_date = today - timedelta(days=rng.randint(0, 75))
        status = rng.choices(STATUS_CHOICES, weights=STATUS_WEIGHTS)[0]
        requested = rng.sample([code for code, *_ in PARAMETERS], k=rng.randint(3, 6))

        year = received_date.year
        counters[year] = counters.get(year, 0) + 1
        sample_code = f"LIMS-{year}-{counters[year]:04d}"

        cur.execute(
            "INSERT INTO samples (sample_code, client_id, food_type, received_date, status, requested_analyses) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sample_code, client["id"], food_type, received_date.isoformat(), status, json.dumps(requested)),
        )
        sample_id = cur.lastrowid

        if status == "received":
            continue  # nothing analyzed yet: no result rows at all

        num_analyzed = len(requested)
        if status == "in_analysis":
            num_analyzed = max(1, round(len(requested) * rng.uniform(0.3, 0.7)))

        for i, code in enumerate(requested):
            param_id = param_ids[code]
            if i >= num_analyzed:
                cur.execute(
                    "INSERT INTO results (sample_id, parameter_id, value, result_status, analyzed_date, notes) "
                    "VALUES (?, ?, NULL, 'pending', NULL, NULL)",
                    (sample_id, param_id),
                )
                continue

            force_fail = rng.random() < 0.12
            value, result_status = _generate_value(code, rng, force_fail)
            analyzed_date = received_date + timedelta(days=rng.randint(1, 4))
            cur.execute(
                "INSERT INTO results (sample_id, parameter_id, value, result_status, analyzed_date, notes) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (sample_id, param_id, value, result_status, analyzed_date.isoformat()),
            )

    conn.commit()
    return num_samples


def main():
    parser = argparse.ArgumentParser(description="Seed the LIMS SQLite database with synthetic data.")
    parser.add_argument("--samples", type=int, default=80, help="Number of samples to generate (default: 80)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)")
    args = parser.parse_args()

    n = seed(num_samples=args.samples, seed_value=args.seed)
    print(f"Seeded database at {get_db_path()} with {n} samples across {len(CLIENTS)} clients.")


if __name__ == "__main__":
    main()
