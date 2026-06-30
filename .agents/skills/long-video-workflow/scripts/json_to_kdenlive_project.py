#!/usr/bin/env python3
"""Convert an Agent Workflow JSON prompt/task pack into a Kdenlive project bundle."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Sequence


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def row_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("prompts"), list):
        return list(data["prompts"])
    if isinstance(data.get("tasks"), list):
        return list(data["tasks"])
    if isinstance(data.get("shots"), list):
        return list(data["shots"])
    raise SystemExit("Unsupported JSON: expected prompts[], tasks[], or shots[].")


def output_file_for(row: dict[str, Any]) -> str:
    output = row.get("output") or {}
    if isinstance(output, dict) and output.get("file"):
        return Path(str(output["file"])).name
    if row.get("image_file"):
        return Path(str(row["image_file"])).name
    raise SystemExit(f"Missing output.file/image_file for order {row.get('order') or row.get('id')}.")


def timing_for(row: dict[str, Any]) -> tuple[float, float, float]:
    timing = row.get("timing") or row
    try:
        start = float(timing["start"])
        end = float(timing["end"])
    except Exception as exc:
        raise SystemExit(f"Missing timing.start/timing.end for order {row.get('order') or row.get('id')}.") from exc
    if end <= start:
        raise SystemExit(f"Invalid timing for order {row.get('order') or row.get('id')}: end must be > start.")
    return start, end, round(end - start, 6)


def assert_digits4(file_name: str) -> None:
    if not re.fullmatch(r"\d{4}\.png", file_name):
        raise SystemExit(f"Image file must use 4 digits like 0001.png, got: {file_name}")


def build_storyboard(json_path: Path, images_dir: Path, out_dir: Path, strict_digits4: bool) -> Path:
    data = load_json(json_path)
    rows = sorted(row_items(data), key=lambda row: int(row.get("order") or row.get("id") or 0))
    if not rows:
        raise SystemExit("JSON contains no prompt/task rows.")

    shots = []
    for index, row in enumerate(rows, start=1):
        image_file = output_file_for(row)
        if strict_digits4:
            assert_digits4(image_file)
        image_path = images_dir / image_file
        if not image_path.exists():
            raise SystemExit(f"Missing image for order {index}: {image_path}")
        prompt = str(row.get("prompt") or "")
        if "\n" in prompt or "\r" in prompt:
            raise SystemExit(f"Prompt contains newline for order {index}; prompts must be one line.")
        start, end, duration = timing_for(row)
        shots.append(
            {
                "id": int(row.get("shot_id") or row.get("id") or index),
                "order": int(row.get("order") or index),
                "start": start,
                "end": end,
                "duration": duration,
                "image_file": image_file,
                "visual_kind": row.get("visual_kind", "illustration"),
                "title_text": row.get("title_text", ""),
                "text": row.get("text", ""),
                "context_text": row.get("context_text", ""),
                "prompt": one_line(prompt),
            }
        )

    total_duration = float(data.get("total_duration") or max(shot["end"] for shot in shots))
    storyboard = {
        "schema": "agent-workflow.kdenlive-storyboard.v1",
        "source_json": str(json_path.resolve()),
        "total_duration": total_duration,
        "shot_count": len(shots),
        "timing_source": "agent workflow json",
        "shots": shots,
    }
    out = out_dir / "_kdenlive_storyboard_from_json.json"
    write_json(out, storyboard)
    return out


def find_exporter(explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if path.exists():
            return path
        raise SystemExit(f"Exporter not found: {path}")
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "scripts" / "export_kdenlive_project.py",
        Path.cwd() / "scripts" / "export_kdenlive_project.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise SystemExit("Cannot find scripts/export_kdenlive_project.py. Pass --exporter /path/to/export_kdenlive_project.py.")


def load_exporter(exporter_path: Path):
    spec = importlib.util.spec_from_file_location("export_kdenlive_project", exporter_path)
    if not spec or not spec.loader:
        raise SystemExit(f"Cannot import exporter: {exporter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_kdenlive_project"] = module
    spec.loader.exec_module(module)
    return module


def validate_kdenlive(project_path: Path, fps: int, expected_images: list[str]) -> dict[str, Any]:
    text = project_path.read_text(encoding="utf-8")
    root = ET.parse(project_path).getroot()
    ids = [element.attrib.get("id") for element in root if "id" in element.attrib]
    main_bin = next((e for e in root if e.tag == "playlist" and e.attrib.get("id") == "main_bin"), None)
    if main_bin is None:
        raise SystemExit("Invalid Kdenlive XML: missing main_bin playlist.")
    props = {c.attrib["name"]: c.text or "" for c in main_bin if c.tag == "property" and "name" in c.attrib}
    sequence_id = props.get("kdenlive:docproperties.activetimeline", "")
    sequence = next((e for e in root if e.tag == "tractor" and e.attrib.get("id") == sequence_id), None)
    bad_durations = []
    for prop in root.iter("property"):
        if prop.attrib.get("name") == "kdenlive:duration" and prop.text and ";" in prop.text:
            frame_text = prop.text.rsplit(";", 1)[1]
            if not frame_text.isdigit() or int(frame_text) >= fps:
                bad_durations.append(prop.text)
    media_paths = [
        prop.text or ""
        for prop in root.iter("property")
        if prop.attrib.get("name") == "resource" and prop.text and prop.text.startswith("assets/")
    ]
    image_paths = [path for path in media_paths if path.startswith("assets/images/")]
    checks = {
        "xml_parsed": True,
        "root_version": root.attrib.get("version"),
        "root_producer": root.attrib.get("producer"),
        "root_path": root.attrib.get("root"),
        "has_main_bin": main_bin is not None,
        "doc_version": props.get("kdenlive:docproperties.version"),
        "xml_retain": props.get("xml_retain"),
        "active_timeline": sequence_id,
        "has_active_sequence": sequence is not None,
        "unique_ids": len(ids) == len(set(ids)),
        "contains_absolute_user_path": "/Users/" in text or re.search(r"[A-Za-z]:\\\\", text) is not None,
        "bad_semicolon_durations": bad_durations,
        "image_count": len(image_paths),
        "expected_image_count": len(expected_images),
        "image_files": [Path(path).name for path in image_paths],
        "expected_image_files": expected_images,
        "media_paths_relative": all(path.startswith("assets/") for path in media_paths),
    }
    checks["ok"] = (
        checks["root_version"] == "7.39.0"
        and checks["root_producer"] == "main_bin"
        and checks["root_path"] == "."
        and checks["doc_version"] == "1.1"
        and checks["xml_retain"] == "1"
        and checks["has_active_sequence"]
        and checks["unique_ids"]
        and not checks["contains_absolute_user_path"]
        and not checks["bad_semicolon_durations"]
        and checks["image_files"] == expected_images
        and checks["media_paths_relative"]
    )
    return checks


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Agent Workflow JSON into a self-contained Kdenlive project.")
    parser.add_argument("--json", required=True, help="image_prompts.json, image_tasks.json, or storyboard JSON.")
    parser.add_argument("--images-dir", required=True, help="Folder containing 0001.png, 0002.png, ...")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--project-name", default="AgentWorkflow")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--template-kdenlive", help="Optional sample Kdenlive file to copy metadata/layout from.")
    parser.add_argument("--exporter", help="Path to scripts/export_kdenlive_project.py when this pack is copied elsewhere.")
    parser.add_argument("--allow-non-digits4", action="store_true")
    args = parser.parse_args(argv)

    json_path = Path(args.json).resolve()
    images_dir = Path(args.images_dir).resolve()
    audio_path = Path(args.audio).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    storyboard = build_storyboard(json_path, images_dir, out_dir, strict_digits4=not args.allow_non_digits4)
    storyboard_data = load_json(storyboard)
    expected_images = [shot["image_file"] for shot in storyboard_data["shots"]]

    exporter = load_exporter(find_exporter(args.exporter))
    project = exporter.make_project(
        storyboard_path=storyboard,
        images_dir=images_dir,
        audio_path=audio_path,
        out_dir=out_dir,
        project_name=args.project_name,
        fps=args.fps,
        width=args.width,
        height=args.height,
        template=Path(args.template_kdenlive).resolve() if args.template_kdenlive else None,
    )
    checks = validate_kdenlive(project, args.fps, expected_images)
    report = {
        "schema": "agent-workflow.kdenlive-conversion-report.v1",
        "source_json": str(json_path),
        "storyboard": str(storyboard),
        "project": str(project),
        "bundle": str(out_dir),
        "checks": checks,
    }
    report_path = out_dir / "kdenlive_conversion_report.json"
    write_json(report_path, report)
    if not checks["ok"]:
        raise SystemExit(f"Kdenlive verification failed. See {report_path}")
    print(f"project={project}")
    print(f"bundle={out_dir}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
