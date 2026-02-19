"""Tests for MCP server tools."""

import asyncio
import json

import pytest

from bodyspecy.localdb.db import BodyspecDB
from bodyspecy.mcp.config import MCPConfig
from bodyspecy.mcp.server import QueryValidator, create_mcp_server


@pytest.fixture
def populated_db(tmp_path, sample_parsed_scan, second_parsed_scan):
    """Create a DB with two scans imported, return the path."""
    db_path = tmp_path / "test.db"
    db = BodyspecDB(db_path)
    db.import_scan(sample_parsed_scan)
    db.import_scan(second_parsed_scan)
    return db_path


@pytest.fixture
def mcp_config(populated_db):
    """MCPConfig pointing to the populated test DB."""
    return MCPConfig(db_path=populated_db)


@pytest.fixture
def mcp_server(mcp_config):
    """FastMCP server instance with tools registered."""
    return create_mcp_server(mcp_config)


def _call_tool(mcp_server, tool_name: str, **kwargs):
    """Call a tool function registered on the MCP server via FastMCP's async API."""
    result = asyncio.run(mcp_server.call_tool(tool_name, kwargs))
    # FastMCP v3 returns ToolResult with structured_content or text content
    if result.structured_content:
        return result.structured_content.get("result", result.structured_content)
    # Fall back to text content
    if result.content:
        text = result.content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return None


class TestExploreDatabase:
    """Test explore_database_structure tool."""

    def test_returns_table_info(self, mcp_server):
        result = _call_tool(mcp_server, "explore_database_structure")
        assert "available_tables" in result

    def test_lists_all_tables(self, mcp_server):
        result = _call_tool(mcp_server, "explore_database_structure")
        tables = result["available_tables"]
        assert "scans" in tables
        assert "scan_regions" in tables
        assert "scan_bone_density" in tables


class TestGetScanSummary:
    """Test get_scan_summary tool."""

    def test_returns_expected_structure(self, mcp_server):
        result = _call_tool(mcp_server, "get_scan_summary")
        assert result["total_scans"] == 2
        assert "date_range" in result
        assert "latest_scan" in result
        assert "trend_first_to_latest" in result


class TestExecuteSqlQuery:
    """Test execute_sql_query tool."""

    def test_valid_select(self, mcp_server):
        result = _call_tool(
            mcp_server,
            "execute_sql_query",
            query="SELECT scan_date, total_body_fat_pct FROM scans ORDER BY scan_date",
        )
        assert isinstance(result, list)
        assert len(result) == 2

    def test_rejects_insert(self, mcp_server):
        with pytest.raises(Exception):
            _call_tool(
                mcp_server,
                "execute_sql_query",
                query="INSERT INTO scans (scan_date) VALUES ('2025-01-01')",
            )

    def test_rejects_delete(self, mcp_server):
        with pytest.raises(Exception):
            _call_tool(
                mcp_server,
                "execute_sql_query",
                query="DELETE FROM scans",
            )

    def test_rejects_drop(self, mcp_server):
        with pytest.raises(Exception):
            _call_tool(
                mcp_server,
                "execute_sql_query",
                query="DROP TABLE scans",
            )

    def test_select_with_where(self, mcp_server):
        result = _call_tool(
            mcp_server,
            "execute_sql_query",
            query="SELECT * FROM scan_bone_density WHERE region = 'total'",
        )
        assert isinstance(result, list)
        assert len(result) == 2


class TestQueryValidator:
    """Test QueryValidator directly."""

    def test_allows_select(self):
        QueryValidator.validate_query("SELECT * FROM scans")

    def test_allows_with(self):
        QueryValidator.validate_query("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_rejects_insert(self):
        with pytest.raises(ValueError):
            QueryValidator.validate_query("INSERT INTO scans VALUES (1)")

    def test_rejects_drop(self):
        with pytest.raises(ValueError):
            QueryValidator.validate_query("DROP TABLE scans")

    def test_rejects_multiple_statements(self):
        with pytest.raises(ValueError):
            QueryValidator.validate_query("SELECT 1; DROP TABLE scans")

    def test_add_row_limit(self):
        result = QueryValidator.add_row_limit("SELECT * FROM scans")
        assert "LIMIT" in result

    def test_preserves_existing_limit(self):
        query = "SELECT * FROM scans LIMIT 10"
        result = QueryValidator.add_row_limit(query)
        assert result == query
