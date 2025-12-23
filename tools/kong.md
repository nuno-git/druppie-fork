# 🦍 Kong Manager - API Gateway

## Wat is het?
Kong Manager is de grafische interface voor de Kong API Gateway. Kong beheert al het inkomende verkeer naar het platform (Ingress Controller).

## Waarvoor gebruik je het?
- **Routes & Services**: Zien welke URL's naar welke interne services leiden.
- **Plugins**: Configureren van plugins zoals Rate Limiting, Authenticatie of Transformaties.
- **Troubleshooting**: Bekijken van de status van de gateway routes.

## Inloggen
- **URL**: [https://kong.localhost](https://kong.localhost)
- **Gebruikersnaam**: (Open in OSS versie, of basic auth indien geconfigureerd)
- **Wachtwoord**: Zie het `.secrets` bestand (`DRUPPIE_KONG_PASS`)

## Hoe te gebruiken
1. **Services**: Bekijk de gedefinieerde backends (bijv. `gitea`, `grafana`).
2. **Routes**: Zie welke hostnames (`*.localhost`) gekoppeld zijn aan welke service.
3. **Plugins**: Activeer plugins op specifieke routes (bijv. Keycloak authenticatie).
