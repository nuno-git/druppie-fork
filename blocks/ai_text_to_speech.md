---
id: ai-text-to-speech
name: AI Text-to-Speech Service (TTS)
type: service
version: 1.0.0
auth_group: []
description: "Advanced multilingual Text-to-Speech service using Coqui XTTSv2 for realistic voice cloning and high-quality narration."
capabilities: ["audio", "tts"]
---

# Bouwblok: AI Text-to-Speech Service (TTS)

## 🎯 Doelstelling
Het omzetten van tekst naar natuurlijke spraak voor video voice-overs, accessibility en interactieve applicaties.

## 🏗️ Architectuur
- **Engine**: Coqui XTTSv2.
- **Features**: 
    - **Voice Cloning**: Kloon een stem op basis van een sample van 6 seconden.
    - **Multilingual**: Ondersteuning voor 16+ talen, waaronder vloeiend Nederlands.
    - **Emotion Control**: Instelbare toon (blij, serieus, etc.).
- **Deployment**: Kubernetes Pod met NVIDIA GPU (voor realtime generatie).

## 🛠️ Integratie
- Wordt aangeroepen door de **Content Creator** voor het genereren van vlag-audio.
- Resultaten (.wav/.mp3) worden opgeslagen in **MinIO**.
