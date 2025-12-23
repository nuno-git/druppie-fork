# 🐙 Gitea - Git Version Control

## Wat is het?
Gitea is de Git server van het platform. Het is een lichtgewicht alternatief voor GitHub/GitLab en beheert alle broncode en configuraties (GitOps).

## Waarvoor gebruik je het?
- **Source Code**: Opslaan en versiebeheer van applicatiecode.
- **GitOps**: Opslaan van Kubernetes manifesten die door Flux CD worden uitgerold.
- **Pull Requests**: Samenwerken aan codewijzigingen.

## Inloggen
- **URL**: [https://gitea.localhost](https://gitea.localhost)
- **Gebruikersnaam**: `druppie_admin`
- **Wachtwoord**: Zie het `.secrets` bestand (`DRUPPIE_GITEA_PASS`)

## Hoe te gebruiken
1. Log in om repositories te bekijken of aan te maken.
2. Clone repositories lokaal: `git clone https://gitea.localhost/druppie_admin/mijn-repo.git`.
3. Gebruik Access Tokens voor CI/CD integraties.
