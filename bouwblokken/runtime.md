# Runtime Interface

## 🎯 Doelstelling
Dit bouwblok definieert de **interface** naar de Runtime omgeving. In de Azure Foundry architectuur bestaat deze runtime uit twee delen: de **Agent Runtime** (Azure AI Agent Service) voor de intelligentie, en de **Container Runtime** (Kubernetes/ACA) voor de workloads.

## 📋 Functionele Specificaties

### 1. Agent Runtime (Azure AI Agent Service)
- **Host**: De beheerde omgeving waar AI-agenten (Threads, Runs) worden uitgevoerd.
- **State Management**: Automatisch beheer van conversatie-state en context (persistentie).
- **Tool Execution**: Veilige uitvoering van code (Code Interpreter) en API-calls via OpenAPI.

### 2. Deployment Management (Container Runtime)
- **Manifest Application**: Vertalen van abstracte deployment intenties naar concrete Kubernetes manifests of Azure Container Apps.
- **Rollout Control**: Beheren van updates en rollbacks (Blue/Green).

### 3. Resource Provisioning aka "Dynamic Slots"
- **Namespace on Demand**: Aanmaken van geïsoleerde omgevingen voor nieuwe projecten.
- **Quota Management**: Toewijzen van CPU/Memory limieten.

## 2. Security & Compliance
- **Entra Agent ID**: Elke agent draait onder zijn eigen Managed Identity.
- **Network Isolation**: Alle communicatie verloopt via Private Endpoints binnen het VNet.

## 🏗️ Relaties
- **Verwijst naar**: [Runtime Domein](../runtime/overview.md).
- **Wordt gebruikt door**: [Druppie Core](./druppie_core.md) en [Build Plane](./build_plane.md).
