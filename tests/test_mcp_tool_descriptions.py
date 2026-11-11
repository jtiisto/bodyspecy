"""Nothing in an MCP tool docstring or the server instructions may be hidden
from the client.

FastMCP (4.x, and the 3-series before it) builds a tool's client-visible
`description` from the docstring text before its first structured section, and
turns each `Args:` entry into that parameter's schema `description`. Anything
else, such as a `Returns:` or `Example queries:` section, is cut, and the model
never sees it. A `Word ...:` line directly followed by an indented line is a
pattern the parser can read as a section (it does once a recognised section
such as `Args:` is present), so the contract forbids it outright. A
parenthesised annotation after a parameter name (`limit (int, max 100): ...`)
is dropped by the parser, so the contract forbids that too. The tool
descriptions and the server instructions are the analysis model's whole
manual, so a silent cut there is a real loss.

The contract, checked per tool through the public API on whatever FastMCP is
installed: the description is the whole docstring above a trailing `Args:`
section; `Args:` is last; every parameter is described, and its schema
description is its whole `Args:` entry text (whitespace-normalised). A failure
names the tool: put the text back above `Args:` or into the entry, and never
indent the line directly under a colon line. Flush-left `- ` bullets under it
are safe, and so are their indented continuation lines.

The client cuts, too. Claude Code (the client this server is written for)
loads tools through tool search: at session start the model gets only the tool
names and the server's `instructions`, and a tool's description arrives only
when that tool is loaded, one at a time. It cuts server instructions at 4,096
characters and a description loaded through tool search at 16,384; before
v2.1.295 it cut every description at 2,048. The model sees only the text before
the cut. So the server sends non-empty instructions of at most 4,096
characters (read through a real initialize handshake, as a client reads them),
and every description is at most 2,048 characters, the stricter cut. A
standing rule that holds for every tool lives in full in the instructions; a
fact about one tool stays on that tool. The anti-guessing hint is pinned both
ways: the instructions carry it, and execute_sql_query's description still
carries it, since a description is read on its own.
"""

import inspect
import re

import pytest

from bodyspecy.localdb.db import BodyspecDB
from bodyspecy.mcp.config import MCPConfig
from bodyspecy.mcp.server import create_mcp_server
from tests.mcp_tools import list_tools, server_instructions

EXPECTED_TOOLS = [
    "explore_database_structure",
    "get_table_details",
    "execute_sql_query",
    "get_scan_summary",
    "get_body_composition_trends",
    "get_regional_comparison",
    "get_bone_density_summary",
]
EXPECTED_COUNT = 7

# Claude Code's cuts (see the module docstring).
MAX_INSTRUCTIONS_CHARS = 4096
MAX_DESCRIPTION_CHARS = 2048

# Short stable markers of the anti-guessing hint: confirm columns and region
# values with get_table_details instead of guessing, because a wrong region
# returns 0 rows and no error. Matched whitespace-normalised, so re-wrapping a
# line never trips them.
ANTI_GUESSING_MARKERS = ["get_table_details", "do NOT guess", "0 rows"]

_ARGS_HEADING = re.compile(r"^Args:$", re.MULTILINE)
_ARGS_ENTRY = re.compile(r"^(\w+)(\s*\([^)]*\))?:(.*)$")


@pytest.fixture(scope="module")
def mcp_server(tmp_path_factory):
    """The server, built on an initialised, empty synthetic database."""
    db_path = tmp_path_factory.mktemp("mcp_descriptions") / "bodyspec.db"
    BodyspecDB(db_path)
    return create_mcp_server(MCPConfig(db_path=db_path))


@pytest.fixture(scope="module")
def listed_tools(mcp_server):
    """`{tool name: listed tool}`."""
    return {tool.name: tool for tool in list_tools(mcp_server)}


@pytest.fixture(scope="module")
def instructions(mcp_server):
    """The instructions text as the server's initialize handshake delivers it
    to a client."""
    return server_instructions(mcp_server)


def _split_docstring(doc):
    """Return (text above `Args:`, the `Args:` block's lines or None)."""
    headings = list(_ARGS_HEADING.finditer(doc))
    assert len(headings) <= 1, "more than one `Args:` heading"
    if not headings:
        return doc.strip(), None
    start = headings[0].start()
    return doc[:start].strip(), doc[headings[0].end():].split("\n")[1:]


def _args_entries(args_lines):
    """Return `[(name, annotation or None, text)]` for an `Args:` block: an entry
    is a line at the block's own indent, its text the rest of that line plus its
    more-indented continuation lines."""
    content = [line for line in args_lines if line.strip()]
    assert content, "empty `Args:` section"
    indent = min(len(line) - len(line.lstrip(" ")) for line in content)
    entries = []
    for line in content:
        if len(line) - len(line.lstrip(" ")) == indent:
            match = _ARGS_ENTRY.match(line.strip())
            assert match, f"not an `Args:` entry: {line.strip()!r}"
            entries.append([match.group(1), match.group(2), [match.group(3)]])
        else:
            assert entries, (
                f"continuation line with no entry above it: {line.strip()!r}")
            entries[-1][2].append(line)
    return [(name, annotation, _normalise(" ".join(text)))
            for name, annotation, text in entries]


def _normalise(text):
    return " ".join(text.split())


class TestToolDescriptions:
    def test_server_lists_the_expected_tools(self, listed_tools):
        """A server that lists nothing (or something new) cannot pass vacuously."""
        assert len(listed_tools) == EXPECTED_COUNT
        assert set(listed_tools) == set(EXPECTED_TOOLS)

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_description_is_the_whole_docstring_above_args(self, listed_tools, name):
        tool = listed_tools[name]
        doc = inspect.getdoc(tool.fn)
        assert doc, "tool has no docstring"
        body, _ = _split_docstring(doc)
        assert tool.description == body, (
            "the client-visible description is not the docstring text above "
            "`Args:`: the parser cut a section out of it")

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_args_is_last_and_names_real_parameters(self, listed_tools, name):
        tool = listed_tools[name]
        _, args_lines = _split_docstring(inspect.getdoc(tool.fn))
        properties = tool.parameters.get("properties", {})
        if args_lines is None:
            assert not properties, "a tool with parameters needs an `Args:` section"
            return
        content = [line for line in args_lines if line.strip()]
        assert content, "empty `Args:` section"
        assert all(line.startswith(" ") for line in content), (
            "text follows the `Args:` section: " +
            next(line for line in content if not line.startswith(" ")))
        names = [entry_name for entry_name, _, _ in _args_entries(args_lines)]
        assert len(names) == len(set(names)), f"duplicate `Args:` entries: {names}"
        assert set(names) <= set(properties), (
            f"`Args:` names no such parameter: {sorted(set(names) - set(properties))}")

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_every_parameter_is_described(self, listed_tools, name):
        properties = listed_tools[name].parameters.get("properties", {})
        undescribed = [p for p, schema in properties.items()
                       if not (schema.get("description") or "").strip()]
        assert not undescribed, f"parameters without a description: {undescribed}"

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_description_leads_with_when_to_use(self, listed_tools, name):
        assert listed_tools[name].description.startswith("WHEN TO USE:")

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_args_entries_reach_the_client_whole(self, listed_tools, name):
        """Each entry's text is its parameter's schema description, nothing lost:
        the parser keeps continuation lines (dedented, so compared
        whitespace-normalised) and drops a `name (annotation):` annotation."""
        tool = listed_tools[name]
        _, args_lines = _split_docstring(inspect.getdoc(tool.fn))
        if args_lines is None:
            return
        properties = tool.parameters.get("properties", {})
        for param, annotation, text in _args_entries(args_lines):
            assert annotation is None, (
                f"`{param}{annotation}:`: the parser drops a parenthesised "
                "annotation after the parameter name; put it in the entry text")
            listed = _normalise(properties.get(param, {}).get("description") or "")
            assert listed == text, (
                f"`{param}`: the client gets {listed!r}, the docstring says {text!r}")

    @pytest.mark.parametrize("name", EXPECTED_TOOLS)
    def test_description_fits_the_client_cut(self, listed_tools, name):
        """Claude Code cut every description at 2,048 characters before v2.1.295;
        text past the cut never reaches the model."""
        length = len(listed_tools[name].description)
        assert length <= MAX_DESCRIPTION_CHARS, (
            f"description is {length} characters, over the client's "
            f"{MAX_DESCRIPTION_CHARS}-character cut: move a standing rule to the "
            "server's instructions or tighten the wording")

    def test_execute_sql_query_states_the_anti_guessing_hint(self, listed_tools):
        """A description is read on its own, so the SQL tool keeps the hint, not
        merely a pointer to the instructions."""
        description = _normalise(listed_tools["execute_sql_query"].description)
        missing = [m for m in ANTI_GUESSING_MARKERS if m not in description]
        assert not missing, f"execute_sql_query lost the anti-guessing hint {missing}"


class TestServerInstructions:
    def test_instructions_reach_the_client(self, instructions):
        """The model gets them at session start, before any tool description;
        a server without them starts the session as bare tool names."""
        assert instructions and instructions.strip(), (
            "the initialize handshake carries no instructions")

    def test_instructions_fit_the_client_cut(self, instructions):
        length = len(instructions or "")
        assert length <= MAX_INSTRUCTIONS_CHARS, (
            f"instructions are {length} characters, over the client's "
            f"{MAX_INSTRUCTIONS_CHARS}-character cut")

    def test_instructions_carry_the_anti_guessing_hint(self, instructions):
        """The hint holds for every query, so the instructions carry it too."""
        text = _normalise(instructions or "")
        missing = [m for m in ANTI_GUESSING_MARKERS if m not in text]
        assert not missing, f"the instructions lost the anti-guessing hint {missing}"
