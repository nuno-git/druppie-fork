# 🔐 Keycloak - Identity & Access Management

## Wat is het?
Keycloak is de centrale authenticatie- en autorisatieserver van het Druppie Platform. Het beheert gebruikers, groepen en rollen en verzorgt de Single Sign-On (SSO) voor alle andere applicaties.

## Waarvoor gebruik je het?
- **Gebruikersbeheer**: Aanmaken en beheren van accounts.
- **Single Sign-On**: Eén keer inloggen voor Gitea, Grafana, Argo, etc.
- **Rollen & Rechten**: Bepalen wie toegang heeft tot welke applicatie.

## Inloggen
- **URL**: [https://keycloak.localhost](https://keycloak.localhost) (of jouw domein)
- **Gebruikersnaam**: `admin`
- **Wachtwoord**: Zie het `.secrets` bestand (`DRUPPIE_KEYCLOAK_PASS`)

## Hoe te gebruiken
1. Ga naar de **Administration Console**.
2. Log in met de admin gegevens.
3. Beheer 'Realms' (standaard is er vaak een `bedrijfsnaam of applicatienaam` realm).
4. Onder **Users** kun je nieuwe teamleden toevoegen.
5. Onder **Clients** zie je de gekoppelde applicaties.
