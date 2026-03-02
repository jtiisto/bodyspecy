# bodyspecy

Local-first tool for importing BodySpec DEXA scan PDFs into a SQLite database and exposing them via an MCP server for LLM analysis.

## What it does

1. **Parses** BodySpec DEXA PDF reports — extracts body composition, regional assessment, bone density, muscle balance, VAT, and metabolic rate data
2. **Stores** everything in a local SQLite database with automatic unit conversion (imperial → metric)
3. **Serves** the data through a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server so LLMs like Claude can query your scan history

## Installation

```bash
pip install -e ".[all]"
```

Or install components separately:

```bash
pip install -e .          # parser + database only
pip install -e ".[mcp]"   # add MCP server support
pip install -e ".[dev]"   # add dev/test tools
```

Requires Python 3.10+.

## Usage

### Import PDF reports

```bash
bodyspecy-import ~/diagnostics/bodyspec-results_01-23-2026.pdf
bodyspecy-import ~/diagnostics/bodyspec-results_*.pdf
bodyspecy-import --database ~/custom/path.db report.pdf
```

Scans are stored in `~/.bodyspecy/bodyspec.db` by default. Duplicate imports (same scan date) are upserted.

### Start the MCP server

```bash
bodyspecy-mcp server
bodyspecy-mcp server --database ~/custom/path.db
bodyspecy-mcp server --transport sse
```

The database path can also be set via the `BODYSPECY_DB_PATH` environment variable.

### Claude Code / Claude Desktop configuration

Add to your MCP settings:

```json
{
  "mcpServers": {
    "bodyspecy": {
      "command": "bodyspecy-mcp",
      "args": ["server"]
    }
  }
}
```

## MCP tools

| Tool | Description |
|------|-------------|
| `explore_database_structure` | See available tables, row counts, and date ranges |
| `get_table_details` | Column schema and sample data for a table |
| `get_scan_summary` | Quick overview: scan count, latest metrics, first-to-latest trends |
| `get_body_composition_trends` | Time-series of body fat, lean mass, weight, RMR, VAT across all scans |
| `get_regional_comparison` | Body composition by region (arms, legs, trunk, etc.) or region trends over time |
| `get_bone_density_summary` | BMD by anatomical region with T/Z-score interpretation (WHO thresholds) |
| `execute_sql_query` | Run custom read-only SQL queries against the database |

## Database schema

All values are stored in metric units (kg, cm, g/cm²).

- **scans** — one row per DEXA scan (body fat %, mass, lean mass, BMC, RMR, android/gynoid fat, VAT, bone density summary)
- **scan_regions** — body composition by region (arms, legs, trunk, android, gynoid, total, right/left arm, right/left leg)
- **scan_bone_density** — BMD by bone region (head, arms, legs, trunk, ribs, spine, pelvis, total) with T/Z-scores

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
