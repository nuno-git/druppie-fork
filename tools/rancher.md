# 🤠 Rancher - Cluster Management

## Wat is het?
Rancher is een interface voor het beheren van Kubernetes clusters. Het maakt het eenvoudig om workloads, nodes en netwerken te visualiseren en te beheren.

## Waarvoor gebruik je het?
- **Cluster Overzicht**: Zien welke nodes en pods draaien.
- **Troubleshooting**: Logs en events van pods bekijken.
- **Workload Management**: Deployments schalen, herstarten of aanpassen via een UI.

## Inloggen
- **URL**: [https://rancher.localhost](https://rancher.localhost)
- **Gebruikersnaam**: `admin`
- **Wachtwoord**: Zie het `.secrets` bestand (wordt gegenereerd als `DRUPPIE_RANCHER_PASS` of staat in logs).

## Hoe te gebruiken
1. Selecteer het "local" cluster.
2. Ga naar **Workloads** om applicaties te zien.
3. Gebruik de **Shell** knop om direct een kubectl shell in de browser te openen.
