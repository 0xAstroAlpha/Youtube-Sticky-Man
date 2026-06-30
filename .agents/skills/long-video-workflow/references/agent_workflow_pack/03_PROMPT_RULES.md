# Prompt Rules

## One-Line Rule

Every prompt must be one physical line.

Allowed:

```text
[0-1.74] Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, a male stick figure...
```

Forbidden:

```text
[0-1.74] Hand-drawn 2D doodle cartoon animation,
flat colors,
bold black outlines...
```

## Dynamic Pacing Rule

Choose visuals that map tightly to specific words or phrases (1-4 seconds per shot). Avoid long, static shots for entire sentences.

Bad: One image holds for a full 10-second sentence.

Good: The scene cuts 3 times across a 10-second sentence, visually emphasizing key phrases (e.g., crossing out a supermarket aisle, zooming in on freezing veins).

## Prehistoric Doodle Recipe

Base formula:

```text
Hand-drawn 2D doodle cartoon animation, flat colors, bold black outlines, slightly imperfect sketchy marker lines, [SPECIFIC VISUALS], stark white background, no gradients, no shadows, no textures, no photorealism, no 3D, 16:9 aspect ratio, educational YouTube explainer doodle style.
```

Character lock:

```text
the recurring character is a primitive prehistoric male stick figure wearing animal skins, same face and body proportions across shots
```

## Continuity Rule

When the next shot belongs to the same scene, use the previous image as ref.

The next prompt must say:

```text
Continuity instruction: use the scene_previous reference as the prior animation beat. Preserve character identity, camera distance, visual scale, white background, and line weight.
```

## Red X Rule

Use a giant bold red X only for:

- rejected choices
- forbidden objects
- negated concepts
- wrong habits

Do not use red X as generic decoration.

## Hero Title Rule

Do not overlay title text during video rendering.

For hero title shots, the image prompt must request the image model to render the exact title inside the image.
