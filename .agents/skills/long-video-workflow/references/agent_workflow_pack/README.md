# Agent Workflow Pack

This folder defines the reusable handoff contract for audio-to-image-prompt-to-video workflows.
Any AI Agent can follow this pack without knowing the internal Sticky-Man codebase.

## Core Rule

The Agent plans timing and prompts first. Another image tool may generate images later. Then the Agent imports ordered images and renders the final video or exports a Kdenlive project.

## Required Outputs

- `transcript_word_aligned.json`: standard word-level timestamp data used for prompt alignment.
- `image_prompts.json`: structured machine-readable prompt pack.
- `prompts.txt`: one prompt per line, formatted as `[time_start-time_end] prompt`.
- `image_tasks.json`: image order, output file name, and refs.
- `raw/0001.png`, `raw/0002.png`, ...: generated image files using 4-digit names.
- `images/0001.png`, `images/0002.png`, ...: postprocessed image files.
- `final_video.mp4`: rendered video.
- `kdenlive_project/`: optional Kdenlive bundle with `.kdenlive`, images, audio, and timeline plan.
- `kdenlive_conversion_report.json`: verification report created when converting JSON to Kdenlive.

## File Naming

All generated image files must use exactly four digits:

```text
0001.png
0002.png
0012.png
0120.png
```

Do not use `shot_0001.png` in this workflow pack.

## Quick Command

```bash
npm run sticky -- manifest \
  --storyboard output/vidtory_word30/storyboard_word_aligned.json \
  --out-dir output/my_agent_workflow \
  --limit 30 \
  --image-name-format digits4

npm run vidtory:rich -- \
  --tasks output/my_agent_workflow/image_tasks.json \
  --dry-run \
  --visual-recipe doodle-male \
  --prompt-lines-txt output/my_agent_workflow/prompts.txt \
  --prompt-pack-json output/my_agent_workflow/image_prompts.json \
  --prompt-pack-md output/my_agent_workflow/image_prompts.md \
  --prompt-debug-dir output/my_agent_workflow/prompts
```

Read the files in order:

1. `01_PROCESS.md`
2. `02_OUTPUT_SPEC.md`
3. `03_PROMPT_RULES.md`
4. `tools/json_to_kdenlive_project.py`
