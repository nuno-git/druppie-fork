---
id: audio-review
name: "Audio Review"
description: "Review generated audio file and its metadata."
type: skill
version: 1.0.0
---

## Description
Presents a single generated audio file to the user for quality control.

## Parameters
- `audio_file` (string): The filename/path of the generated audio (e.g., "audio_scene_1.mp3").
- `duration` (string): The duration of the clip.

## Behavior
- Displays a playback control for the user.
- User approves or rejects the quality/intonation.
