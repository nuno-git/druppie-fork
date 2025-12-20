# **Architecturaal Blauwdruk voor Centraal Beheerde Agentic AI: Een Enterprise Design met Microsoft Foundry en Microsoft 365 Copilot**

## **Executive Summary**

De snelle evolutie van generatieve AI binnen enterprises verschuift de focus van geïsoleerde chatbots naar geïntegreerde, autonome 'Agentic AI'-systemen. Organisaties worden geconfronteerd met de uitdaging om deze krachtige agenten niet alleen te faciliteren, maar ook centraal te beheersen, te beveiligen en te orkestreren. Dit onderzoeksrapport presenteert een gedetailleerd architecturaal ontwerp voor een **Centraal AI Control Plane**, gebaseerd op de synergie tussen **Microsoft Foundry** (voorheen Azure AI Foundry) als de backend 'Agent Factory' en **Microsoft 365 Copilot** als de primaire gebruikersinterface.

Het voorgestelde ontwerp adresseert specifiek de vereiste voor "spec-driven agent creatie", waarbij agenten programmatisch worden gegenereerd op basis van gestandaardiseerde definities (Agent-as-Code). Dit mechanisme garandeert consistentie, versiebeheer en strikte governance. Door een centrale 'Router Agent' te implementeren die fungeert als verkeersleider voor gespecialiseerde sub-agenten, wordt een hub-and-spoke model gerealiseerd dat schaalbaarheid combineert met centrale controle. Dit rapport synthetiseert technische documentatie, architecturale patronen en best practices tot een rigoureus implementatieplan voor de moderne AI-gestuurde onderneming.

## **1\. Strategische Context: Van Chatbots naar de 'Agent Factory'**

Het landschap van enterprise AI ondergaat een fundamentele transformatie. Waar de eerste golf van adoptie zich richtte op "chat with your data" (RAG) toepassingen, beweegt de markt zich nu richting **Agentic AI**. In tegenstelling tot passieve modellen die enkel reageren op prompts, bezitten AI-agenten het vermogen om waar te nemen, te redeneren, te handelen en te leren.1 Ze kunnen autonoom workflows orkestreren, externe tools aanroepen en samenwerken met andere agenten om complexe, meerstaps problemen op te lossen.2

Deze verschuiving brengt echter aanzienlijke risico's met zich mee. Zonder een gecentraliseerde strategie ontstaat "Shadow AI": een wildgroei aan onbeheerde agenten die opereren buiten het zicht van IT-governance, wat leidt tot datalekken, inconsistente beveiliging en ondoorzichtige kostenstructuren.3

### **1.1 De Noodzaak van Centrale Controle**

Centrale controle in een multi-agent ecosysteem impliceert niet noodzakelijkerwijs een monolithische architectuur, maar eerder een georkestreerd federatief model. Het doel is om een **Single Pane of Glass** te creëren voor:

* **Identiteitsbeheer:** Wie of wat is de agent en wat mag deze doen?  
* **Levenscyclusbeheer:** Hoe worden agenten gecreëerd, geüpdatet en uitgefaseerd?  
* **Observability:** Wat doen de agenten in real-time en hoe presteren ze?  
* **Orkestratie:** Hoe wordt een gebruikersvraag toegewezen aan de juiste specialist?

De gebruiker vraagt specifiek om een oplossing waarbij **Microsoft 365 Copilot** fungeert als de interface. Dit is een strategisch verstandige keuze, aangezien het de drempel voor adoptie verlaagt door AI te integreren in de tools waar medewerkers dagelijks werken (Teams, Outlook, Word). De uitdaging ligt in het koppelen van deze laagdrempelige frontend aan een krachtige, op Azure gehoste backend die voldoet aan strenge enterprise-eisen.

### **1.2 Microsoft Foundry als Fundament**

Microsoft Foundry (voorheen Azure AI Studio/Foundry) positioneert zich als het verenigende platform voor deze architectuur. Het markeert de overgang van Infrastructure-as-a-Service (IaaS) AI naar Platform-as-a-Service (PaaS) Agents.3 Foundry consolideert modellen, tooling, veiligheidsevaluaties en orkestratie in één controlepaneel.4 Dit is cruciaal voor de realisatie van "spec-driven creatie", omdat Foundry robuuste API's en SDK's biedt om de creatie en configuratie van agenten te automatiseren, los van de handmatige handelingen in een portal.

## **2\. Kernarchitectuur: Het Centrale Control Plane**

Om te voldoen aan de eisen voor centrale controle en spec-driven creatie, stelt dit rapport een gelaagde architectuur voor. De kern wordt gevormd door de **Azure AI Agent Service**, die de complexiteit van infrastructuurbeheer abstraheert en native ondersteuning biedt voor stateful interacties en tool-aanroepen.5

### **2.1 De Azure AI Agent Service**

De Azure AI Agent Service fungeert als de runtime-engine. Het biedt een beheerde omgeving waarin agenten kunnen draaien, schalen en interacteren. Voor een oplossing die gericht is op centrale controle, zijn de volgende eigenschappen van de Agent Service doorslaggevend:

| Functionaliteit | Relevantie voor Centrale Controle | Bron |
| :---- | :---- | :---- |
| **Stateful Execution** | De service beheert automatisch de gespreksgeschiedenis (threads) en context, wat essentieel is voor complexe multi-turn conversaties zonder dat ontwikkelaars externe databases hoeven te beheren. | 6 |
| **Managed Identity** | Integratie met Microsoft Entra ID (voorheen Azure AD) maakt het mogelijk om elke agent een eigen identiteit te geven, waardoor fijnmazige toegangscontrole (RBAC) tot data en tools mogelijk is. | 7 |
| **Open Standaarden** | Ondersteuning voor het Model Context Protocol (MCP) en Agent-to-Agent (A2A) protocollen zorgt ervoor dat de centrale orkestrator kan communiceren met diverse agenten, ongeacht hun interne implementatie. | 8 |
| **Bring Your Own Storage** | Organisaties kunnen hun eigen Azure Storage en Cosmos DB accounts koppelen, wat cruciaal is voor datasoevereiniteit en compliance. | 9 |

### **2.2 Het 'Hub-and-Spoke' Orkestratiemodel**

De architectuur volgt een **Hub-and-Spoke** patroon (ook wel Router-pattern genoemd). Hierbij fungeert één centrale agent (de Hub) als de poortwachter en verkeersleider voor een netwerk van gespecialiseerde agenten (de Spokes).

* **De Hub (Router Agent):** Deze agent heeft als enige taak het analyseren van de intentie van de gebruiker en het routeren van de vraag naar de juiste specialist. De Hub beschikt over een register van alle beschikbare Spoke-agenten en hun capabilities.10  
* **De Spokes (Specialist Agents):** Dit zijn domeinspecifieke agenten (bijv. "HR Specialist", "IT Support", "Data Analist"). Ze zijn uitgerust met specifieke tools en kennisbanken die relevant zijn voor hun domein.

Dit model maakt centrale controle mogelijk doordat alle interacties via de Hub verlopen. Beleidsregels, logging en authenticatie kunnen centraal op de Hub worden afgedwongen voordat een verzoek wordt doorgestuurd.

## **3\. Spec-Driven Agent Creatie: De 'Agent Factory'**

Een kernvereiste van het ontwerp is "spec-driven agent creatie". Dit impliceert een **Agent-as-Code** methodologie, waarbij de configuratie van een agent niet handmatig in een GUI wordt samengeklikt, maar wordt gedefinieerd in code (JSON/YAML) en via een geautomatiseerde pipeline wordt uitgerold.

### **3.1 De Agent Specificatie (Het Schema)**

De basis van dit systeem is een gestandaardiseerd schema dat een agent volledig beschrijft. Dit schema abstraheert de technische details van de Azure AI Agent Service REST API naar een beheerbaar formaat voor de organisatie.

Een hypothetisch YAML-schema voor een agent-definitie zou er als volgt uit kunnen zien:

YAML

agent\_config:  
  id: "finance\_analyst\_v1"  
  name: "Financieel Analist"  
  version: "1.0.0"  
  description: "Assisteert bij financiële vraagstukken en data-analyse."  
  model:   
    deployment\_name: "gpt-4o"  
    temperature: 0.2  
    
governance:  
  owner: "Finance Dept"  
  cost\_center: "CC-1234"  
  access\_level: "confidential"

instructions: |  
  Je bent een expert in financiële analyse.   
  Gebruik de beschikbare tools om kwartaalcijfers op te halen.  
  Geef antwoorden in tabelvorm.

tools:  
  \- type: code\_interpreter  
  \- type: file\_search  
    vector\_store\_id: "vs\_finance\_docs"  
  \- type: function  
    name: "get\_stock\_price"  
    spec\_url: "https://api.internal/finance/openapi.json"

### **3.2 De Instantiation Pipeline (CI/CD)**

De realisatie van de "Spec-Driven" aanpak vereist een **Agent Factory Pipeline**. Dit is een automatiseringsproces (bijv. in Azure DevOps of GitHub Actions) dat getriggerd wordt wanneer een nieuwe of gewijzigde agent-specificatie naar de repository wordt gepusht.

Het proces verloopt in vier fasen:

1. **Validatie:** De pipeline valideert de YAML-specificatie tegen organisatorische beleidsregels. Bijvoorbeeld: "Mag de afdeling Marketing gebruikmaken van het gpt-4o model?" of "Is de code\_interpreter tool toegestaan voor deze veiligheidsclassificatie?".11  
2. **Resource Provisioning:** Indien de specificatie afhankelijkheden heeft die nog niet bestaan (zoals een nieuwe Vector Store of een Azure AI Search index), worden deze resources programmatisch aangemaakt via Bicep of Terraform templates.12  
3. **Agent Instantiatie:** De pipeline roept de **Azure AI Agent Service REST API** (POST /assistants) aan om de agent daadwerkelijk te creëren of te updaten in het Foundry project.13 Hierbij worden de instructies, modelkeuze en tool-configuraties vanuit de YAML vertaald naar de API-payload.  
4. **Registratie:** Na succesvolle creatie wordt de unieke Agent ID (bijv. asst\_abc123) teruggestuurd en geregistreerd in een centrale **Agent Registry** (bijv. een Azure SQL Database of Cosmos DB). Deze registry is de bron van waarheid voor de Router Agent om te weten welke specialisten beschikbaar zijn.8

### **3.3 Dynamische Tool-Toewijzing**

Een cruciaal aspect van spec-driven creatie is het dynamisch koppelen van tools. De Agent Service ondersteunt **OpenAPI Tools**, waarmee agenten kunnen communiceren met externe REST API's.14 In de spec-driven aanpak hoeft een ontwikkelaar alleen de URL naar de OpenAPI (Swagger) definitie op te geven. De Factory-pipeline haalt deze definitie op en configureert de agent automatisch met de juiste authenticatie (bij voorkeur via Managed Identity), waardoor de agent direct in staat is om complexe bedrijfsfuncties uit te voeren.13

## **4\. Integratie: Microsoft 365 Copilot als Interface**

De "laatste mijl" van de architectuur is het ontsluiten van deze krachtige Azure-backend via de vertrouwde interface van Microsoft 365 Copilot. De gebruiker wil Copilot gebruiken, maar de intelligentie moet komen van de centraal beheerde Azure-agenten.

### **4.1 Declarative Agents voor M365**

Om de Azure-agenten beschikbaar te maken in M365 Copilot, maken we gebruik van **Declarative Agents** (voorheen Copilot Extensions/Plugins).16 Een Declarative Agent is een lichtgewicht configuratiebestand (manifest) dat in M365 wordt geladen. Het definieert de identiteit van de agent (naam, icoon) en, belangrijker nog, de **Acties** die het kan uitvoeren.

In dit ontwerp configureren we een Declarative Agent die fungeert als een "thin client". Deze agent bevat zelf geen complexe logica, maar is geconfigureerd met een REST API-actie die alle gebruikersinvoer doorstuurt naar onze Azure-backend.

### **4.2 De Proxy Pattern: Azure Functions als Brug**

Omdat de protocollen van M365 Copilot en de Azure AI Agent Service niet direct één-op-één compatibel zijn (M365 spreekt de taal van Teams/Bot Framework, terwijl de Agent Service een OpenAI-achtige API hanteert), is een tussenlaag noodzakelijk. We introduceren een **Azure Function Proxy**.17

De rol van deze proxy is veelzijdig:

1. **Protocol Translatie:** Het ontvangt de JSON-payload van M365 Copilot, extraheert de gebruikersvraag en de context, en vertaalt dit naar een verzoek voor de Azure AI Agent Service.  
2. **Sessie Beheer:** M365 Copilot stuurt een conversationId. De proxy moet deze ID mappen naar een threadId in de Azure AI Agent Service. Als de gebruiker voor het eerst contact opneemt, creëert de proxy een nieuwe thread (POST /threads) en slaat de mapping op in een snelle key-value store (zoals Azure Cosmos DB of Redis).19  
3. **Authenticatie Brug:** De proxy valideert het inkomende token van M365 (om te garanderen dat het verzoek van een legitieme gebruiker in de tenant komt) en gebruikt vervolgens zijn eigen Managed Identity om veilig te communiceren met de Azure AI Agent Service. Hierdoor hoeven API-sleutels nooit te worden blootgesteld aan de client-zijde.20

### **4.3 Deep Linking en Contextuele Integratie**

Een krachtig mechanisme om de integratie te verdiepen is het gebruik van **Deep Links**. Wanneer een agent in de Azure-backend bepaalt dat een taak te complex is voor chat (bijv. het visualiseren van een complex dashboard), kan deze een Adaptive Card genereren met een deep link naar een specifieke Teams Tab of applicatie. Deze link kan context-parameters (zoals de threadId) bevatten, zodat de gebruiker naadloos kan overschakelen van de chat in Copilot naar een gespecialiseerde applicatie zonder de context te verliezen.21

## **5\. Orkestratie en Multi-Agent Patronen**

De "centrale multi-agent" vereiste wordt ingevuld door specifieke orkestratiepatronen toe te passen binnen de Azure-backend.

### **5.1 Het Router/Dispatcher Patroon**

Zoals eerder genoemd, vormt de Router Agent de ingang. Wanneer de Proxy Function een verzoek doorstuurt naar de Agent Service, komt dit eerst bij de Router.

* De Router gebruikt zijn "kennis" (verkregen uit de Agent Registry) om te bepalen welke gespecialiseerde agent het verzoek moet afhandelen.  
* Als de vraag luidt: "Wat is de status van factuur 123?", herkent de Router dit als een financiële vraag en roept de "Finance Agent" aan.  
* In de Azure AI Agent Service kan dit worden geïmplementeerd via de **Connected Agents** functionaliteit, waarbij de Router de specialist aanroept als een tool.23

### **5.2 Handoffs vs. Proxy Orkestratie**

Er zijn twee manieren om de samenwerking tussen agenten te structureren:

1. **Expliciete Handoffs:** De Router draagt het gesprek *volledig* over aan de specialist. De specialist communiceert direct terug naar de gebruiker. Dit wordt ondersteund door het Microsoft Agent Framework.24 Dit is efficiënt, maar kan complex zijn qua sessiebeheer.  
2. **Proxy/Tool-Use:** De Router blijft de eigenaar van het gesprek. Hij roept de specialist aan als een functie ("tool"), ontvangt het antwoord, en stuurt dit door naar de gebruiker. Dit patroon is vaak stabieler voor integratie met M365 Copilot, omdat de interface een consistente gesprekspartner verwacht.25

**Advies:** Voor dit design wordt het **Proxy/Tool-Use patroon** aanbevolen voor de interactie tussen de Router en de Specialisten. Dit centraliseert de logging en controle bij de Router, wat de eis voor "centrale controle" versterkt. De Router fungeert als de 'Manager' die taken delegeert en de resultaten controleert voordat ze naar de gebruiker gaan.

## **6\. Governance en Beveiliging**

Centrale controle staat of valt met beveiliging en governance. De architectuur leunt zwaar op de native security features van Azure.

### **6.1 Identiteit: Entra Agent ID**

Een cruciale innovatie is het gebruik van **Entra Agent ID** (momenteel in preview). In plaats van agenten te laten draaien onder generieke service principals, krijgt elke agent die door de 'Agent Factory' wordt gecreëerd een eigen, unieke identiteit.7

* **Granulaire Rechten:** De "Finance Agent" krijgt via zijn Entra Agent ID alléén leesrechten op de financiële SQL-database en specifieke SharePoint-sites. Hij heeft géén toegang tot HR-data.  
* **Auditability:** Elke actie die de agent onderneemt (bijv. een database query) wordt gelogd in Azure Monitor en Microsoft Purview onder die specifieke identiteit. Dit creëert een onweerlegbaar auditspoor: "Agent X heeft Resource Y benaderd op Tijdstip Z".26

### **6.2 Data Exfiltratie Preventie**

Om te voorkomen dat gevoelige data de organisatie verlaat, wordt strikte netwerkisolatie toegepast 27:

* **Private Endpoints:** Alle communicatie tussen de Agent Service, de modellen (Azure OpenAI), en de dataopslag (Storage, Search, SQL) verloopt over Private Links binnen een virtueel netwerk (VNet). Het verkeer komt nooit op het publieke internet.  
* **Outbound Rules:** Azure Policy en Firewall-regels blokkeren agenten om verbinding te maken met niet-goedgekeurde externe URL's. Alleen whitelisted API-endpoints zijn toegankelijk.29

### **6.3 Azure Policy voor AI**

Governance wordt afgedwongen via **Azure Policy** op de Foundry-resources.11 Policies kunnen automatisch worden toegepast om te garanderen dat:

* Geen agenten worden aangemaakt met niet-goedgekeurde modellen (bijv. GPT-4 in regio's waar data residency niet gegarandeerd is).  
* Alle agenten verplicht gebruikmaken van Private Endpoints.  
* Alle storage accounts encryptie met Customer Managed Keys (CMK) gebruiken.

## **7\. Operationele Implementatie (Stappenplan)**

Om dit design te realiseren, wordt het volgende implementatiepad aanbevolen:

1. **Fundering:** Zet de Azure AI Agent Service hub en project op met VNet-integratie en Private Endpoints.  
2. **Factory Bouwen:** Ontwikkel de 'Agent Factory' (Azure Function \+ DevOps Pipeline) die YAML-specificaties kan parsen en vertalen naar API-calls naar de Foundry SDK.  
3. **Router Agent:** Creëer de centrale Router Agent via de Factory. Instrueer deze om intenties te classificeren en door te verwijzen.  
4. **Specialisten Pilot:** Rol 2-3 gespecialiseerde agenten uit (bijv. "IT Helpdesk", "Beleid Vraagbaak") en registreer deze in de Registry.  
5. **Integratie:** Implementeer de Azure Function Proxy en configureer de Declarative Agent in M365 Copilot.  
6. **Validatie:** Test de end-to-end flow: Vraag in Teams \-\> M365 Copilot \-\> Proxy \-\> Router \-\> Specialist \-\> Antwoord.

## **Conclusie**

Dit ontwerp beantwoordt aan uw vraag door de toegankelijkheid van **Microsoft 365 Copilot** te combineren met de robuuste controle van **Microsoft Foundry**. De **Spec-Driven Agent Factory** introduceert een "Agent-as-Code" paradigma dat essentieel is voor schaalbaarheid en beheersbaarheid. Het **Centrale Router** patroon garandeert dat de organisatie grip houdt op de complexe interacties binnen het multi-agent systeem, terwijl **Entra Agent ID** en **Azure Policy** zorgen voor de noodzakelijke enterprise-grade beveiliging. Dit resulteert in een toekomstbestendige architectuur die innovatie faciliteert zonder concessies te doen aan controle en veiligheid.

### ---

**Verklarende Woordenlijst & Definities**

| Term | Definitie | Context |
| :---- | :---- | :---- |
| **Microsoft Foundry** | Het uniforme platform voor het bouwen, beheren en orkestreren van AI-applicaties en agenten (voorheen Azure AI Studio). | Het centrale beheersplatform in dit ontwerp. |
| **Azure AI Agent Service** | Een beheerde PaaS-dienst voor het hosten en uitvoeren van AI-agenten, inclusief state management en tool-integratie. | De runtime-engine voor de agenten. |
| **Entra Agent ID** | Een specifiek type identiteit binnen Microsoft Entra ID (Azure AD) ontworpen voor AI-agenten. | Biedt identiteit en toegangscontrole (RBAC) voor agenten. |
| **Declarative Agent** | Een configuratie-extensie binnen het M365 ecosysteem die Copilot voorziet van specifieke instructies en acties. | De "Voordeur" in M365 Copilot. |
| **Spec-Driven Creatie** | Het proces van het programmatisch aanmaken van agenten op basis van gestructureerde definities (YAML/JSON). | De methodologie voor beheersbare schaalvergroting. |
| **Proxy Pattern** | Een ontwerppatroon waarbij een intermediair component (zoals een Azure Function) verzoeken doorstuurt en vertaalt. | De integratiemethode tussen M365 en Azure. |

### **Bronvermeldingen**

1

#### **Geciteerd werk**

1. Azure AI Foundry: Build Autonomous AI Agents Easily \- eInfochips, geopend op december 15, 2025, [https://www.einfochips.com/blog/how-azure-ai-foundry-enables-the-development-of-autonomous-ai-agents/](https://www.einfochips.com/blog/how-azure-ai-foundry-enables-the-development-of-autonomous-ai-agents/)  
2. Building No-Code Agentic Workflows with Microsoft Foundry | by Akshay Kokane | Data Science Collective | Dec, 2025, geopend op december 15, 2025, [https://medium.com/data-science-collective/building-no-code-agentic-workflows-with-microsoft-foundry-52ad377ad644](https://medium.com/data-science-collective/building-no-code-agentic-workflows-with-microsoft-foundry-52ad377ad644)  
3. Goodbye Azure AI, Hello Microsoft Foundry: Why the Pivot to an “Agent Factory” Matters, geopend op december 15, 2025, [https://medium.com/towardsdev/goodbye-azure-ai-hello-microsoft-foundry-why-the-pivot-to-an-agent-factory-matters-f96c6994aa67](https://medium.com/towardsdev/goodbye-azure-ai-hello-microsoft-foundry-why-the-pivot-to-an-agent-factory-matters-f96c6994aa67)  
4. Microsoft Foundry, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/products/ai-foundry](https://azure.microsoft.com/en-us/products/ai-foundry)  
5. Foundry Agent Service | Microsoft Azure, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/products/ai-foundry/agent-service](https://azure.microsoft.com/en-us/products/ai-foundry/agent-service)  
6. Part 3: Client-Side Multi-Agent Orchestration on Azure App Service with Microsoft Agent Framework \- Azure documentation, geopend op december 15, 2025, [https://azure.github.io/AppService/2025/11/04/app-service-agent-framework-part-3.html](https://azure.github.io/AppService/2025/11/04/app-service-agent-framework-part-3.html)  
7. Manage Agent Identities with Microsoft Entra ID \- Microsoft Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/agent-identity?view=foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/agent-identity?view=foundry)  
8. Agent Factory: Designing the open agentic web stack | Microsoft Azure Blog, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/blog/agent-factory-designing-the-open-agentic-web-stack/](https://azure.microsoft.com/en-us/blog/agent-factory-designing-the-open-agentic-web-stack/)  
9. What Is Foundry Agent Service? \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/overview?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/overview?view=foundry-classic)  
10. Autonomous AI Agents & Multi-Agent Orchestration in Copilot \- Kellton, geopend op december 15, 2025, [https://www.kellton.com/kellton-tech-blog/microsoft-multi-agent-orchestration-strategy](https://www.kellton.com/kellton-tech-blog/microsoft-multi-agent-orchestration-strategy)  
11. Create a custom Azure Policy for Foundry \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/custom-policy-definition?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/custom-policy-definition?view=foundry-classic)  
12. Microsoft.CognitiveServices/accounts/deployments 2025-10-01-preview \- Bicep, ARM template & Terraform AzAPI reference | Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2025-10-01-preview/accounts/deployments](https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2025-10-01-preview/accounts/deployments)  
13. Create Agent \- REST API (Azure AI Foundry) | Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/create-agent/create-agent?view=rest-aifoundry-aiagents-v1](https://learn.microsoft.com/en-us/rest/api/aifoundry/aiagents/create-agent/create-agent?view=rest-aifoundry-aiagents-v1)  
14. Integrate web app with OpenAPI in Foundry Agent Service (Python) \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/app-service/tutorial-ai-integrate-azure-ai-agent-python](https://learn.microsoft.com/en-us/azure/app-service/tutorial-ai-integrate-azure-ai-agent-python)  
15. How to use Foundry Agent Service with OpenAPI Specified Tools \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/openapi-spec?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/openapi-spec?view=foundry-classic)  
16. Agents for Microsoft 365 Copilot, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/agents-overview](https://learn.microsoft.com/en-us/microsoft-365-copilot/extensibility/agents-overview)  
17. Triggering the Backend \- Integrating Azure AI Foundry with Microsoft Copilot Studio, geopend op december 15, 2025, [https://holgerimbery.blog/triggering-the-backend](https://holgerimbery.blog/triggering-the-backend)  
18. Integrate Custom Azure AI Agents with CoPilot Studio and M365 CoPilot, geopend op december 15, 2025, [https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/integrate-custom-azure-ai-agents-with-copilot-studio-and-m365-copilot/4405070](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/integrate-custom-azure-ai-agents-with-copilot-studio-and-m365-copilot/4405070)  
19. Microsoft Agent Framework Multi-Turn Conversations and Threading \- Azure AI Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/multi-turn-conversation](https://learn.microsoft.com/en-us/agent-framework/user-guide/agents/multi-turn-conversation)  
20. Get started with Microsoft Foundry SDKs and Endpoints, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/sdk-overview?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/develop/sdk-overview?view=foundry-classic)  
21. Copilot Handoffs for Bots \- Teams \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/bot-copilot-handoff](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/bot-copilot-handoff)  
22. Deep link to a Teams chat \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/deep-link-teams](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/build-and-test/deep-link-teams)  
23. How to use connected agents \- Microsoft Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/connected-agents?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/connected-agents?view=foundry-classic)  
24. Microsoft Agent Framework Workflows Orchestrations \- Handoff, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/orchestrations/handoff](https://learn.microsoft.com/en-us/agent-framework/user-guide/workflows/orchestrations/handoff)  
25. Agent system design patterns \- Azure Databricks \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/databricks/generative-ai/guide/agent-system-design-patterns](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/guide/agent-system-design-patterns)  
26. Agent Factory: Creating a blueprint for safe and secure AI agents | Microsoft Azure Blog, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/blog/agent-factory-creating-a-blueprint-for-safe-and-secure-ai-agents/](https://azure.microsoft.com/en-us/blog/agent-factory-creating-a-blueprint-for-safe-and-secure-ai-agents/)  
27. Configure Virtual Networks for Foundry Tools \- Azure \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks](https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-virtual-networks)  
28. Data exfiltration protection access controls \- Microsoft Service Assurance, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/compliance/assurance/assurance-data-exfiltration-access-controls](https://learn.microsoft.com/en-us/compliance/assurance/assurance-data-exfiltration-access-controls)  
29. Configure data loss prevention for Azure AI services, geopend op december 15, 2025, [https://docs.azure.cn/en-us/ai-services/cognitive-services-data-loss-prevention](https://docs.azure.cn/en-us/ai-services/cognitive-services-data-loss-prevention)  
30. Microsoft Foundry: Scale innovation on a modular, interoperable, and secure agent stack, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/blog/microsoft-foundry-scale-innovation-on-a-modular-interoperable-and-secure-agent-stack/](https://azure.microsoft.com/en-us/blog/microsoft-foundry-scale-innovation-on-a-modular-interoperable-and-secure-agent-stack/)  
31. Creating Multi-Agent Workflows with Microsoft Agent Framework, geopend op december 15, 2025, [https://medium.com/data-science-collective/creating-multi-agent-workflows-with-microsoft-agent-framework-8c68df1ec0ea](https://medium.com/data-science-collective/creating-multi-agent-workflows-with-microsoft-agent-framework-8c68df1ec0ea)  
32. AI Agent Orchestration Patterns \- Azure Architecture Center \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)  
33. Introducing Microsoft Agent Framework | Microsoft Azure Blog, geopend op december 15, 2025, [https://azure.microsoft.com/en-us/blog/introducing-microsoft-agent-framework/](https://azure.microsoft.com/en-us/blog/introducing-microsoft-agent-framework/)  
34. Quickstart \- Create a new Foundry Agent Service project \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/quickstart?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/quickstart?view=foundry-classic)  
35. Microsoft just announced that Azure AI Foundry has been renamed to Microsoft Foundry. \- Reddit, geopend op december 15, 2025, [https://www.reddit.com/r/AZURE/comments/1p1xxh4/microsoft\_just\_announced\_that\_azure\_ai\_foundry/](https://www.reddit.com/r/AZURE/comments/1p1xxh4/microsoft_just_announced_that_azure_ai_foundry/)  
36. What is Microsoft Foundry? \- Microsoft Foundry \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/what-is-azure-ai-foundry?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/what-is-azure-ai-foundry?view=foundry-classic)  
37. Deploy in production your existing Foundry agent to M365 in minutes, geopend op december 15, 2025, [https://www.youtube.com/watch?v=nRuY\_YI-Efk](https://www.youtube.com/watch?v=nRuY_YI-Efk)  
38. Publish agents to Microsoft 365 Copilot and Microsoft Teams, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/publish-copilot?view=foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/publish-copilot?view=foundry)  
39. Navigating Microsoft's Copilot Studio and Azure AI Foundry, geopend op december 15, 2025, [https://techcommunity.microsoft.com/blog/microsoftmissioncriticalblog/navigating-microsofts-copilot-studio-and-azure-ai-foundry/4472233](https://techcommunity.microsoft.com/blog/microsoftmissioncriticalblog/navigating-microsofts-copilot-studio-and-azure-ai-foundry/4472233)  
40. Deploy your agent to Azure manually | Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/deploy-azure-bot-service-manually](https://learn.microsoft.com/en-us/microsoft-365/agents-sdk/deploy-azure-bot-service-manually)  
41. Publishing Agents from Microsoft Foundry to Microsoft 365 Copilot & Teams, geopend op december 15, 2025, [https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/publishing-agents-from-microsoft-foundry-to-microsoft-365-copilot--teams/4471184](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/publishing-agents-from-microsoft-foundry-to-microsoft-365-copilot--teams/4471184)  
42. Create Your First AI Agent with Azure AI Service \- Rajeev Singh | Coder, Blogger, YouTuber, geopend op december 15, 2025, [https://singhrajeev.com/2025/01/20/creating-your-first-ai-agent-with-azure-ai-agent-service/](https://singhrajeev.com/2025/01/20/creating-your-first-ai-agent-with-azure-ai-agent-service/)  
43. Exploring the Semantic Kernel Azure AI Agent Agent \- Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-types/azure-ai-agent](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-types/azure-ai-agent)  
44. Azure AI Search tool for agents \- Microsoft Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/ai-search?view=foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/ai-search?view=foundry)  
45. How to use an existing AI Search index with the Azure AI Search tool \- Microsoft Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/azure-ai-search?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/azure-ai-search?view=foundry-classic)  
46. Role-based access control for Microsoft Foundry, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/rbac-azure-ai-foundry?view=foundry-classic](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/rbac-azure-ai-foundry?view=foundry-classic)  
47. Process to build agents process across your organization with Microsoft Foundry and Copilot Studio \- Cloud Adoption Framework, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/build-secure-process](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/build-secure-process)  
48. Building for Agentic AI \- Agent SDKs & Design Patterns | by Ryan LIN \- Medium, geopend op december 15, 2025, [https://medium.com/dsaid-govtech/building-for-agentic-ai-agent-sdks-design-patterns-ef6e6bd4a029](https://medium.com/dsaid-govtech/building-for-agentic-ai-agent-sdks-design-patterns-ef6e6bd4a029)  
49. Choosing Between Building a Single-Agent System or Multi-Agent System \- Cloud Adoption Framework | Microsoft Learn, geopend op december 15, 2025, [https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/single-agent-multiple-agents](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/single-agent-multiple-agents)