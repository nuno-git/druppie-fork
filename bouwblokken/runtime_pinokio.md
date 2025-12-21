# Bouwblok: Pinokio (AI Runtime Automation)

## 🎯 Selectie: Pinokio
Voor het lokaal uitvoeren, delen en eenvoudig installeren van complexe AI-applicaties (zoals Stable Diffusion, LLM's of Audio tools) introduceren we **Pinokio**. Dit fungeert als een "AI Browser" die JSON-gebaseerde installatie-scripts uitvoert om volledig geïsoleerde en reproduceerbare omgevingen op te zetten.

### 💡 Het Probleem: "Dependency Hell"
Normaal gesproken moet een ontwikkelaar of eindgebruiker handmatig een enorme stack installeren om een AI applicatie te draaien:
*   Specifieke Python versie (3.10 vs 3.11).
*   Virtuele omgevingen (Venv/Conda) beheren.
*   Complex C++ compilers of CUDA drivers configureren.
*   Systeemvariabelen (PATH) aanpassen.

Dit is foutgevoelig en zorgt ervoor dat software vaak niet werkt bij collega's ("It works on my machine").

### 🚀 De Oplossing: Script-Driven Provisioning
Pinokio lost dit op door de **installatie te automatiseren** via een `pinokio.json` script. Dit past naadloos in de **Spec-Driven** filosofie van Druppie.

**Hoe het werkt:**
1.  **Geïsoleerde Runtimes**: Pinokio installeert *lokaal* in een eigen map verse versies van Python, Node.js, Git en FFmpeg. Het raakt de systeem-installatie van de host **niet** aan.
2.  **JSON Specificatie**: De ontwikkelaar (of AI Agent) schrijft geen ingewikkelde README, maar een JSON bestand met de stappen (git clone, pip install, run).
3.  **One-Click Install**: De gebruiker laadt het script en klikt op "Install". Pinokio voert alles uit.

### ⚙️ Implementatie in Druppie
Binnen de architectuur vervult Pinokio de rol van **Local/Edge Runtime**:

*   **Builder Agent Output**: Wanneer de Builder Agent een nieuwe AI-tool genereert (bijv. de "Vergunning Vinder"), genereert hij ook een `pinokio.json`.
*   **Team Collaboratie**: Een teamlid kan dit script inladen en heeft gegarandeerd exact dezelfde omgeving, zonder Docker kennis nodig te hebben.
*   **Lokale Inferentie**: Voor zware workloads die GPU toegang nodig hebben op een laptop, is Pinokio vaak lichter en makkelijker te configureren dan Docker Desktop met GPU-passthrough.

### 🎬 Use Case: Ephemeral Video Studio
Een specifiek doel binnen Druppie is het inzetten van Pinokio voor **Generative Video & Film** producties.
AI-video tools (zoals ComfyUI, AnimateDiff, Stable Video Diffusion) vereisen vaak enorme hoeveelheden schijfruimte, specifieke FFmpeg versies en complexe dependencies.

**De Workflow:**
1.  **Spin-up**: De Agent start een Pinokio script dat een tijdelijke "Video Studio" omgeving opzet.
2.  **Productie**: De video wordt gegenereerd/gerenderd met maximale GPU prestaties.
3.  **Cleanup**: Na afloop van het project kan de gehele omgeving met één klik verwijderd worden.

Hierdoor blijft het basissysteem schoon en wordt er geen opslag verspild aan "oude" project-dependencies. Dit maakt het ideaal voor eenmalige producties of experimenten.

### 🛠️ Voorbeeld Script
Een voorbeeld van hoe zo'n specificatie eruit ziet:

```json
{
  "version": "2.0",
  "run": [
    {
      "method": "shell.run",
      "params": {
        "message": "Install dependencies",
        "venv": "env",                // Maak automatisch een virtual env
        "path": "app",
        "message": [
          "pip install -r requirements.txt",
          "npm install"
        ]
      }
    },
    {
      "method": "shell.run",
      "params": {
        "message": "Start Application",
        "venv": "env",
        "path": "app",
        "script": "python main.py"
      }
    }
  ]
}
```

### 📹 Example: Tencent HunyuanVideo
Hieronder een specifiek voorbeeld voor het draaien van **[HunyuanVideo](https://github.com/Tencent-Hunyuan/HunyuanVideo)**, een state-of-the-art open source video model.

Dit script automatiseert de complexe setup (Git LFS, PyTorch, Model Download) volledig.

```json
{
  "version": "2.0",
  "run": [
    {
      "method": "shell.run",
      "params": {
        "message": "Install System Dependencies",
        "message": [
          "git lfs install"
        ]
      }
    },
    {
      "method": "shell.run",
      "params": {
        "message": "Clone Repository",
        "path": "app",
        "message": "git clone https://github.com/Tencent-Hunyuan/HunyuanVideo.git ."
      }
    },
    {
      "method": "shell.run",
      "params": {
        "message": "Setup Python Environment",
        "venv": "env",
        "path": "app",
        "message": [
          "pip install -r requirements.txt",
          "pip install ninja", 
          "pip install git+https://github.com/Dao-AILab/flash-attention.git@v2.6.3"
        ]
      }
    },
    {
      "method": "shell.run",
      "params": {
        "message": "Download Weights (HuggingFace)",
        "path": "app/ckpts",
        "message": [
          "huggingface-cli download Tencent-Hunyuan/HunyuanVideo --local-dir ."
        ]
      }
    },
    {
      "method": "shell.run",
      "params": {
        "message": "Start Inference Server (Gradio)",
        "venv": "env",
        "path": "app",
        "script": "python app.py --host 0.0.0.0 --port 7860"
      }
    }
  ]
}
```

### ✅ Samenvatting
Pinokio biedt voor AI-applicaties wat Docker biedt voor webservers: **reproduceerbaarheid**. Maar dan zonder de overhead van containers en met een focus op lokale, GPU-versnelde uitvoering.
