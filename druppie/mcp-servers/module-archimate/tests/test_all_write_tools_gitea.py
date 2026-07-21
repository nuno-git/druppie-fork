"""End-to-end smoke test of EVERY archimate write tool over the Gitea flow.

Captures the real @mcp.tool wrappers via a fake MCP, drives them against an
in-memory GiteaFileStore, and asserts each returns success. This exercises the
new keyword-only signatures, the repo_owner/repo_name injection contract, and
the get()->mutate->persist() (model + SVG push) cycle without any network.

Run with:
    python3 druppie/mcp-servers/module-archimate/tests/test_all_write_tools_gitea.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
os.environ["MODELS_DIR"] = str(MODELS_DIR)


def _load_v1():
    v1 = Path(__file__).resolve().parent.parent / "v1"
    pkg = types.ModuleType("amv1")
    pkg.__path__ = [str(v1)]
    sys.modules["amv1"] = pkg
    for name in ("gitea_io", "writer", "svg_export", "write_tools"):
        spec = importlib.util.spec_from_file_location(f"amv1.{name}", v1 / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"amv1.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["amv1.writer"], sys.modules["amv1.write_tools"]


writer, write_tools = _load_v1()


class FakeStore:
    """In-memory stand-in for GiteaFileStore. Keys: (owner, repo, path)."""

    org = "druppie"

    def __init__(self):
        self.files = {}
        self.puts = []

    async def get_file(self, *, owner, repo, path, ref="main"):
        return self.files.get((owner, repo, path), (None, None))

    async def put_file(self, *, owner, repo, path, content, message, branch="main", sha=None):
        self.files[(owner, repo, path)] = (content, f"sha{len(self.files)}")
        self.puts.append(path)
        return {"content": {"sha": f"sha{len(self.files)}"}}


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *, name=None, description=None, meta=None, **_):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return deco


def main():
    store = FakeStore()
    registry = writer.WriteSessionRegistry(MODELS_DIR, store=store)
    writer._REGISTRY = registry
    # write_tools._registry() -> get_registry() singleton; point it at ours.
    write_tools.get_registry = lambda: registry

    mcp = FakeMCP()
    write_tools.register_write_tools(mcp, module_id="archimate", module_version="1.0.0")
    T = mcp.tools

    expected = {
        "create_element", "update_element", "delete_element",
        "create_relationship", "update_relationship", "delete_relationship",
        "add_to_view", "add_connection_to_view", "remove_from_view",
        "get_or_create_wilma_reference", "save_model", "request_full_relayout",
        "add_layered_view", "add_cooperation_view", "validate_view", "assess_layout",
    }
    missing = expected - set(T)
    assert not missing, f"tools not registered: {missing}"

    ctx = dict(session_id="sess-1", repo_owner="alice", repo_name="proj")

    def ok(label, res):
        assert isinstance(res, dict), f"{label}: not a dict: {res!r}"
        assert res.get("success") is True, f"{label} FAILED: {res}"
        print(f"  ok  {label}")
        return res

    async def run():
        r = ok("add_layered_view", await T["add_layered_view"](
            **ctx, name="Blueprint",
            business=[{"name": "Intake", "type": "BusinessProcess"},
                      {"name": "Vergunning", "type": "BusinessObject"}],
            application=[{"name": "Zaaksysteem", "type": "ApplicationComponent"}],
            relationships=[
                {"source": "Zaaksysteem", "target": "Intake", "type": "Serving"},
                {"source": "Intake", "target": "Vergunning", "type": "Access", "access_type": "Write"},
            ],
        ))
        view_id = r["view_id"]
        el_intake = r["element_ids"]["Intake"]

        r = ok("create_element", await T["create_element"](
            **ctx, element_type="ApplicationComponent", name="Notificatie"))
        new_el = r["element_id"]

        ok("update_element", await T["update_element"](
            **ctx, element_id=new_el, name="Notificatieservice", documentation="verstuurt mail"))

        r = ok("create_relationship", await T["create_relationship"](
            **ctx, relationship_type="Serving", source_id=new_el, target_id=el_intake))
        new_rel = r["relationship_id"]

        ok("update_relationship", await T["update_relationship"](
            **ctx, relationship_id=new_rel, name="notifies"))

        ok("add_to_view", await T["add_to_view"](**ctx, view_id=view_id, element_id=new_el))
        ok("add_connection_to_view", await T["add_connection_to_view"](
            **ctx, view_id=view_id, relationship_id=new_rel))
        ok("validate_view", await T["validate_view"](**ctx, view_id=view_id))
        ok("assess_layout", await T["assess_layout"](**ctx, view_id=view_id))
        ok("request_full_relayout", await T["request_full_relayout"](**ctx, view_id=view_id))
        ok("remove_from_view", await T["remove_from_view"](**ctx, view_id=view_id, element_id=new_el))
        ok("delete_relationship", await T["delete_relationship"](**ctx, relationship_id=new_rel))
        ok("delete_element", await T["delete_element"](**ctx, element_id=new_el))

        # The tool that was broken before the fix.
        ok("add_cooperation_view", await T["add_cooperation_view"](
            **ctx, name="Samenwerking",
            peers=[{"name": "GemeenteA", "type": "ApplicationComponent"},
                   {"name": "GemeenteB", "type": "ApplicationComponent"}],
            shared_services=[{"name": "GedeeldeService", "type": "ApplicationService"}],
            relationships=[{"source": "GemeenteA", "target": "GedeeldeService", "type": "Serving"}],
        ))

        ok("get_or_create_wilma_reference", await T["get_or_create_wilma_reference"](
            **ctx, wilma_element_id="id-5a11eb0694ee10bbc9761f54b19841b0"))

        # The layout-service (ELK) is unreachable in this offline test, so
        # view nodes stay at (0,0) and the SVG renderer correctly defers them
        # to the browser. Simulate ELK's output by assigning positions, so the
        # persist() SVG-push branch is genuinely exercised.
        doc = registry._docs[("sess-1", "docs/architecture.archimate")]
        gx = 40
        for node in doc.root.findall("am:views/am:diagrams/am:view/am:node", writer.NS):
            node.set("x", str(gx))
            node.set("y", "40")
            gx += 220
        doc.dirty = True

        r = ok("save_model", await T["save_model"](**ctx))
        assert r["written"] is True, f"save_model did not write: {r}"
        assert ("alice", "proj", "docs/architecture.archimate") in store.files, "model not pushed"
        svgs = [p for p in store.puts if p.startswith("docs/diagrams/") and p.endswith(".svg")]
        assert svgs, f"no SVG exported: {store.puts}"
        print(f"  ok  save_model pushed model + {len(svgs)} SVG(s)")

        r = ok("save_model (idempotent)", await T["save_model"](**ctx))
        assert r["written"] is False, f"expected no-op second save: {r}"

    asyncio.run(run())
    print("\nALL 16 WRITE TOOLS OK")


def test_all_write_tools_gitea():
    """Pytest entry point — drives every write tool over the Gitea flow."""
    main()


if __name__ == "__main__":
    main()
