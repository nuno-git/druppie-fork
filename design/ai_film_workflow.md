# Technisch Ontwerp: AI Film Productie Pipeline

## 🎯 Doelstelling
Het automatiseren van het filmproductieproces door middel van Generative AI. Dit ontwerp beschrijft hoe we van een **script** (tekst) naar een **volledige video** gaan, gebruikmakend van Pinokio voor de lokale, GPU-intensieve generatie en montage.

## 🏗️ Architectuur

De pipeline bestaat uit drie hoofdfasen die worden georkestreerd door de **Director Agent** (Orchestrator). De "Heavy Lifting" vindt plaats in tijdelijke Pinokio omgevingen.

### Componenten
1.  **Director Agent (LLM)**: Vertaalt het verhaal naar technische prompts (Storyboard).
2.  **Scene Generator (Pinokio + ComfyUI)**: Genereert losse clips op basis van prompts.
3.  **Editor (Pinokio + FFmpeg)**: Voegt clips, overgangen en audio samen.

---

## 🎬 De Workflow

### Stap 1: Script & Storyboard (Pre-productie)
De gebruiker levert een verhaal of thema aan. De **Director Agent** breekt dit op in scènes.
*   **Input**: "Een cyberpunk detective loopt door een regenachtige straat in Neo-Amsterdam, 2084."
*   **Output (JSON Spec)**:
    ```json
    {
      "title": "Neo-Amsterdam",
      "scenes": [
        { "id": 1, "duration": 4, "prompt": "Cyberpunk detective walking, rain, neon lights, canals of Amsterdam, futuristic architecture, 8k, unreal engine 5" },
        { "id": 2, "duration": 3, "prompt": "Close up of cybernetic eye looking at a holographic map" }
      ]
    }
    ```

### Stap 2: Generatie (Productie)
De Agent start een Pinokio sessie voor **ComfyUI** of **AnimateDiff**.
Voor elke scène in de JSON spec:
1.  **Injectie**: De prompt wordt in de Workflow API van de image generator geschoten.
2.  **Rendering**: Pinokio gebruikt de lokale GPU om een clip (bijv. `.mp4`) te genereren.
3.  **Consistentie**: Seed en Style Lora's worden hergebruikt om personages gelijk te houden.

### Stap 3: Montage (Post-productie)
Wanneer alle clips klaar zijn (`/output/scene_01.mp4`, `/output/scene_02.mp4`), start de Agent een "Editing" taak in Pinokio.
Dit script gebruikt **FFmpeg**:
1.  **Stitching**: Plakt de bestanden achter elkaar (`ffmpeg -f concat`).
2.  **Transitions**: Voegt eventueel cross-fades toe.
3.  **Audio**: Voegt een gegenereerde soundtrack toe.

### Stap 4: Levering & Cleanup
1.  De eindfilm (`final_movie.mp4`) wordt verplaatst naar de gebruikersmap.
2.  De Pinokio omgeving (inclusief gigabytes aan temp files) wordt verwijderd.

---

## 🛠️ Technische Specificatie (Pinokio Script)

Een voorbeeld van hoe de "Editor" taak eruit ziet in Pinokio JSON formaat:

```json
{
  "run": [
    {
      "method": "shell.run",
      "params": {
        "message": "Stitching Scenes...",
        "path": "output",
        "message": [
          "echo 'file scene_01.mp4' > list.txt",
          "echo 'file scene_02.mp4' >> list.txt",
          "ffmpeg -f concat -safe 0 -i list.txt -c copy final_movie.mp4"
        ]
      }
    }
  ]
}
```

## ✅ Voordelen
*   **Schaalbaar**: Je kunt 100 films genereren zonder handmatig werk.
*   **Reproduceerbaar**: Het script garandeert dat dezelfde input altijd leidt tot hetzelfde technische resultaat.
*   **Schoon**: Geen vervuiling van de ontwikkelmachine met video-tools; alles leeft in de Pinokio bubbel.
