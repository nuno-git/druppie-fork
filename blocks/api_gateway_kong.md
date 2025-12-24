---
id: api-gateway-kong
name: API Gateway (Kong)
type: block
description: "Centrale API Gateway voor het beheren, beveiligen en monitoren van API-verkeer across services."
capabilities: ["api-management", "rate-limiting", "auth-proxy"]
version: 1.0.0
auth_group: ["developers"]
---
# API Gateway (Kong)

## 🎯 Selectie: Kong Gateway
Voor het geavanceerd beheren, beveiligen en monitoren van API-verkeer kiezen we voor **Kong Gateway** (DB-less mode). Kong fungeert als de voordeur voor alle microservices en AI-agenten.

### 💡 Onderbouwing van de Keuze
Hoewel we al een Ingress Controller (NGINX) hebben voor basis routing, voegt een API Gateway een abstractielaag toe die essentieel is voor een volwassen platform:

1.  **Decoupling**: De afnemer van de data praat met `api.druppie.nl/v1/drone-data`, terwijl de backend misschien `drone-service-v3.internal:8080/export` heet. De Gateway vertaalt dit.
2.  **Policy Enforcement (CRD)**: Met Kong beheren we "Traffic Policies" als Kubernetes objecten (`KongPlugin`). De **Policy Engine** (zie Architecture) kan zo afdwingen dat *elke* externe API een Rate Limit heeft, zonder de applicatiecode aan te passen.
3.  **Centrale Authenticatie**: Kong valideert API Keys of JWT tokens (van Keycloak) *voordat* het verzoek de service bereikt. Dit ontlast de ontwikkelaars.
4.  **Transformation**: Kong kan on-the-fly requests aanpassen (bijv. een oude XML response omzetten naar JSON) om legacy systemen te ontsluiten voor moderne AI agents.
5.  **Performance**: Kong is gebouwd op NGINX en is extreem snel en lichtgewicht.

---

## 🛠️ Installatie

We installeren Kong als Ingress Controller (of als Gateway achter NGINX). In DB-less mode is hij stateless en makkelijk te schalen.

### 1. Installatie via Helm
```bash
helm repo add kong https://charts.konghq.com
helm upgrade --install kong kong/kong \
  --namespace api-gateway --create-namespace \
  --set ingressController.installCRDs=false \
  --set dblessConfig.configMap=kong-config
```
*(We installeren CRDs meestal apart om race-conditions te voorkomen)*

---

## 🚀 Gebruik: Policies als Code

De kracht van Kong binnen Druppie is dat de **Builder Agent** policies kan genereren op basis van functionele eisen.

### Scenario: "Bescherm de Drone API tegen overbelasting"
Gebruiker: *"De drone data API mag maximaal 100 requests per minuut ontvangen."*

De Builder Agent genereert een `KongPlugin` manifest:

```yaml
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: rate-limit-100
  namespace: productie
config: 
  minute: 100
  policy: local
plugin: rate-limiting
```

En koppelt deze aan de Service of Ingress:

```yaml
apiVersion: filtering.presidio.com/v1 # Fictief voorbeeld
kind: Ingress
metadata:
  name: drone-api
  annotations:
    konghq.com/plugins: rate-limit-100
    konghq.com/strip-path: "true"
spec:
  ingressClassName: kong
  rules:
  - host: api.druppie.nl
    http:
      paths:
      - path: /v1/drone-data
        pathType: ImplementationSpecific
        backend:
          service:
            name: drone-service
            port:
              number: 80
```

### Andere veelgebruikte Plugins
*   **Key Auth**: `konghq.com/plugins: api-key-auth` (Voor M2M communicatie).
*   **Prometheus**: Exposeert metrics over API gebruik direct naar onze PLG stack.
*   **Correlation ID**: Voegt een `Trace-ID` toe aan de header voor Traceability.

## 🔄 Integratie in Druppie
1.  **Compliance**: De Gateway logt *elk* request. De logs gaan naar **Loki**. Als er misbruik wordt gemaakt van een API, zien we dat direct.
2.  **Versiebeheer**: API changes (v1 -> v2) worden beheerd in de Ingress definities in Git.
3.  **Verbinding met MCP**: Als we externe tools (MCP Servers) ontsluiten, zetten we die achter Kong. Zo kunnen we precies meten hoeveel tokens/calls een specifieke AI-agent verbruikt.
