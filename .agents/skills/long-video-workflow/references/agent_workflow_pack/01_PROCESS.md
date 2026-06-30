# Process

## Step 1: Input & Prompt Generation (Agent)

When receiving input audio or transcript (with word-level timing), the Agent analyzes the content and writes the prompt set. Each prompt matches an image to be created, includes clear sequence numbering, and is mapped at the word-level.

- **Dynamic Word-Level Pacing**: Do not plan shots by full sentences. Break the scene down into rapid-fire word/phrase clusters averaging 1-4 seconds per shot for maximum engagement.
- Use word-level timing to snap image boundaries to real spoken words.
- Export both JSON and TXT formats for the prompts.
- Prompts must be a single line. Example:
  `[0-1.74] Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, a primitive prehistoric male stick figure...`

## Step 2: Image Generation (User)

The User takes the exported prompts to generate images using an external tool. 
Once finished, the User returns the generated images with standardized sequential naming:

```text
0001.png
0002.png
0003.png
```

## Step 3: Video Assembly & Rendering (Agent)

The Agent takes the sequentially numbered images provided by the User and stitches them together according to the timestamps analyzed in Step 1.
The Agent then renders and returns the final finished video.

## Step 4: Kdenlive Project Export (Optional - Agent)

Only if the User explicitly requests the creation of a Kdenlive project, the Agent will build a self-contained Kdenlive project bundle.

The bundle structure:

```text
kdenlive_project/
  ProjectName.kdenlive
  assets/
    audio/audio.mp3
    images/0001.png
    images/0002.png
  kdenlive_timeline_plan.json
```

Use relative paths inside `.kdenlive`. Convert workflow JSON to Kdenlive using `agent_workflow_pack/tools/json_to_kdenlive_project.py`.
