#!/usr/bin/env python3
"""Tests that tool.yaml declares every field the area tools can actually author.

A tool.yaml property is the ONLY way a caller learns a parameter exists. A field
the handler reads but the schema omits is unreachable through MCP, and nothing
else in this repo notices: the handler still works when called directly, the
unit tests still pass, and the parameter is simply invisible.

That is not hypothetical. Adding `type` to the area tools replaced the
`priority` block instead of sitting beside it, and priority became unsettable
through plan_area_new and plan_area_describe.

Usage:
    python3 test_tool_schema.py
"""

from __future__ import annotations

from pathlib import Path
import sys

import yaml

MODULE_DIR = Path(__file__).resolve().parent

# Every field an area can be authored with. Adding a column to `areas` that a
# caller is meant to set means adding it here too.
AUTHORABLE_AREA_FIELDS = {
    "description", "class", "type", "priority", "scope", "watch", "depends",
}

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{suffix}")


def main():
    print("Testing tool.yaml area schemas\n")
    spec = yaml.safe_load((MODULE_DIR / "tool.yaml").read_text())
    tools = {t["name"]: t for t in spec["tools"]}

    for tool_name in ("plan_area_new", "plan_area_describe"):
        props = set(tools[tool_name]["inputSchema"]["properties"])
        missing = sorted(AUTHORABLE_AREA_FIELDS - props)
        report(f"{tool_name} declares every authorable field",
               not missing,
               f"missing: {missing}" if missing else f"has {sorted(props)}")

    # Batch mode authors the same fields through its own nested schema, which is
    # a separate copy and drifts independently of the single-area one.
    batch = set(tools["plan_area_new"]["inputSchema"]["properties"]
                ["items"]["items"]["properties"])
    # The batch item spells description as description_md.
    batch_expected = (AUTHORABLE_AREA_FIELDS - {"description"}) | {"description_md"}
    missing = sorted(batch_expected - batch)
    report("plan_area_new items[] declares every authorable field",
           not missing,
           f"missing: {missing}" if missing else f"has {sorted(batch)}")

    # The closed sets must agree between the two tools, or the same value is
    # settable at create time and refused at update time.
    enums = {n: tools[n]["inputSchema"]["properties"].get("type", {}).get("enum")
             for n in ("plan_area_new", "plan_area_describe")}
    enums["items"] = (tools["plan_area_new"]["inputSchema"]["properties"]["items"]
                      ["items"]["properties"].get("type", {}).get("enum"))
    same = len({tuple(v) if v else None for v in enums.values()}) == 1
    report("the type enum is identical in all three declarations", same,
           f"{enums}" if not same else f"{enums['plan_area_new']}")

    total = passed + failed
    print(f"\n{total} checks, {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
