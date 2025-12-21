# AI Anonymizer (YOLOv8)

## 🎯 Selectie: YOLOv8
Voor het automatisch detecteren en anonimiseren van privacy-gevoelige objecten (gezichten, personen, kentekenplaten) in beeldmateriaal kiezen we voor **YOLOv8** (You Only Look Once, versie 8) van Ultralytics.

### 💡 Onderbouwing van de Keuze
Waarom een generiek AI-model en geen specifieke "Blur Tool"?

1.  **SOTA (State of the Art)**: YOLOv8 is momenteel de industriestandaard voor real-time objectdetectie. Het is extreem snel en nauwkeurig.
2.  **Trainbaar**: Standaard tools (zoals FaceDetect) werken vaak niet goed op drone-beelden (bovenaanzicht, kleine pixels). YOLOv8 kunnen we specifiek **hertrainen** (Fine-Tuning) op onze eigen "Drone Dataset" met behulp van gelabelde data uit DVC.
3.  **Flexibiliteit**:
    *   Vandaag: Gezichten en Kentekens anonimiseren.
    *   Morgen: Muskusratten of Kadebreuken detecteren. De infrastructuur blijft hetzelfde, alleen het modelbestand (`.pt`) verandert.
4.  **Performance**: Geoptimaliseerd voor GPU. Dit is essentieel als we TB's aan data moeten verwerken in onze pipeline.

---

## 🛠️ Installatie

We verpakken YOLOv8 in een container die fungeert als een "Filter Service".

### Docker Image
We gebruiken de officiële base image en voegen een klein Python script toe dat de blurring doet.

```dockerfile
FROM ultralytics/ultralytics:latest-cpu
# (Of 'latest-gpu' voor de nodes met NVIDIA kaarten)

RUN pip install opencv-python-headless

COPY anonymize.py /app/
ENTRYPOINT ["python", "/app/anonymize.py"]
```

### Het Script (`anonymize.py`)
In pseudocode:
1.  Laad Model: `model = YOLO('yolov8n-face.pt')`
2.  Open Info: `img = cv2.imread(input_path)`
3.  Detecteer: `results = model(img)`
4.  Voor elke detectie (Box):
    *   Pas een **Gaussian Blur** toe op de regio binnen de box.
    *   (Tip: Gebruik geen zwart vlak, dat verstoort de fotogrammetrie/stitching in WebODM. Blurring behoudt de kleur-structuur).
5.  Sla op: `cv2.imwrite(output_path, img)`

---

## 🚀 Gebruik: De "Scrubbing Pipeline"

Dit bouwblok wordt aangeroepen door **Tekton** in de Data Lifecycle.

### Configuratie (ConfigMap)
We kunnen de agressiviteit van het model instellen:

```yaml
confidence_threshold: 0.25 # Bij twijfel: blurren (Better safe than sorry)
classes_to_blur:
  - 0 # Person
  - 1 # Bicycle (Optioneel)
  - 2 # Car (Kentekens)
```

### Validatie (Human-in-the-Loop)
Hoewel YOLOv8 >99% kan scoren, is bij High Risk data (dichtbij bebouwing) een menselijke check nodig.
*   De pipeline kan een "Heatmap" genereren van geblurde locaties.
*   De operator ziet in één oogopslag waar anonimisering heeft plaatsgevonden en kan steekproeven doen.

## 🔄 Integratie in Druppie
1.  **DVC**: Het getrainde model zelf (`drone-face-v1.pt`) wordt beheerd in DVC net als de data.
2.  **WebODM**: De output van deze anonimizer is de input voor WebODM. Doordat we "zacht" blurren, kan WebODM de foto's nog steeds aan elkaar stitchen op basis van de omgeving (gras, bomen), terwijl de personen onherkenbaar zijn.
3.  **Governance**: In de metadata van de foto (EXIF) schrijven we: `Processed-By: Druppie-Anonymizer-V1`.
