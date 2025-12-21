# Bouwblok: Headless ComfyUI (High-Performance Rendering)

## 🎯 Alternatief voor Pinokio
Waar Pinokio een gebruiksvriendelijke "Desktop Wrapper" is, is **Headless ComfyUI** de industriestandaard voor schaalbare, geautomatiseerde AI-productie zonder overhead.

### 💡 Het Concept
Pinokio draait een volledige browser + filesysteem management layer. Dit kost CPU/RAM en is moeilijk te schalen in een cluster.
Door **ComfyUI** direct in **API-Only Mode** te draaien binnen een geoptimaliseerde Docker container, strippen we alle overhead weg.

*   **Geen GUI**: De server luistert alleen naar API verzoeken via WebSocket/HTTP.
*   **Geen "Install Scripts"**: De environment zit 'fixed' gebakken in een Docker image (Immutable Infrastructure).

### 🚀 Architectuur: The Rendering Farm

In deze opzet fungeert het Kubernetes cluster als een "Rendering Farm".

1.  **Designer (Lokaal)**:
    *   De creatief ontwikkelaar gebruikt lokaal ComfyUI (met GUI) om de workflow te bouwen.
    *   Hij slaat dit op als **API Format** (`workflow.json`).
2.  **Manager (Druppie Core)**:
    *   De Agent pakt de JSON en injecteert variabelen (bijv. `"text": "A cyberpunk city"`).
    *   Hij stuurt de payload naar het cluster.
3.  **Worker (K8s Pod)**:
    *   Een ComfyUI pod (met GPU) pikt de taak op.
    *   Rendert de video.
    *   Uploadt het resultaat naar MinIO.

### ⚙️ Spec-Driven Containers: Cog
Binnen Druppie kiezen we voor **Cog** (van Replicate) als de standaard voor het bouwen van AI containers.

**Waarom Cog?**
Standaard Dockerfiles zijn krachtig maar imperatief ("doe dit, doe dat"). Voor AI workloads leidt dit vaak tot "CUDA Hell": het oneindig pielen met nvidia-drivers, python versies en torch builds die niet matchen.

**Cog is Declaratief (Spec-Driven):**
Je definieert *wat* je nodig hebt in `cog.yaml`, en Cog genereert de perfecte Docker image voor je.
*   **Automatic CUDA**: Cog kiest automatisch de juiste base-images voor jouw GPU hardware.
*   **Immutable**: De output is een production-ready container die overal werkt.
*   **API-First**: Cog genereert automatisch een HTTP server rondom je model.

**De Spec (`cog.yaml`):**
```yaml
build:
  # De "Spec" van de runtime
  gpu: true
  python_version: "3.10"
  system_packages:
    - "ffmpeg"
    - "libgl1-mesa-glx"
  python_packages:
    - "torch==2.1.2" # Specifieke versies!
    - "comfy-cli==1.0.0"

# De "Interface" naar de buitenwereld
predict: "predict.py:Predictor"
```

In onze CI/CD pipeline (Tekton) draait simpelweg `cog build` om van deze spec een container te maken.

### 🛠️ Technische Implementatie (K8s Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: comfyui-worker
spec:
  replicas: 1 # Schaalbaar via KEDA
  template:
    spec:
      containers:
      - name: comfyui
        image: ghcr.io/my-org/comfyui-hunyuan:sha-123456 # Built by Cog
        ports:
        - containerPort: 5000 # Standaard Cog poort
        resources:
          limits:
            nvidia.com/gpu: 1
```

### 📼 Implementatie: HunyuanVideo in Headless ComfyUI

Om het **HunyuanVideo** model (state-of-the-art open source video) te draaien in deze headless setup, moeten we de Docker image "pre-baken" met de juiste modellen en custom nodes.

#### 1. Directory Structuur (in de Container)
De Dockerfile moet de volgende bestanden op de juiste plek zetten:

*   **Custom Nodes**:
    *   `custom_nodes/ComfyUI-HunyuanVideoWrapper`: Clone van Kijai's wrapper.
*   **Modellen**:
    *   `/models/diffusion_models/`: `hunyuan_video_t2v_720p_bf16.safetensors`
    *   `/models/vae/`: `hunyuan_video_vae_bf16.safetensors`
    *   `/models/text_encoders/`: `clip_l.safetensors`, `llava_llama3_fp8_scaled.safetensors`

#### 2. Dockerfile Specificatie (Cog)

```yaml
build:
  gpu: true
  python_version: "3.10"
  system_packages:
    - "git"
    - "wget"
  python_packages:
    - "torch==2.1.0"
  run:
    # 1. Install Custom Nodes
    - "git clone https://github.com/kijai/ComfyUI-HunyuanVideoWrapper custom_nodes/ComfyUI-HunyuanVideoWrapper"
    - "pip install -r custom_nodes/ComfyUI-HunyuanVideoWrapper/requirements.txt"
    
    # 2. Download Weights (Coded in Image for Speed)
    # Let op: In productie mounten we dit vaak via een Volume (PVC) om image size clean te houden.
    - "wget -O models/diffusion_models/hunyuan_video_720p.safetensors https://huggingface.co/Tencent-Hunyuan/HunyuanVideo/resolve/main/hunyuan_video_t2v_720p_bf16.safetensors"
```

### ✅ Vergelijking

| Feature | Pinokio | Headless ComfyUI |
| :--- | :--- | :--- |
| **Gebruiksgemak** | Hoog (One-click) | Gemiddeld (API knowledge) |
| **Overhead** | Hoog (GUI, Node.js wrapper) | Minimaal (Pure Python) |
| **Schaalbaarheid** | Laag (1 instantie) | Hoog (Kubernetes HPA) |
| **Startup Tijd** | Traag (Install at runtime) | Instant (Pre-baked image) |
| **Doelgroep** | Hobbyist / Single User | Enterprise / Automatisering |
