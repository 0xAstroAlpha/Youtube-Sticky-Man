# Output Spec

## `prompts.txt`

Required format:

```text
[0-1.74] prompt text on one line
[1.74-4.16] prompt text on one line
```

Rules:

- One line equals one image.
- No newline inside any prompt.
- Start/end are seconds.
- Start/end must match JSON timing.
- Prompt text must not contain Markdown fences.

## `image_prompts.json`

Required top-level shape:

```json
{
  "schema": "sticky-man.prompt-pack.v1",
  "shot_count": 30,
  "total_duration": 113.323,
  "instructions": {
    "order": "Create images in ascending order.",
    "output": "Return files using each item.output.path or file.",
    "refs": "Use refs[] when the image tool supports reference images."
  },
  "prompts": []
}
```

Each prompt item:

```json
{
  "order": 1,
  "shot_id": 1,
  "visual_kind": "illustration",
  "generation_mode": "create",
  "visual_recipe": "doodle-male",
  "timing": {
    "start": 0,
    "end": 1.74,
    "duration": 1.74
  },
  "output": {
    "file": "0001.png",
    "format": "png"
  },
  "refs": [],
  "prompt": "Single-line prompt only."
}
```

## `image_tasks.json`

This file answers two required questions:

1. Image order: `tasks[].order`
2. Image refs: `tasks[].refs`

Each task must include:

```json
{
  "order": 12,
  "output": {
    "file": "0012.png",
    "path": "/absolute/path/to/raw/0012.png"
  },
  "refs": [
    {
      "type": "scene_previous",
      "source_order": 11,
      "path": "/absolute/path/to/raw/0011.png",
      "required": true
    }
  ],
  "timing": {
    "start": 30.161,
    "end": 42.801,
    "duration": 12.64
  },
  "prompt": "Single-line prompt only."
}
```

## Image File Names

Required:

```text
0001.png
0002.png
0012.png
0030.png
```

Forbidden in this workflow:

```text
shot_0001.png
image1.png
frame-1.png
1.png
```

## Kdenlive Project

Kdenlive project export must include:

- `.kdenlive` file with relative media paths.
- `assets/images/0001.png`, `assets/images/0002.png`, ...
- `assets/audio/<audio_file>`.
- `kdenlive_timeline_plan.json`.

The `.kdenlive` file should use the same shot timing as `image_prompts.json`.

## Kdenlive Conversion Report

`kdenlive_conversion_report.json` must include:

```json
{
  "schema": "agent-workflow.kdenlive-conversion-report.v1",
  "source_json": "/abs/path/image_prompts.json",
  "project": "/abs/path/kdenlive_project/ProjectName.kdenlive",
  "bundle": "/abs/path/kdenlive_project",
  "checks": {
    "ok": true,
    "xml_parsed": true,
    "root_version": "7.39.0",
    "root_producer": "main_bin",
    "root_path": ".",
    "doc_version": "1.1",
    "xml_retain": "1",
    "has_active_sequence": true,
    "unique_ids": true,
    "contains_absolute_user_path": false,
    "bad_semicolon_durations": [],
    "media_paths_relative": true
  }
}
```

## `transcript_word_aligned.json`

Required when converting external TTS (like ElevenLabs) into word-level timestamps. This defines the standard format the animation timeline uses to snap frames to spoken words.

```json
{
  "schema": "sticky-man.transcript.v1",
  "text": "Hello there, this is a test.",
  "words": [
    {
      "word": "Hello",
      "start": 0.0,
      "end": 0.174
    },
    {
      "word": "there,",
      "start": 0.232,
      "end": 0.522
    }
  ]
}
```

Rules:

- Timing is expressed in seconds as floating-point numbers.
- `words[]` must correspond sequentially to the spoken audio.
- The `start` and `end` values must be mapped from the TTS provider (e.g. parsed from ElevenLabs `with-timestamps`).
