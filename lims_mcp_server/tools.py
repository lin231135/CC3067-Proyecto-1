"""Business logic for the LIMS Food Analysis MCP server's five tools.

Each public tool function receives the already-parsed `arguments` dict from
a `tools/call` request and returns a plain dict. `protocol.py` is
responsible for turning that dict into the MCP `content` array -- this
module only knows about the laboratory domain and SQLite.
"""
import json
from datetime import date

from .database import get_connection


class ToolError(Exception):
    """Raised for any user-facing tool failure (bad input, not found, etc.).

    Handled by protocol.py and reported back as an MCP tool result with
    isError=true, NOT as a JSON-RPC protocol-level error -- a wrong sample
    code is a normal, expected outcome for an LLM to see and react to.
    """


PARAMETER_CODES = [
    "ph", "fecal_coliforms", "salmonella", "total_aerobic_count", "moisture",
    "water_activity", "staph_aureus", "e_coli", "listeria", "yeast_mold",
]

PARAMETER_LABELS = {
    "ph": "pH",
    "fecal_coliforms": "Coliformes fecales",
    "salmonella": "Salmonella spp.",
    "total_aerobic_count": "Recuento de aerobios totales",
    "moisture": "Humedad",
    "water_activity": "Actividad de agua (aw)",
    "staph_aureus": "Staphylococcus aureus",
    "e_coli": "Escherichia coli",
    "listeria": "Listeria monocytogenes",
    "yeast_mold": "Mohos y levaduras",
}

TOOL_DEFINITIONS = [
    {
        "name": "register_sample",
        "description": "Register a new food sample received by the laboratory for analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "Name of the client/company submitting the sample.",
                },
                "food_type": {
                    "type": "string",
                    "description": "Type of food product, e.g. 'queso fresco', 'pollo crudo'.",
                },
                "requested_analyses": {
                    "type": "array",
                    "items": {"type": "string", "enum": PARAMETER_CODES},
                    "minItems": 1,
                    "description": "Analysis parameter codes requested for this sample.",
                },
                "received_date": {
                    "type": "string",
                    "description": "Date the sample was received, format YYYY-MM-DD. Defaults to today.",
                },
            },
            "required": ["client_name", "food_type", "requested_analyses"],
        },
    },
    {
        "name": "get_sample_status",
        "description": "Get the current status (received, in_analysis, finalized) of a sample by its code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sample_code": {"type": "string", "description": "Sample code, e.g. 'LIMS-2026-0032'."},
            },
            "required": ["sample_code"],
        },
    },
    {
        "name": "get_analysis_results",
        "description": "Get the analysis results (pH, bacterial counts, etc.) recorded for a sample.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sample_code": {"type": "string", "description": "Sample code, e.g. 'LIMS-2026-0032'."},
            },
            "required": ["sample_code"],
        },
    },
    {
        "name": "list_pending_samples",
        "description": (
            "List samples that do not yet have a finalized result, optionally "
            "filtered by a received-date range."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Earliest received_date to include (YYYY-MM-DD)."},
                "date_to": {"type": "string", "description": "Latest received_date to include (YYYY-MM-DD)."},
            },
        },
    },
    {
        "name": "generate_report_summary",
        "description": "Generate a client-ready text report summarizing a sample's results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sample_code": {"type": "string", "description": "Sample code, e.g. 'LIMS-2026-0032'."},
            },
            "required": ["sample_code"],
        },
    },
]


def _require(arguments, field):
    value = arguments.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(f"Missing required argument: '{field}'")
    return value


def _parse_date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolError(f"Invalid date for '{field}': expected YYYY-MM-DD, got {value!r}")


def register_sample(arguments):
    client_name = _require(arguments, "client_name")
    food_type = _require(arguments, "food_type")
    requested = arguments.get("requested_analyses")
    if not isinstance(requested, list) or not requested:
        raise ToolError("'requested_analyses' must be a non-empty list of parameter codes")
    unknown = [code for code in requested if code not in PARAMETER_CODES]
    if unknown:
        raise ToolError(f"Unknown analysis parameter code(s): {unknown}. Valid codes: {PARAMETER_CODES}")

    received_date_str = arguments.get("received_date") or date.today().isoformat()
    received_date = _parse_date(received_date_str, "received_date")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM clients WHERE name = ?", (client_name,))
    row = cur.fetchone()
    if row:
        client_id = row["id"]
    else:
        cur.execute("INSERT INTO clients (name) VALUES (?)", (client_name,))
        client_id = cur.lastrowid

    year = received_date.year
    cur.execute("SELECT COUNT(*) AS n FROM samples WHERE sample_code LIKE ?", (f"LIMS-{year}-%",))
    seq = cur.fetchone()["n"] + 1
    sample_code = f"LIMS-{year}-{seq:04d}"

    cur.execute(
        "INSERT INTO samples (sample_code, client_id, food_type, received_date, status, requested_analyses) "
        "VALUES (?, ?, ?, ?, 'received', ?)",
        (sample_code, client_id, food_type, received_date.isoformat(), json.dumps(requested)),
    )
    conn.commit()

    return {
        "sample_code": sample_code,
        "client_name": client_name,
        "food_type": food_type,
        "received_date": received_date.isoformat(),
        "status": "received",
        "requested_analyses": requested,
    }


def _fetch_sample(cur, sample_code):
    cur.execute(
        "SELECT s.*, c.name AS client_name FROM samples s "
        "JOIN clients c ON c.id = s.client_id WHERE s.sample_code = ?",
        (sample_code,),
    )
    row = cur.fetchone()
    if row is None:
        raise ToolError(f"Sample '{sample_code}' was not found.")
    return row


def get_sample_status(arguments):
    sample_code = _require(arguments, "sample_code")
    conn = get_connection()
    cur = conn.cursor()
    row = _fetch_sample(cur, sample_code)
    return {
        "sample_code": row["sample_code"],
        "client_name": row["client_name"],
        "food_type": row["food_type"],
        "received_date": row["received_date"],
        "status": row["status"],
        "requested_analyses": json.loads(row["requested_analyses"]),
    }


def get_analysis_results(arguments):
    sample_code = _require(arguments, "sample_code")
    conn = get_connection()
    cur = conn.cursor()
    sample = _fetch_sample(cur, sample_code)

    cur.execute(
        "SELECT p.code, p.name, p.unit, r.value, r.result_status, r.analyzed_date "
        "FROM results r JOIN analysis_parameters p ON p.id = r.parameter_id "
        "WHERE r.sample_id = ? ORDER BY p.name",
        (sample["id"],),
    )
    results = [
        {
            "parameter_code": r["code"],
            "parameter_name": r["name"],
            "unit": r["unit"],
            "value": r["value"],
            "status": r["result_status"],
            "analyzed_date": r["analyzed_date"],
        }
        for r in cur.fetchall()
    ]

    return {
        "sample_code": sample["sample_code"],
        "sample_status": sample["status"],
        "results": results,
        "message": None if results else "No results have been recorded for this sample yet.",
    }


def list_pending_samples(arguments):
    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    if date_from:
        _parse_date(date_from, "date_from")
    if date_to:
        _parse_date(date_to, "date_to")

    conn = get_connection()
    cur = conn.cursor()
    query = (
        "SELECT s.sample_code, c.name AS client_name, s.food_type, s.received_date, s.status "
        "FROM samples s JOIN clients c ON c.id = s.client_id "
        "WHERE s.status != 'finalized'"
    )
    args = []
    if date_from:
        query += " AND s.received_date >= ?"
        args.append(date_from)
    if date_to:
        query += " AND s.received_date <= ?"
        args.append(date_to)
    query += " ORDER BY s.received_date"

    cur.execute(query, args)
    samples = [
        {
            "sample_code": r["sample_code"],
            "client_name": r["client_name"],
            "food_type": r["food_type"],
            "received_date": r["received_date"],
            "status": r["status"],
        }
        for r in cur.fetchall()
    ]
    return {"count": len(samples), "samples": samples}


def generate_report_summary(arguments):
    sample_code = _require(arguments, "sample_code")
    conn = get_connection()
    cur = conn.cursor()
    sample = _fetch_sample(cur, sample_code)

    cur.execute(
        "SELECT p.name, p.unit, r.value, r.result_status, r.analyzed_date "
        "FROM results r JOIN analysis_parameters p ON p.id = r.parameter_id "
        "WHERE r.sample_id = ? ORDER BY p.name",
        (sample["id"],),
    )
    rows = cur.fetchall()

    requested_labels = [PARAMETER_LABELS.get(c, c) for c in json.loads(sample["requested_analyses"])]
    lines = [
        "LABORATORY REPORT SUMMARY",
        "=" * 26,
        f"Sample code: {sample['sample_code']}",
        f"Client: {sample['client_name']}",
        f"Food type: {sample['food_type']}",
        f"Received date: {sample['received_date']}",
        f"Status: {sample['status']}",
        "",
        f"Requested analyses: {', '.join(requested_labels)}",
        "",
        "Results:",
    ]

    if not rows:
        lines.append("  (no results recorded yet)")

    pending_count = 0
    fail_count = 0
    for r in rows:
        if r["result_status"] == "pending":
            pending_count += 1
            lines.append(f"  - {r['name']}: pending")
            continue
        if r["result_status"] == "fail":
            fail_count += 1
        unit = f" {r['unit']}" if r["unit"] else ""
        lines.append(f"  - {r['name']}: {r['value']}{unit} ({r['result_status']}) - analyzed {r['analyzed_date']}")

    if fail_count:
        verdict = "FAIL"
    elif pending_count or not rows:
        verdict = "PENDING"
    else:
        verdict = "PASS"

    lines.append("")
    lines.append(f"Overall verdict: {verdict}")
    if pending_count:
        lines.append(f"Note: report is preliminary, {pending_count} parameter(s) still pending.")

    report_text = "\n".join(lines)
    return {"sample_code": sample["sample_code"], "verdict": verdict, "report_text": report_text}


DISPATCH = {
    "register_sample": register_sample,
    "get_sample_status": get_sample_status,
    "get_analysis_results": get_analysis_results,
    "list_pending_samples": list_pending_samples,
    "generate_report_summary": generate_report_summary,
}


def dispatch(name, arguments):
    fn = DISPATCH.get(name)
    if fn is None:
        raise ToolError(f"Unknown tool: '{name}'. Available tools: {list(DISPATCH)}")
    return fn(arguments)
