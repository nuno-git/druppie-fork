# Policy Enforcement (Kyverno)

## 🎯 Selectie: Kyverno
Voor het technisch afdwingen en rapporteren van *Security by Design* en *Compliance by Design* regels binnen de Kubernetes runtime kiezen we voor **Kyverno**. Kyverno is een Kubernetes-native Policy Engine.

### 💡 Onderbouwing van de Keuze
Waar traditionele tools zoals OPA Gatekeeper een complexe, losstaande taal (Rego) vereisen, gebruikt Kyverno gewoon **YAML** voor zijn policies. Dit past perfect in onze "Alles is YAML" strategie met de Builder Agent.

1.  **Simpel & Declaratief**: Policies zien eruit als Kubernetes resources. De AI (en de mens) kan ze makkelijk lezen en schrijven.
2.  **Validate, Mutate, Generate**:
    *   *Validate*: Blokkeer een Pod als hij als `root` draait.
    *   *Mutate*: Voeg automatisch een `cost-center` label toe aan elke Namespace.
    *   *Generate*: Maak automatisch een `NetworkPolicy` (Deny-All) aan bij elk nieuw project.
3.  **Reporting**: Kyverno genereert `PolicyReport` objecten in het cluster. Deze zijn direct uitleesbaar door tools als Grafana of een compliance dashboard.

---

## 🛠️ Installatie

Kyverno draait als Admission Controller in het cluster.

### Installatie via Helm
```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm upgrade --install kyverno kyverno/kyverno \
  --namespace policy-system --create-namespace \
  --set replicaCount=3 \
  --set admissionController.replicas=3
```

---

## 🚀 Gebruik: Van Regel naar Handhaving

### Scenario: "Verplicht AI Register"
Vanuit de compliance regels (zie [AI Register](../compliance/ai_register.md)) is de eis: *Geen deployment zonder verwijzing naar een algoritme ID.*

### De Policy (YAML)
We definiëren een `ClusterPolicy` die dit controleert:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-algorithm-id
spec:
  validationFailureAction: Enforce # Blokkeer deployment! (Of 'Audit' voor alleen loggen)
  rules:
  - name: check-label
    match:
      resources:
        kinds:
        - Deployment
    validate:
      message: "Deze deployment moet een 'algorithm-id' label hebben conform de AI Act."
      pattern:
        metadata:
          labels:
            algorithm-id: "?*" # Moet minimaal 1 karakter zijn
```

### De Rapportage
Kyverno maakt continu rapporten aan: `kubectl get policyreports`.

**In Grafana Dashboard:**
We bouwen een Compliance Dashboard dat deze rapporten uitleest.
*   ✅ **Green**: 95% van de workloads voldoet aan de eisen.
*   🔴 **Red**: Project "Drone-V1" faalt op "Non-Root" check.

Hierdoor heeft de CISO (Chief Information Security Officer) real-time inzicht: "Zijn we NU compliant?", in plaats van een jaarlijkse papieren audit.

## 🔄 Integratie in Druppie
1.  **CISO Component**: De Mens-in-de-Loop kan via Kyverno "Exceptions" goedkeuren (bijv. voor een tijdelijke test).
2.  **Builder Agent**: Voordat de agent probeert te deployen, kan hij de YAML valideren tegen de Kyverno CLI (`kyverno apply policy.yaml --resource deploy.yaml`) om "afwijzing aan de poort" te voorkomen.
