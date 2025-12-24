---
id: iaas-terraform
name: Infrastructure as Code (Terraform/OpenTofu)
type: block
version: 1.0.0
auth_group: ["provisioning"]
description: "provisioneren van infrastructuur"
capabilities: ["iaas"]
---

# Infrastructure as Code (Terraform/OpenTofu)

## 🎯 Selectie: OpenTofu (Terraform)
Voor het provisioneren van infrastructuur binnen het Druppie platform is gekozen voor **OpenTofu** (de open-source fork van Terraform). Dit stelt ons in staat om infrastructuur declaratief te definiëren en te beheren als code.

### 💡 Onderbouwing van de Keuze
De keuze voor OpenTofu/Terraform is gebaseerd op de volgende kernwaarden:

1.  **Declaratief Model**: Definieer *wat* je wilt (bijv. een Kubernetes cluster, een S3 bucket), niet *hoe* het gemaakt moet worden. Dit sluit 1-op-1 aan bij de **Spec-Driven Architecture** van Druppie.
2.  **Cloud Agnostisch**: Hoewel providers specifiek zijn, is de workflow (init, plan, apply) identiek voor Azure, AWS, Google Cloud en on-premise (VMware/Proxmox). Dit ondersteunt de hybride runtime strategie.
3.  **State Management**: Terraform houdt de staat van de infrastructuur bij. Dit is cruciaal voor de **Builder Agent** om te weten wat er al bestaat en wat er gewijzigd moet worden (drift detection).
4.  **Enorme Ecosystem**: Er zijn providers voor bijna alles (Azure, Kubernetes, Helm, Keycloak, Grafana), waardoor we de hele stack met één tool kunnen beheren.

### ⚙️ Implementatie in Druppie
Binnen de architectuur vervult Terraform een specifieke rol in de **Build Plane**:

*   **Gegenereerd door AI**: De **Builder Agent** schrijft Terraform configuraties (`.tf` files) op basis van de functionele specificaties.
*   **Execution in Foundry**: De Tekton pipelines draaien `tofu plan` en `tofu apply` in een gecontroleerde omgeving.
*   **Integratie met Compliance**: Terraform plannen worden vóór uitvoering gevalideerd door tools zoals **Trivy** (IaC scanning) om te garanderen dat er geen onveilige infrastructuur wordt uitgerold (bijv. open storage buckets).

### 🛠️ Voorbeeld Spec
Een voorbeeld van hoe een Terraform definitie eruit ziet die door de Agent gegenereerd kan worden:

```hcl
resource "azurerm_kubernetes_cluster" "druppie_cluster" {
  name                = "druppie-prod"
  location            = "West Europe"
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = "druppie-k8s"

  default_node_pool {
    name       = "default"
    node_count = 3
    vm_size    = "Standard_D2_v2"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Environment = "Production"
    ManagedBy   = "DruppieAgent"
  }
}
```
