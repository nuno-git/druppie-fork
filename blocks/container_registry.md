---
id: container-registry
name: "Container Registry (Harbor)"
type: block
version: 1.0.0
auth_group: []
description: "Container Registry (Harbor)"
capabilities: []
---

# Container Registry (Harbor)

## 📄 Samenvatting
Dit bouwblok beschrijft de implementatie van een centrale opslagplaats voor Docker images (Container Registry). Voor een Kubernetes-platform is een betrouwbare, snelle en veilige registry essentieel. Wij kiezen voor **Harbor** vanwege de cloud-native focus, ingebouwde security scanning en role-based access control.

## 🎯 Doelstelling
Het bieden van een veilige haven ('Harbor') waar alle gebouwde applicatie-images worden opgeslagen voordat ze worden uitgerold naar de clusters. Dit zorgt voor:
*   **Versiebeheer**: Elke build heeft een unieke, onwijzigbare tag (immutable).
*   **Security**: Images worden automatisch gescand op kwetsbaarheden (CVE's) voordat ze "live" mogen.
*   **Performance**: Lokale caching van images dichtbij de clusters.

## ⚙️ Technologie Selectie
Wij standaardiseren op **Harbor**.

*   **Waarom Harbor?**
    *   **Open Source & CNCF Graduated**: De industriestandaard voor self-hosted registries.
    *   **Ingebouwde Scanning**: Naadloze integratie met Trivy om images te scannen bij push.
    *   **RBAC & OIDC**: Koppelt direct met Keycloak voor gebruikersbeheer (wie mag pushen/pullen).
    *   **Replication**: Kan images synchroniseren tussen verschillende Harbor instanties (bijv. DMZ vs Intern).
    *   **Signing**: Ondersteunt Cosign/Notary voor het digitaal ondertekenen van images (supply chain security).

## 🔨 Implementatie Specificaties

### 1. Deployment Model
Harbor wordt uitgerold binnen het `tooling` cluster via Helm.

*   **Namespace**: `harbor`
*   **Storage**: Gebruikt MinIO (S3) of een PVC voor de opslag van de lagen (layers).
*   **Ingress**: Bereikbaar via `registry.druppie.local` (of publieke URL).

### 2. Integratie met Core
De **Druppie Core** (Build Plane) interacteert met Harbor:
1.  **Push**: De CI/CD pipeline (Tekton) bouwt een image en pusht deze naar Harbor.
2.  **Scan**: Harbor triggert een Trivy scan.
3.  **Webhook**: Harbor stuurt een event naar de Core: `SCAN_COMPLETED` met status `PASS` of `FAIL`.
4.  **Pull**: De Kubernetes clusters authenticeren met een `ImagePullSecret` om de images binnen te halen.

### 3. Configuratie (Helm Values voorbeelden)
```yaml
expose:
  type: ingress
  tls:
    enabled: true
    secretName: "harbor-tls"
  ingress:
    hosts:
      core: "registry.druppie.local"

externalURL: "https://registry.druppie.local"

persistence:
  imageChartStorage:
    type: s3
    s3:
      region: "us-east-1"
      bucket: "harbor-images"
      accesskey: "minio-admin"
      secretkey: "minio-secret"
      regionendpoint: "http://minio.minio.svc:9000"

trivy:
  enabled: true
```

## 🛡️ Security & Compliance
*   **Image Signing**: Alle productie-images MOETEN ondertekend zijn.
*   **Vulnerability Policy**: Images met 'Critical' CVE's worden geblokkeerd en kunnen niet gepulled worden (Deployment Preventie).
*   **Retention Policy**: Oude 'nightly' builds worden na 14 dagen automatisch verwijderd om opslag te besparen.

## Noodzakelijke Skills
*   Docker & OCI standaarden.
*   Kubernetes (voor Helm deployment).
*   Linux systeembeheer (voor storage management).
