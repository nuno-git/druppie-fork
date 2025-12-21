# Technisch Ontwerp: AI Film Productie Pipeline

## 🎯 Doelstelling
Het automatiseren van het filmproductieproces door middel van Generative AI. Dit ontwerp beschrijft hoe we van een **script** (tekst) naar een **volledige video** gaan, gebruikmakend van **Headless ComfyUI** op Kubernetes voor schaalbare, GPU-intensieve generatie.

## 🏗️ Architectuur

De pipeline bestaat uit drie hoofdfasen die worden georkestreerd door de **Director Agent** (Orchestrator). De "Heavy Lifting" vindt plaats in de **K8s Render Farm**.

### Componenten
1.  **Director Agent (LLM)**: Vertaalt het verhaal naar technische prompts (Storyboard).
2.  **Scene Generator (ComfyUI API)**: Genereert losse clips op basis van prompts (HunyuanVideo).
3.  **Editor (FFmpeg Worker)**: Voegt clips, overgangen en audio samen.

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
De Agent stuurt API calls naar de **Headless ComfyUI** service in het cluster.
Voor elke scène in de JSON spec:
1.  **Injectie**: De prompt wordt in de JSON workflow template (Node Graph) geschoten.
2.  **Rendering**: Een Kubernetes Pod (met GPU) pikt de taak op en genereert de clip (bijv. `.mp4`).
3.  **Hunyuan**: We gebruiken het HunyuanVideo model voor hoge kwaliteit en consistentie.

### Stap 3: Montage (Post-productie)
Wanneer alle clips klaar zijn (beschikbaar in MinIO/S3), start de Agent een "Editing" Job in Kubernetes.
Deze container gebruikt **FFmpeg**:
1.  **Stitching**: Plakt de bestanden achter elkaar en voegt een gegenereerde soundtrack toe.
2.  **Output**: De eindfilm wordt geüpload naar de gedeelde storage.

### Stap 4: Levering
1.  De eindfilm (`final_movie.mp4`) wordt beschikbaar gemaakt in de UI.
2.  De tijdelijke render-pods schalen automatisch af (Scale-to-Zero).

---

## 🛠️ Technische Specificatie (ComfyUI API Payload)

Een voorbeeld van hoe de Agent de API aanroept:

```json
{
  "client_id": "director_agent_007",
  "prompt": {
    "3": {
      "class_type": "KSampler",
      "inputs": {
        "seed": 849302,
        "steps": 30,
        "cfg": 7.0,
        "model": ["4", 0],
        "positive": ["6", 0], // Link to Prompt Node
        "image": ["10", 0]
      }
    },
    "6": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "Cyberpunk detective walking, rain, neon lights...",
        "clip": ["4", 1]
      }
    }
  }
}
```

## ✅ Voordelen
*   **Schaalbaar**: Het cluster verdeelt de scènes over alle beschikbare GPU's (Parallel Rendering).
*   **Automatisering**: Geen menselijke interactie nodig; van tekst tot video in één pijplijn.
*   **Gestandaardiseerd**: Door Docker containers is de output, in tegenstelling tot lokale machines, altijd identiek.
