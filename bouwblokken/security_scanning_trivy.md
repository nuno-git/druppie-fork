# Security & Compliance Scanning (Trivy)

## 🎯 Selectie: Trivy
Voor het scannen van onze containers, bestandssystemen en Infrastructuur-als-Code (IaC) kiezen we voor **Trivy** (van Aqua Security). Trivy is de meest veelzijdige, uitgebreide en gebruiksvriendelijke open-source security scanner.

### 💡 Onderbouwing van de Keuze
Waarom Trivy boven alternatieven (zoals Clair, SonarQube of Anchore)?

1.  **Alles-in-één Scanner**: Trivy scant niet alleen container images op CVE's (Common Vulnerabilities), maar scant ook:
    *   **Filesystem**: Source code dependencies (npm, pip, maven).
    *   **IaC**: Kubernetes manifests, Helm charts en Terraform bestanden op misconfiguraties (bijv. "Container draait als root").
    *   **SBOM**: Genereert automatisch een Software Bill of Materials (vereist voor Cyber Resilience Act / NIS2).
2.  **CI/CD Native**: Trivy is ontworpen als CLI tool die perfect past in een **Tekton** pipeline. Het geeft een harde Exit Code 1 als er een kritiek lek wordt gevonden, wat de build laat falen.
3.  **Stand-alone & Operator**: Kan als CLI draaien tijdens de build, maar ook als **Trivy Operator** in het cluster om draaiende workloads continu te scannen op nieuwe exploits (Day-2 Operations).
4.  **Database**: De vulnerability database is extreem up-to-date en wordt dagelijks ververst.

*(Noot: SonarQube is sterker in Code Quality/Bugs, maar voor Security & Compliance van de infrastructuurketen is Trivy de primaire tool.)*

---

## 🛠️ Installatie

We implementeren Trivy op twee plekken: in de **Build Plane** (Pipeline) en in de **Runtime** (Operator).

### 1. In de Pipeline (Tekton Task)
We voegen een herbruikbare Tekton Task toe die door de Builder Agent kan worden aangeroepen.

```yaml
apiVersion: tekton.dev/v1beta1
kind: Task
metadata:
  name: trivy-scan
spec:
  params:
    - name: IMAGE_URL
      description: The image to scan
  steps:
    - name: scan-image
      image: aquasec/trivy:latest
      command: ["trivy"]
      args:
        - "image"
        - "--exit-code"
        - "1"  # Fail pipeline on Critical
        - "--severity"
        - "CRITICAL,HIGH"
        - "--format"
        - "json"
        - "--output"
        - "scan_results.json"
        - "$(params.IMAGE_URL)"
```

### 2. In het Cluster (Trivy Operator)
Voor continue monitoring van productie.

```bash
helm repo add aqua https://aquasecurity.github.io/helm-charts/
helm upgrade --install trivy-operator aqua/trivy-operator \
  --namespace security-system --create-namespace \
  --set compliance.cron="0 */6 * * *" # Scan elke 6 uur
```

---

## 🚀 Gebruik: De "Secure Supply Chain"

### Scenario: Vulnerability Gevonden
1.  **Build Fase**: De Builder Agent commit nieuwe code. Tekton bouwt de container.
2.  **Scan**: De `trivy-scan` taak draait en vindt `CVE-2024-1234` (Critical) in de base image `python:3.9`.
3.  **Actie**: 
    *   De pipeline faalt ❌.
    *   De image wordt **niet** gepusht naar de registry.
    *   De Agent krijgt feedback: "Critical Vulnerability in base image. Update naar python:3.9-slim of patch de dependency."

### Scenario: SBOM Generatie (Compliance)
Voor elk release genereren we een SBOM (Software Bill of Materials).
```bash
trivy image --format cylonedx --output sbom.json my-app:v1
```
Dit bestand slaan we op in de **Traceability DB**. Als over 6 maanden blijkt dat "Log4j" lek is, kunnen we met één query zien: *"Welke applicaties gebruikten versie X?"*.

## 🔄 Integratie in Druppie
1.  **Kyverno**: Trivy scant, Kyverno handhaaft. De Trivy Operator schrijft rapporten (`VulnerabilityReport`) naar de Kubernetes API. Kyverno kan een policy hebben die zegt: "Als een pod een rapport heeft met >0 Criticals, kill de pod."
2.  **Visualisatie**: De resultaten van de Trivy Operator worden geëxporteerd naar **Grafana**. De CISO ziet een dashboard met "Security Posture: 98% Safe".
