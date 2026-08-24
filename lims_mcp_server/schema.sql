-- SQLite schema for the LIMS Food Analysis MCP server.
-- Kept intentionally small: clients, samples, the catalog of analysis
-- parameters the lab tests for, and the individual results tied to a
-- sample + parameter pair.

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    contact_email TEXT,
    phone TEXT,
    address TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_code TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    food_type TEXT NOT NULL,
    received_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('received', 'in_analysis', 'finalized')) DEFAULT 'received',
    requested_analyses TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    unit TEXT,
    method TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id INTEGER NOT NULL REFERENCES samples(id),
    parameter_id INTEGER NOT NULL REFERENCES analysis_parameters(id),
    value TEXT,
    result_status TEXT NOT NULL CHECK (result_status IN ('pass', 'fail', 'pending')) DEFAULT 'pending',
    analyzed_date TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
CREATE INDEX IF NOT EXISTS idx_samples_received_date ON samples(received_date);
CREATE INDEX IF NOT EXISTS idx_results_sample_id ON results(sample_id);
