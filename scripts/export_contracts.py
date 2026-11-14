"""Export deterministic OpenAPI and web fixtures from the Python source of truth."""

import argparse
import json

from api.config import ROOT, load_profiles
from api.main import app, compare, export, investigation, list_investigations, meta, rank
from api.models import AnswerEvent, DoneEvent, ProgressEvent, TestList


def outputs() -> dict:
    schema = app.openapi()
    for model in [ProgressEvent, AnswerEvent, DoneEvent]:
        fragment = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = fragment.pop("$defs", {})
        schema["components"]["schemas"].update(definitions)
        schema["components"]["schemas"][model.__name__] = fragment
    schema["paths"]["/chat"]["post"]["x-sse-events"] = {
        "progress": {"$ref": "#/components/schemas/ProgressEvent"},
        "answer": {"$ref": "#/components/schemas/AnswerEvent"},
        "done": {"$ref": "#/components/schemas/DoneEvent"},
    }
    fixture = {
        "meta": meta().model_dump(mode="json"),
        "profiles": load_profiles().model_dump(mode="json"),
        "investigations": list_investigations().model_dump(mode="json"),
        "investigation": investigation("PSI-69").model_dump(mode="json"),
        "rank": rank().model_dump(mode="json"),
        "tests": TestList(items=[], total=0, limit=100, offset=0).model_dump(mode="json"),
        "compare": compare("PSI-26,PSI-25").model_dump(mode="json"),
        "export": export("json").model_dump(mode="json"),
    }
    events = [
        (
            "progress",
            ProgressEvent(stage="retrieval", message="Offline contract mock; no LLM called."),
        ),
        (
            "answer",
            AnswerEvent(
                text=(
                    "Insufficient evidence: Phase 2 contains catalogue metadata, "
                    "not reviewed experimental findings."
                ),
                status="insufficient_evidence",
                citations=[],
            ),
        ),
        ("done", DoneEvent(finish_reason="insufficient_evidence")),
    ]
    return {
        ROOT / "docs/contracts/openapi.json": json.dumps(schema, indent=2) + "\n",
        ROOT / "web/public/fixtures.json": json.dumps(fixture, indent=2) + "\n",
        ROOT / "snapshots/sample/responses.json": json.dumps(fixture, indent=2) + "\n",
        ROOT / "snapshots/sample/chat.sse": "".join(
            f"event: {name}\ndata: {event.model_dump_json()}\n\n" for name, event in events
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, text in outputs().items():
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if stale:
        parser.exit(1, "Stale generated files: " + ", ".join(stale) + "\nRun make contracts.\n")
    print("Contract artifacts match." if args.check else "Contract artifacts exported.")


if __name__ == "__main__":
    main()
