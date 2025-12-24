---
id: audio
name: AI Audio Service (TTS & Voice)
type: block
version: 1.0.0
auth_group: []
description: "Een dedicated, zelfstandige service voor het genereren van hoge kwaliteit spraak (Text-to-Speech) en audio-effecten."
capabilities: ["audio"]
---

# Bouwblok: AI Audio Service (TTS & Voice)

## 🎯 Doelstelling
Een dedicated, zelfstandige service voor het genereren van hoge kwaliteit spraak (Text-to-Speech) en audio-effecten. Hoewel audio vaak onderdeel is van video, rechtvaardigt de complexiteit en herbruikbaarheid (bijv. voor podcasts, accessibility, chatbots) een eigen bouwblok.

## 🏗️ Architectuur

We draaien dit als een **Headless API Service** op Kubernetes, vergelijkbaar met de AI Video setup.

*   **API-First**: Input is tekst + stem-ID, output is `.wav`.
*   **Low-Latency**: Geoptimaliseerd voor snelle generatie (sneller dan realtime).
*   **Stateful**: Caching van gegenereerde stemmen in MinIO.

## ⚙️ Technologie Selectie: XTTSv2 / Parakeet

We standaardiseren op **Coqui XTTSv2** (via de `coqui-ai/TTS` library) vanwege:
1.  **Multilingual**: Uitstekende ondersteuning voor Nederlands.
2.  **Voice Cloning**: Kan met een 6-seconden sample een nieuwe stem klonen (ideaal voor consistente karakters).
3.  **Expressie**: Ondersteunt emoties (blij, boos, fluisterend).

Altenatief voor _ultra-realistisch_ Nederlands: **Parakeet** (Open Source model van NDI).

## 🛠️ Technische Implementatie (Cog Spec)

We gebruiken ook hier **Cog** voor de container definitie.

```yaml
build:
  gpu: true
  python_version: "3.10"
  python_packages:
    - "tts==0.22.0" # Coqui TTS
    - "fastapi"
    - "uvicorn"

predict: "predict.py:Predictor"
```

### API Interface
De service luistert naar POST requests:

```json
{
  "text": "Dit is een test voor de Druppie spraak service.",
  "language": "nl",
  "speaker_wav": "speakers/detective.wav" // Reference audio voor Voice Cloning
}
```

## ✅ Integratie
Dit bouwblok wordt gebruikt door:
1.  **AI Video Pipeline**: Voor de voice-overs.
2.  **Knowledge Bot**: Voor spraak-terugkoppeling in de chat.
3.  **Accessibility**: Voor het voorlezen van documentatie.
