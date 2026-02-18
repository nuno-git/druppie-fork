
## PBI (Story) — Bouwer & Tester Agent

### Story

Als **Developer**

wil ik **een Bouwer- en Tester-agent implementeren die samenwerken volgens Test Driven Development en integreren met de bestaande Planner-agent, waarbij de Coding MCP builds en tests uitvoert**

zodat **code automatisch gebouwd, getest en gevalideerd wordt met een expliciet Pass/Fail-resultaat** .

---

### Acceptatiecriteria (kort & verifieerbaar)

* Er zijn **twee afzonderlijke agents geïmplementeerd** : Bouwer en Tester.
* De Bouwer en Tester **interacteren via een feedback-loop** .
* De Tester valideert **functionele én technische requirements** .
* De Tester kan **tests genereren met (waar mogelijk) 100% code coverage** .
* De samenwerking volgt **Test Driven Development (TDD)** .
* Bij afkeuring door de Tester wordt de Bouwer **automatisch opnieuw aangestuurd** .
* De feedback-loop ondersteunt een **configureerbaar maximum aantal retries (x)** .
* De Tester levert per run een **expliciet Pass/Fail-resultaat inclusief onderbouwing** .
* De Tester bepaalt of de build **voldoende kwaliteit heeft voor acceptatie** .
* De bestaande **Planner-agent stuurt de Bouwer en Tester aan via toegevoegde instructies** .
* De Coding MCP moet worden uitgebreid met bijvoorbeeld het **uitvoeren van build- en test-commands als tool** .

---

### Context / Links

* **Ontwerp / Mock:** Nog te bepalen
* **Besluit / Notulen:** Nog te bepalen

**Gerelateerd:**

* Bestaande Planner Agent
* Architectuur Agents
* Coding MCP

---

### Taken (uit te voeren door Developer)

* Implementeren van Bouwer-agent
* Implementeren van Tester-agent
* Definiëren van interfaces en contracten tussen Bouwer en Tester
* Implementeren van TDD-flow (test → build → test)

meeting in plannen: zelf met ideeen komen, in meeting bespreken/bepalen. (robbe meeting)

* Opzetten van Bouwer ↔ Tester feedback-loop
* Implementeren van retry-mechanisme met maximale pogingen
* Ontwerpen en implementeren van Pass/Fail-resultaatstructuur
* Toevoegen van instructies/configuratie aan de **bestaande Planner-agent**
* Integreren en verbeteren van Coding MCP als uitvoerende tool (Nuno)
* Testen van Bouwer en Tester afzonderlijk
* Testen van end-to-end flow via Planner → Bouwer → Tester
* Documenteren van resultaten per run (geslaagd / niet geslaagd)

test gedeelte: Robbe

developer gedeelte: Nuno, Sjoerd
