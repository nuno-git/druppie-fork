---
id: content-review
name: "Content Review"
description: "Present generated content (e.g. scripts, plans) to the user for approval or feedback."
type: skill
version: 1.0.0
---

## Description
This skill acts as a Quality Gate. It displays structured content to the user and waits for explicit confirmation before proceeding.

## Parameters
- `av_script` (JSON): The Audio-Visual script to review. MUST follow the **AV Script Blueprint** structure:
  ```json
  [
    {
      "scene_id": 1,
      "audio_text": "Spoken text here...",
      "visual_prompt": "Visual description in English...",
      "voice_profile": "Description of voice...",
      "duration": "Estimated duration (e.g. 5s)"
    }
  ]
  ```

## Behavior
- The system renders the content in a user-friendly format (e.g. Markdown, Tables).
- The user can "Accept" (proceed) or "Reject" (stop/loop back).
- Feedback provided by the user is returned to the agent for refinement.
