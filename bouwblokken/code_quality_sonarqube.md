# Code Quality & Static Analysis (SonarQube)

## 🎯 Selectie: SonarQube
Voor het bewaken van de **technische kwaliteit**, **onderhoudbaarheid** en **code coverage** kiezen we voor **SonarQube**. Waar Trivy focust op beveiligingslekken in containers (CVE's), focust SonarQube op de broncode zelf (SAST - Static Application Security Testing).

### 💡 Onderbouwing van de Keuze
SonarQube is de logische aanvulling op Trivy in onze "Quality Gate".

1.  **Clean Code**: De **Builder Agent** genereert veel code. SonarQube fungeert als de automatische "Senior Developer" die de kwaliteit reviewt:
    *   *Complexiteit*: "Deze functie is te ingewikkeld (Deep nesting)."
    *   *Bugs*: "Mogelijke NullPointer Exception op regel 40."
    *   *Duplicatie*: "Stuk code is 3x gekopieerd."
2.  **Code Coverage**: Visualizeert welke regels code zijn geraakt door de Unit Tests (uitgevoerd door PyTest/Jest in Tekton). We eisen bijvoorbeeld minimaal 80% coverage.
3.  **Security Hotspots**: Vindt hardcoded secrets of zwakke encryptie in de code *voordat* het gecompileerd wordt.
4.  **Quality Gate**: Blokkeert de pipeline als de kwaliteit zakt (bijv. "Technical Debt ratio > 5%").

---

## 🛠️ Installatie

We draaien SonarQube als een stateful service in de **Build Plane**.

### Installatie via Helm
```bash
helm repo add sonarqube https://SonarSource.github.io/helm-chart-sonarqube
helm upgrade --install sonarqube sonarqube/sonarqube \
  --namespace build-system --create-namespace \
  --set edition=community \
  --set persistence.enabled=true
```

---

## 🚀 Gebruik: De "Quality Gate"

### 1. In de Pipeline (Tekton)
Na de unit-tests draait de scan.

```yaml
# Tekton Task Snippet
- name: sonar-scan
  image: sonarsource/sonar-scanner-cli
  command: ["sonar-scanner"]
  args:
    - "-Dsonar.projectKey=drone-service"
    - "-Dsonar.sources=."
    - "-Dsonar.host.url=http://sonarqube.build-system:9000"
    - "-Dsonar.qualitygate.wait=true" # Wacht op uitslag en faal indien nodig
```

### 2. Functional & Technical Testing
SonarQube zelf *voert* geen functionele testen uit (dat doen tools als PyTest, Jest, of Cypress), maar het **rapporteert** er wel over.

*   **Technisch Testen (Unit)**: De Builder Agent schrijft unit tests. Tekton voert ze uit. SonarQube toont: "95% Coverage".
*   **Functioneel Testen (E2E)**: Voor UI tests (bijv. met Playwright) kunnen de resultaten ook ingelezen worden als "Generic Test Data" om te zien welke features gedekt zijn.

### Scenario: "De Agent maakt rommelige code"
De Builder Agent is soms lui en kopieert code.
1.  **Commit**: Agent pusht code naar Gitea.
2.  **Scan**: SonarQube detecteert 15% Code Duplication.
3.  **Feedback**: De Quality Gate faalt ❌.
4.  **Loop**: De pipeline stuurt de error log terug naar de Agent. De Agent leest: *"Refactor required: Extract duplicate logic to helper function"*. De Agent past de code aan en pusht opnieuw.

## 🔄 Integratie in Druppie
*   **Trivy vs SonarQube**:
    *   *Trivy*: Kijkt naar de **Container** en **Dependencies** (Is `log4j` lek?). -> Security.
    *   *SonarQube*: Kijkt naar de **Eigen Code** (Heb ik een wachtwoord hardcoded?). -> Kwaliteit.
*   **Samen**: Ze vormen samen de verdedigingslinie in de **Build Plane**.
