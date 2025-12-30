---
id: ai-image-sdxl
name: AI Image Service (SDXL)
type: service
version: 1.0.0
auth_group: []
description: "High-performance image generation service using Stable Diffusion XL (SDXL) with Cog and Kubernetes."
capabilities: ["ai_image"]
---

# Bouwblok: AI Image Service (SDXL)

## 🎯 Doelstelling
Het leveren van een schaalbare API voor het genereren van afbeeldingen van hoge kwaliteit op basis van tekstprompts, geschikt voor storyboarding, UI design en marketing content.

## 🏗️ Architectuur
De service draait als een Cog-container op Kubernetes met GPU ondersteuning.

*   **Model**: Stable Diffusion XL (SDXL) 1.0.
*   **Infrastructure**: Kubernetes met NVIDIA GPU-scheduling.
*   **API**: REST API voor single en batch generatie.

## 🛠️ Technische Details
- **Backend**: Python/FastAPI.
- **Image Serving**: MinIO voor opslag van resultaten.
- **Input**: Prompt, Negative Prompt, Aspect Ratio, Seed.
