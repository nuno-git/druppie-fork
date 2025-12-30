---
id: content-merge
name: "Content Merge"
description: "Merges multiple generated assets (audio/video/images) into a final video."
type: block
version: 1.0.0
---

## Description
This block takes the list of generated scenes (audio/video segments) and stitches them together into a single master video file.

## Parameters
- `av_script` (JSON): The full script context, which implicitly guides the order of merge.
- `output_format` (string, optional): Default "mp4".

## Behavior
- Scans `params` for generated video files (e.g., `video_scene_1.mp4`, `video_scene_2.mp4`).
- Uses ffmpeg (or equivalent) to concatenate them.
- Returns the path to the final video.
