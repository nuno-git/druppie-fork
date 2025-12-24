---
id: iam-keycloak
name: Identity & Access Management (Keycloak)
type: block
description: "Centralized identity management and SSO using Keycloak."
capabilities: ["authentication", "authorization", "sso", "identity-brokering"]
version: 1.0.0
auth_group: ["developers"]
---
# Identity & Access Management (Keycloak)

## 🎯 Selectie: Keycloak
Voor het beheer van gebruikersidentiteiten, authenticatie en autorisatie kiezen we voor **Keycloak**. Keycloak fungeert als een **Identity Broker** tussen onze applicaties en de centrale gebruikersdirectory (Azure AD / Microsoft Entra ID).

### 💡 Onderbouwing van de Keuze
Waarom Keycloak als tussenlaag en niet direct Azure AD koppelen aan elke applicatie?
1.  **Identity Brokering**: Keycloak ontkoppelt de applicaties van de specifieke Identity Provider (IdP). Als we ooit willen wisselen van IdP of een tweede IdP (bijv. DigiD voor burgers) willen toevoegen, hoeven we de applicaties niet aan te passen. Keycloak regelt de vertaalslag.
2.  **Granulaire RBAC**: We kunnen in Keycloak specifieke rollen en groepen definiëren voor onze apps (bijv. `DroneViewer`, `DroneEditor`) en deze mappen naar Azure AD groepen. Dit houdt de Azure AD schoon en geeft teams meer autonomie.
3.  **Unified Login**: Keycloak biedt één centrale Single Sign-On (SSO) ervaring.
4.  **Kubernetes Native**: Draait als container op het cluster en is eenvoudig te configureren via CRD's (met de Keycloak Operator) of via de API.

---

## 🛠️ Installatie

We installeren Keycloak via de geoptimaliseerde Bitnami Helm chart of operator.

### 1. Installatie via Helm
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm upgrade --install keycloak bitnami/keycloak \
  --namespace iam-system --create-namespace \
  --set auth.adminUser=admin \
  --set auth.adminPassword=SECRET_ADMIN_PW \
  --set service.type=ClusterIP \
  --set postgresql.enabled=false \
  --set externalDatabase.host=druppie-core-db-rw.default.svc.cluster.local \
  --set externalDatabase.user=druppie \
  --set externalDatabase.password=DB_PASSWORD \
  --set externalDatabase.database=keycloak
```
*(Ook hier hergebruiken we de centrale PostgreSQL cluster voor opslag)*

---

## ⚙️ Integratie met Azure AD (Entra ID)

De cruciale stap is het koppelen van Azure AD als upstream Identity Provider.

### 1. Azure AD App Registration
Maak in de Azure Portal een App Registration aan:
*   **Redirect URI**: `https://auth.druppie.nl/realms/druppie/broker/oidc/endpoint`
*   Genereer een **Client Secret**.

### 2. Keycloak Configureren
In de Keycloak Admin Console:
1.  Maak een Realm aan: `druppie`.
2.  Ga naar **Identity Providers** -> **OpenID Connect v1.0**.
3.  **Alias**: `azure-ad`.
4.  **Discovery Endpoint**: `https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration`.
5.  Vul Client ID en Secret in van stap 1.
6.  **Mappers**: Configureer mappers om gebruikersinfo (email, naam, groups) uit het Azure AD token over te nemen naar het Keycloak user profiel.

---

## 🚀 Gebruik in Applicaties

Wanneer de **Builder Agent** een nieuwe frontend bouwt (bijv. een React app), configureert hij deze om gebruik te maken van Keycloak.

### OIDC Configuratie
De applicatie praat **alleen** met Keycloak, niet met Azure.

```json
{
  "authority": "https://auth.druppie.nl/realms/druppie",
  "client_id": "drone-service-frontend",
  "redirect_uri": "https://drone.druppie.nl/callback",
  "response_type": "code",
  "scope": "openid profile email offline_access"
}
```

### Flow
1.  Gebruiker opent de app -> wordt doorgestuurd naar Keycloak.
2.  Keycloak toont knop "Login met Azure AD".
3.  Gebruiker logt in bij Microsoft.
4.  Azure stuurt gebruiker terug naar Keycloak met token.
5.  Keycloak vertaalt dit naar een intern token (met juiste interne rollen).
6.  Keycloak stuurt gebruiker terug naar de App.

## 🔄 Integratie in Druppie
1.  **Applicatie Security**: De *Ingress* controller (zie Webserver bouwblok) kan samenwerken met Keycloak (via OAuth2 Proxy) om applicaties te beveiligen die zelf geen login-logica hebben.
2.  **Audit**: Keycloak logt elke loginpoging. Deze logs worden door **Loki** (zie Observability) opgehaald. Zo zien we precies wie wanneer heeft ingelogd.
