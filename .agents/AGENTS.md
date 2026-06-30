# Workspace Rules

When working on long-form video projects or scripts over 5000 characters, you MUST trigger the `long-video-workflow` skill. 
Do not attempt to process massive scripts in a single pass. Always rely on the chunking methodology outlined in the skill to prevent audio cutoff and LLM output token limits.
CRITICAL RULE: Never use mechanical duration-based loops to slice video shots. Always use Agent Semantic Intelligence to map visual scenes to exact trigger words in the transcript, ensuring visual impacts hit precisely on the emphasized word.
