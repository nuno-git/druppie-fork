# Druppie-92: Sessie Simulatie & End-to-End Test Framework

## User Story

**Als** developer/QA in het Druppie-team,
**wil ik** agent-sessies kunnen simuleren met YAML-definities en uitkomsten automatisch valideren,
**zodat** ik agent-gedrag snel kan testen zonder handmatige interactie, regressies vroegtijdig kan opsporen en de kwaliteit van agent-output op schaal kan beoordelen.

## Achtergrond

Het handmatig testen van agent-sessies is traag en foutgevoelig. Elke testcyclus vereist dat een developer handmatig met agents communiceert, HITL-goedkeuringen doorklikt en resultaten visueel inspecteert. Er was geen geautomatiseerde manier om sessies te draaien, tool call-uitkomsten te valideren of outputkwaliteit te beoordelen. Dit framework introduceert YAML-gestuurde sessiesimulatie zodat tests herhaalbaar, automatiseerbaar en uiteindelijk in CI te draaien zijn.

## Scope

### 1. YAML-gestuurde Sessie Simulatie (kern)
- Definieer complete sessieflows in YAML: tool calls, verwachte resultaten, foutscenario's
- Sessies voeren echte MCP tool calls uit tegen echte services (coding server, Docker server, Gitea)
- `continue_session: true` maakt chaining mogelijk — draai een setup-sessie en ga verder met een andere agent/test
- Per-stap `mock: true` vlag om dure calls over te slaan zonder globale blocklist
- Result validators controleren zowel `result` als `error_message` velden per stap

### 2. HITL (Human-in-the-Loop) Simulatie
- HITL-goedkeuringsstappen worden automatisch afgehandeld op basis van YAML-profielconfiguratie (`testing/profiles/hitl.yaml`)
- Agent-tests kunnen auto-answer regels definiëren voor menselijke goedkeuringsstappen
- Maakt volledig onbemande agent-testruns mogelijk die normaal zouden blokkeren op menselijke input

### 3. LLM-als-Beoordelaar (Judge) Evaluatie
- LLM-judge beoordeelt agent-outputkwaliteit aan de hand van criteria in natuurlijke taal (bijv. "FD moet in het Nederlands zijn", "geen solution bias")
- Judge checks gedefinieerd in `testing/checks/*.yaml` met herbruikbare criteria
- **Judge Eval** tests valideren de judge zelf met verwachte slaag/faal-uitkomsten — voorkomt vals vertrouwen door een kapotte judge

### 4. Analytics & Rapportage
- Analytics-pagina met filtering per batch en Check Explorer
- Drill-down weergave met ruwe LLM input/output en tool call details
- Test-uitvoering UI om testruns te starten en te monitoren vanuit de frontend

## Test Types

| Type | Wat het doet | Voorbeeld |
|------|-------------|-----------|
| **Tool test** | Ketens van echte MCP tool calls met resultaatvalidatie | `create-todo-app.yaml` — zet intent, maakt FD, deployt app |
| **Agent test** | Echte LLM-agent draait met HITL auto-beantwoording | `router-picks-correct-project.yaml` — 3 setup-sessies + router |
| **LLM Judge** | LLM beoordeelt agent-outputkwaliteit | `architect-reviews-fd.yaml` — controleert FD-kwaliteitscriteria |
| **Judge Eval** | Test de judge zelf met bekende goede/slechte input | `judge-catches-biased-fd.yaml` — expected: false |

## Acceptatiecriteria

- [ ] Tool tests voeren echte MCP calls uit en valideren resultaten volgens YAML-spec
- [ ] Agent tests draaien volledige agent-loops met automatisch afgehandelde HITL-gates
- [ ] `continue_session` hervat correct vanuit de state van een eerdere sessie
- [ ] LLM-judge produceert slaag/faal met onderbouwing op basis van gedefinieerde checks
- [ ] Judge eval tests detecteren een verkeerd geconfigureerde judge (verwachte uitkomst mismatch = falen)
- [ ] Analytics-pagina toont batchresultaten met filtering, drill-down naar ruwe LLM I/O
- [ ] `create-todo-app` tool test deployt een echte werkende app end-to-end
- [ ] Alle testdefinities staan in `testing/` als YAML — geen hardcoded testlogica

## Belangrijke Bestanden

- `testing/` — alle YAML testdefinities, checks, profielen
- `druppie/testing/` — runner, executor, schema, validators, judge
- `druppie/api/routes/evaluations.py` — testuitvoering & analytics API
- `frontend/src/pages/Analytics.jsx` — analytics dashboard
- `frontend/src/pages/Evaluations.jsx` — testuitvoering UI
- `docs/TESTING.md` — framework documentatie
