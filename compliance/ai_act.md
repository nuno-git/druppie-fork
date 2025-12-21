# De AI Act & Implementatie Waterschappen

## 📜 Wetgevend & Sector Kader
**Europese Unie**: Regulation (EU) 2024/1689 (Artificial Intelligence Act)
**Nederland**: Uitvoeringswet AI-verordening (Toezichthouder: AP / RDI)
**Sector**: Unie van Waterschappen (UvW) Implementatiehandleiding

De AI Act is 's werelds eerste alomvattende AI-wetgeving met een **risico-gebaseerde aanpak**. Voor waterschappen is dit extra relevant omdat zij beheerders zijn van **kritieke infrastructuur** (dijken, zuiveringen, gemalen). De UvW heeft specifieke handreikingen opgesteld om de abstracte wet te vertalen naar de watersector.

---

## 🤖 Risico Classificatie (De Piramide)

De wet onderscheidt risiconiveaus. De UvW benadrukt de specifieke context voor waterschappen hierin:

### 1. Onaanvaardbaar Risico (Verboden)
*   *Wet*: Social Scoring, Real-time biometrische identificatie in openbare ruimte (door politie), manipulatie van gedrag.
*   *Actie*: **BLOKKEREN**. De Policy Engine mag dit nooit goedkeuren.

### 2. Hoog Risico (Strenge Eisen)
Dit is de focus voor **Druppie Core**.
*   *Wet*: AI in kritieke infrastructuur, HR-selectie, Kredietwaardigheid.
*   *Waterschap Context (UvW)*: 
    *   AI die veiligheidscomponenten van waterkeringen of sluizen aanstuurt.
    *   AI die beslissingen neemt over waterpeilbeheer (risico op overstroming/droogte).
*   *Actie*: Vereist **Conformiteitsbeoordeling**, **Human Oversight**, **Hoogwaardige DataSets**, en **Logging**.

### 3. Beperkt Risico (Transparantie)
*   *Wet*: Chatbots (zoals de Druppie Copilot), Deepfakes/GenAI.
*   *Actie*: **Transparantieplicht**. De gebruiker moet weten dat hij met een AI praat. ("Ik ben Druppie, een AI-assistent").

### 4. Minimaal Risico
*   *Voorbeelden*: Spamfilters, Muskusrat-tellingen (zonder automatische actie).

---

## 🌊 De AI Impact Assessment (AIIA)
De UvW schrijft voor om *vóór* de start van elk AI-project een **AIIA** uit te voeren. Dit gaat verder dan een DPIA.

1.  **Doelbinding**: Is het maatschappelijk verantwoord?
2.  **Dataset Representativiteit**: 
    *   *Cruciaal voor water*: Is het model getraind op data van zowel extreme 'natte' als 'droge' jaren (bijv. 2018)?
    *   *Bias*: Voorkom dat het model alleen werkt voor scenario's uit het verleden die door klimaatverandering niet meer representatief zijn.
3.  **Uitlegbaarheid (XAI)**: Kan een hydroloog begrijpen *waarom* het model voorstelt de stuw te sluiten? "Black box" modellen zijn ongewenst voor kritieke processen.

---

## 🛠️ Implementatie in Druppie

Hoe borgen we de wet en de UvW richtlijnen in het platform?

### Stap 1: Intake & Classificatie (Policy Engine)
Wanneer een gebruiker een nieuw project start, activeert de Policy Engine de **UvW Template**.
*   **Check**: "Raakt dit systeem de veiligheid van waterkeringen?"
    *   *Ja* -> Markeer als **Hoog Risico**. Activeer "Four-Eyes Principle" (Menselijke goedkeuring vereist).

### Stap 2: Data Validatie & Versiebeheer (DVC)
Om te voldoen aan de eis voor "Hoogwaardige Datasets":
*   **DVC (Data Versioning)**: Garandeert dat we altijd kunnen bewijzen op welke dataset is getraind.
*   **Automated Checks**: De **Builder Agent** kan controleren of de dataset voldoende spreiding heeft (seizoenen, extremen).

### Stap 3: Traceability & Logging (Juridisch Bewijs)
*   **Eis**: Automatische logging van events gedurende de levenscyclus (Artikel 12).
*   **Oplossing**: De **Traceability DB** (Tempo/Loki). Elke stap van "Input Foto" tot "Beslissing: Schade" wordt onwijzigbaar vastgelegd. Dit is cruciaal voor de bestuurlijke verantwoording.

### Stap 4: Menselijk Toezicht (Human-in-the-Loop)
*   **Eis**: Een mens moet kunnen ingrijpen (Artikel 14).
*   **Oplossing**: Voor autonome systemen (gemalen/sluizen) bouwen we altijd een **Kill Switch**. De operator kan de AI overrulen via het SCADA dashboard.

### Stap 5: Continuous Monitoring (Model Drift)
Een model veroudert.
*   **Grafana**: Monitor **Model Drift**. "Wijkt de voorspelling steeds vaker af van de peilbuis-meting?"
*   **Policy**: Verplicht jaarlijkse herijking/hertraining.

---

## ✅ Checklist voor de Architect / Policy Engine
1.  [ ] **Risk Assessment**: Is de UvW risico-classificatie uitgevoerd?
2.  [ ] **Human-in-the-Loop**: Is er voor Hoog Risico systemen een menselijke goedkeuringsstap (of noodstop) ingebouwd?
3.  [ ] **Data Quality**: Is de dataset representatief voor (toekomstige) klimaattoestanden?
4.  [ ] **Audit Trail**: Worden alle inputs/outputs gelogd in de Traceability DB?
5.  [ ] **Transparency**: Maakt de interface duidelijk dat het een AI is?
