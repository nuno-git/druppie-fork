---
name: architecture-principles
description: >
  Water Authority architecture principles based on NORA, WILMA, and joint
  Water Authority governance. Provides the full set of 22 principles with
  rationale, implications, and practical examples for architectural
  assessment of functional designs.
---

# Architecture Principles

## Introduction

Architecture principles guide the development and design of information
services. These principles are valuable both for each Water Authority
individually and for joint development across collaborating authorities.
By adhering to the same principles, the Water Authorities can better
align with one another.

Architecture principles do not stand alone. They are grounded in various
drivers for change such as strategy, bottlenecks, and external
developments. The following change drivers are important to analyse and
form the basis for the architecture principles:

- **Objectives** — goals that stakeholders aim to achieve
- **Values** — fundamental beliefs held by people in the organisation
- **Bottlenecks** — problems that prevent the organisation from reaching
  its objectives
- **Risks** — problems that may arise in the future
- **Opportunities** — opportunities and their potential reward for the
  organisation
- **Constraints** — limitations imposed by others inside and outside the
  organisation

### Sources

The principles draw from:

- Established principles of Hoogheemraadschap van Delfland (HHD)
- Established principles of Hoogheemraadschap van Rijnland (HHR)
- NORA — Nederlandse Overheid Referentie Architectuur (Dutch Government
  Reference Architecture)
- WILMA — Waterschaps Informatie Architectuur + Logische Modellen (Water
  Authority Information Architecture + Logical Models)
- Joint principles of the collaborating Brabant Water Authorities

## How to Apply These Principles

When assessing a functional design, evaluate each principle that is
relevant to the proposed solution. Not every principle applies to every
design — focus on the ones that are material to the context.

For each relevant principle, determine:

1. **Compliance** — Does the design align with the principle?
2. **Implications** — Are the consequences of the principle addressed?
3. **Conflicts** — Does the design violate the principle? If so, is
   there a justified reason?
4. **Gaps** — Are there aspects the functional design does not address
   that the principle requires?

Use the architecture layer and domain classification to ensure coverage
across all NORA layers.

## Principle Format

Each principle is documented with the following attributes:

| Attribute | Description |
|-----------|-------------|
| **ID** | Sequence number |
| **Principle** | Short, strong statement |
| **Explanation** | Expanded description of what the principle entails |
| **Motivation** | Why the principle is important; references objectives or requirements |
| **Implications** | Specific consequences for the organisation, so people understand what it means for their work |
| **Examples** | Practical examples for illustration |
| **Source** | Origin of the principle |
| **Architecture Layer** | Layer in the NORA model this principle relates to |
| **Architecture Domain** | Domain in the NORA model this principle relates to |

## Architecture Layers and Domains — The NORA Nine-Square Model

The NORA nine-square model is a framework for architecture principles.
It helps place elements within an aspect of architecture and ensures all
aspects are covered. The tenth and eleventh components — **management**
and **security & privacy** — span across all nine other components.

The vertical axis represents the architecture layers; within those, the
architecture domains can be found.

| Layer | Domains |
|-------|---------|
| **Business Architecture** | Organisation, Services & Products, Processes |
| **Information Architecture** | Employees & Applications, Messages & Data, Information Exchange |
| **Technical Architecture** | Technical Components |
| **Management Architecture** | *(cross-cutting)* |
| **Security Architecture** | *(cross-cutting)* |

## Foundational Assumptions

The following foundational assumptions underpin the principles.

### Collaboration

The Water Authorities collaborate intensively — internally, with each
other, and with chain partners — wherever this leads to greater
effectiveness or efficiency.

Collaboration entails intensive knowledge and information sharing:

- Relevant knowledge and data are shared with chain partners.
- Data quality must be high.
- Standards are required for data exchange.
- Standardisation of processes makes collaboration easier.

Guiding assumptions for collaboration:

- Collaborate where there is a business case in terms of cost, quality,
  and/or vulnerability (the 3 Ks).
- Collaborate on the basis of equality, mutual respect, and recognition
  of individual identity.
- Collaboration must be organised and safeguarded at strategic, tactical,
  and operational levels.
- Collaboration must not have a market-distorting effect.

### Effectiveness

The Water Authorities carry out their tasks in an effective,
cost-efficient manner, at socially acceptable costs.

Effectiveness has the following consequences for architecture:

- Effectiveness goes beyond operations within a single Water Authority —
  it also concerns the effectiveness of the entire water sector.
- Joint knowledge acquisition and processing.
- Standardisation.
- Transparency is needed to measure effectiveness and cost efficiency.

### Sustainability

The Water Authorities choose sustainable solutions wherever possible.
In new developments, sustainability aspects are incorporated from the
outset and the entire lifecycle is considered from the beginning.

### Innovation

The Water Authorities invest in innovation to continue performing their
core tasks effectively. Knowledge sharing is important, and there must
be room for adopting new technologies.

### Customer Orientation

The Water Authorities design their processes in a customer-friendly
manner and equip their employees to serve customers optimally.

- Customers can communicate with the Water Authority through the channel
  of their choice (internet, telephone, letter, counter); the result is
  equivalent.
- Information is usable, findable, and standardised.
- Processes are designed to be customer-friendly and employees are willing
  and able to serve the customer optimally.

### Transparency

The Water Authorities are traceable in delivering products and services
and render accountability.

- Public documents are made available via the internet.
- High availability and integrity of data.
- Policy regarding confidentiality of data.

---

## Principles

### Principle 1 — Central Governance on ICT and Information Services

| Attribute | Detail |
|-----------|--------|
| **ID** | 1 |
| **Principle** | There is central governance on ICT and information services |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Organisation |
| **Source** | WILMA, HHD and HHR principles |

**Explanation**

There is central governance on ICT and information services according to
an established governance model. This governance covers all types of
information services and automation and applies per organisational unit.

**Motivation**

- Central governance is needed to realise an efficiently designed,
  integrated information service landscape.
- It enables integrated management of all types of information services
  and automation.
- It enables better and more readily available management information.

**Implications**

- An integrated governance model is designed and implemented.
- The governance model must encompass the management of all types of
  information services and automation, including mutual alignment and
  delineation.
- When drafting policy (information policy, security policy), all types
  of information services, automation, and management are involved.
- Architecture steers (ICT) project portfolio management.
- Working under architecture applies to all types of automation and
  applications.
- The same management methodology is applied to all types of automation.
- An overview of all ICT-related costs and person-hours in the
  organisation is required.

**Examples**

- Different types of automation include: process automation, office
  automation, GIS, and administrative automation.
- Data from technical process automation and administrative automation
  can be delivered integrally at management information level. An example
  is the Z-Info application for wastewater treatment, which is populated
  with (aggregated) data from process automation.
- A new application can only be introduced after an approval process via
  the governance model.

---

### Principle 2 — Sourcing via an Established Assessment Framework

| Attribute | Detail |
|-----------|--------|
| **ID** | 2 |
| **Principle** | Sourcing for information services is determined using an established assessment framework |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Organisation |
| **Source** | — |

**Explanation**

What do we do ourselves, what do we outsource, and what do we do
together? That is what sourcing is about. Depending on the products and
services of an organisation, the answer may differ. The challenge is to
arrive at an optimal "sourcing mix" that suits the organisation, guided
by a sourcing strategy — an assessment framework to determine the
optimal sourcing mix.

Information services are intertwined with all primary and supporting
processes. This makes it impossible to make a single sourcing choice for
information services as a whole. A sourcing form must be chosen per
process or service.

**Motivation**

A sourcing strategy provides a structured trade-off of cost, quality,
vulnerability, and effectiveness when deciding whether to keep tasks
in-house or outsource them.

**Implications**

- Processes and services of information provision must be well described
  to enable sourcing decisions.
- Structural temporary staffing should be reconsidered: choose a
  different sourcing form.
- It may have personnel consequences when processes currently performed
  in-house are better executed by a shared service centre or the market.
- A cloud policy must be established in conjunction with the sourcing
  policy.

**Examples**

- Core or directing task: Determine the vision for information services
  with own staff.
- Temporary capacity: Hiring a project manager for a Windows migration.
- Temporary expertise: Having infrastructure security regularly tested by
  a specialised market party.

---

### Principle 3 — Every Primary Data Element, Process, and Application Has an Owner

| Attribute | Detail |
|-----------|--------|
| **ID** | 3 |
| **Principle** | Every primary data element, process, and application has an owner |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Organisation |
| **Source** | — |

**Explanation**

Ownership is assigned for primary data, processes, and applications. It
is determined what this entails and which responsibilities and
authorities are associated with it.

It is not feasible to assign ownership for every single data element, but
it is at a higher (primary) level. For example: "postal code" is a
secondary data element, while "customer" is a primary data element.

**Motivation**

- Ownership must be assigned in order to:
  - Exercise governance and make decisions
  - Make agreements
  - Hold someone accountable for quality
- Clear ownership makes it possible to align information system
  management accordingly. By doing this uniformly, we can:
  - Save (management) costs
  - Increase quality
  - Reduce vulnerability

**Implications**

- Responsibilities must be described and unambiguously assigned within
  the organisation.
- Every owner must know their responsibilities and be enabled to assume
  them.
- The owner ensures that requirements are established.
- Every owner must take into account the requirements of all stakeholder
  processes.
- Management is aligned with the established requirements.

**Examples**

- An application owner coordinates changes to that application with all
  stakeholder processes that also use the same application.
- An owner of a primary data element is responsible for ensuring that
  data element is available to every process that needs it.
- A process owner is responsible for ensuring that the products the
  process delivers meet the requirements of consuming processes.

---

### Principle 4 — Digital Channel First for Service Delivery

| Attribute | Detail |
|-----------|--------|
| **ID** | 4 |
| **Principle** | We use the digital channel as much as possible for service delivery |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Services and Products |
| **Source** | WILMA PR.DP.01, NORA AP09 |

**Explanation**

When delivering services to citizens and businesses, the digital channel
(internet) is used as much as possible. Other channels must remain
available.

**Motivation**

- Required for e-service delivery to citizens; e-government is a
  national government mandate.
- Citizens and businesses increasingly demand digital service delivery.
- Greater accessibility for consumers; enables 24/7 service delivery.
- Significantly increases the range of service delivery possibilities.
- Gives customers digital insight into the status of product or service
  requests.
- Cost savings.
- Keeps the burden on citizens as low as possible.

**Implications**

- The organisation is capable of handling communication with consumers
  via the internet and other chosen channels.
- There must be a good connection with the back office.
- Use of the digital channel by citizens and businesses must be
  encouraged.
- Other channels must remain available.
- Information must be digitally available, also outside office hours.
- Information that is not digitally available must be digitised.
- Adequate security is required.
- Data and information must be of sufficient and known quality.
- Data exchange according to applicable standards.
- Data management must be in order.

**Examples**

- Website with up-to-date information.
- E-counter on the website, for example for applying for permits.
- Ability to report complaints and notifications via the website.

---

### Principle 5 — ICT Facilities Aligned with Business Availability Requirements

| Attribute | Detail |
|-----------|--------|
| **ID** | 5 |
| **Principle** | The design and support of ICT facilities is in accordance with business availability requirements |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Services and Products |
| **Source** | DRS |

**Explanation**

Where necessary, core tasks must be executable on a continuous basis.
Part of the information services must therefore be available and
supported 24/7.

**Motivation**

Statutory duty of the Water Authority.

**Implications**

- 24/7 availability must be arranged for all processes and systems that
  are directly or indirectly related to core tasks and/or crisis
  management.
- For those processes, infrastructure, applications, and support must
  also be available 24/7.
- Personnel performing the process must also be continuously available.
- For other processes and systems, lower availability may be offered.
  Agreements are made in advance based on process needs.
- Include in contracts with suppliers of the relevant information
  services.

**Examples**

- Wastewater treatment is a continuous process where infrastructure,
  applications, and management must be available 24/7. This applies both
  to internal personnel and suppliers.
- Calamity response must also be supportable outside office hours.

---

### Principle 6 — We Work Under Architecture

| Attribute | Detail |
|-----------|--------|
| **ID** | 6 |
| **Principle** | We work under architecture |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Processes |
| **Source** | — |

**Explanation**

Working under architecture is embedded in the organisations.

**Motivation**

Architecture is the steering instrument to shape the substantive
coordination of developments in information services. Architecture
provides direction during change.

Added value of architecture:

- Providing insight into the coherence between different aspects of
  information services in an organisation.
- Steering towards integration and standardisation.
- Reducing complexity.
- Creating flexibility so information services can keep pace with
  changing circumstances.
- Managing risks and costs.
- Being in control.

**Implications**

- Responsibilities and authorities are clearly and unambiguously
  assigned.
- There is sufficient commitment and motivation from management. Business
  and ICT management are especially important in creating the right
  conditions.
- Compliance with architecture is actively enforced (strategic dialogue).
- Every (ICT) project is assessed against architecture frameworks.
- The architecture role is filled with sufficient knowledge and skills.
- There is a connection to the change portfolio (coordinated through
  project portfolio management).
- There is a consultation structure for alignment between architects.
- Priorities are set for further developing the practice of working under
  architecture.

**Examples**

- Projects that meet certain architecture criteria are executed under
  architecture. A project architect is appointed.

---

### Principle 7 — Process Optimisation Through Digitisation and Standardisation

| Attribute | Detail |
|-----------|--------|
| **ID** | 7 |
| **Principle** | Process optimisation through digitisation and standardisation |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Processes |
| **Source** | WILMA PR.PR.01 |

**Explanation**

Information flows are made digital as much as possible.

**Motivation**

- Digitisation increases:
  - The timeliness of information.
  - The traceability of information.
  - The availability of information.
- Standardisation of processes makes it easier to:
  - Collaborate on developing joint information services.
  - Share knowledge and experience, leading to greater effectiveness.
  - Develop chain processes with partners.

**Implications**

- Data must be recorded correctly at the source in one go.
- Data and information that do not arrive digitally from outside must be
  digitised.
- Data exchange according to applicable standards.
- Data management must be established to safeguard the quality of data
  and information.
- Metadata must be added during the work process.
- This also affects operations outside the I&A domain.

**Examples**

- Self-service HRM.
- Permits can be applied for digitally, e.g. via the website.
- Documents that do not arrive digitally are scanned.

---

### Principle 8 — Case-Oriented Working in Service Delivery

| Attribute | Detail |
|-----------|--------|
| **ID** | 8 |
| **Principle** | Case-oriented working is applied in service delivery |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Processes |
| **Source** | — |

**Explanation**

Case-oriented working is one of the ways to manage a process (alongside
process-oriented and project-oriented working).

A case is a coherent body of work with a defined trigger and a defined
result, whose quality and lead time must be monitored. Case-oriented
working enables better service delivery through:

- Greater transparency.
- Integrated monitoring of service handling.
- Integrated management information.

Case-oriented working is also applicable to internal service delivery.

**Motivation**

Government policy is aimed at enabling businesses and citizens to handle
their dealings with the government digitally. This requires the
government to make all relevant information digitally available,
including status information about case handling. Case-oriented working
helps government organisations implement the national strategy for a
digital government — strengthening the information position of citizens
and businesses.

For internal service delivery, similar considerations apply: handling
should be predictable and transparent for the requester.

**Implications**

- Clearly define what is meant by case-oriented working and in which
  situations it is applied. Not everything is a case.
- Make agreements about the process and information services, including:
  - Defining the result of a case.
  - Setting quality monitoring norms per case type.
- Standardise (case types, working methods).
- For every request of certain complexity, a case is defined.
- The employee receives an integrated "case view" (case dossier).
- The customer is given access to relevant information.

**Examples**

- A citizen who has submitted a request can see what personal information
  is used to assess their request.
- A citizen can check the status of their request at any time.
- Processes suited for case-oriented working include: permit granting and
  enforcement, incident reports, and objections to decisions.
- Simple customer questions that can be answered immediately are not
  cases.

---

### Principle 9 — Harmonise Processes and Applications for Collaboration

| Attribute | Detail |
|-----------|--------|
| **ID** | 9 |
| **Principle** | From a collaboration perspective, we harmonise processes and applications |
| **Architecture Layer** | Business Architecture |
| **Architecture Domain** | Processes |
| **Source** | — |

**Explanation**

By first aligning processes within and between collaboration partners
and only then incorporating those processes into a joint system, the
maximum benefit is derived from joint I&A projects.

**Motivation**

Collaboration, effectiveness. Only through harmonisation can
collaboration partners configure the system in the same way, (jointly)
manage it, and enter into contracts.

**Implications**

- See foundational assumptions on collaboration: only works if those
  apply.
- Willingness to adapt one's own processes where possible.
- This cannot be enforced through technology; it requires a different
  approach.

**Examples**

- Z-Info: Every wastewater treatment manager must deliver the same
  external reports. Using Z-Info, those reports are automated and
  delivered uniformly. The working processes of treatment managers are
  adjusted where necessary to meet this standard.
- During the implementation of the case management system, working
  methods are aligned where possible, using a shared case type catalogue.

---

### Principle 10 — Location- and Time-Independent Working

| Attribute | Detail |
|-----------|--------|
| **ID** | 10 |
| **Principle** | Employees can perform their work independently of location and time |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Employees and Applications |
| **Source** | WILMA PR.OR.04, WILMA PR.BG.02 |

**Explanation**

To efficiently and effectively support flexible working and field work,
applications must be usable on different platforms and independently of
location, also outside regular working hours.

**Motivation**

- Good employer practice — part of the new way of working.
- Supports collaboration (internal and external).
- To optimally support employees in their work, including in the field
  (mobile working) and at home.
- For flexibility in work execution.

**Implications**

- Digital working.
- Information is accessible at any place, any time, with any device.
- Platform-independent applications.
- Functionality must be made accessible in different ways.
- New applications must connect to existing interfaces for mobile devices
  where needed.
- Places significant demands on data management and infrastructure.
- Security must be well arranged.
- Differentiation in accessibility of data and information must be
  possible.

**Examples**

- From home, also outside regular working hours, secure access to all
  relevant applications can be obtained via the internet.
- Applications can be used on various operating systems and devices where
  needed.
- Installations must be operable remotely.

---

### Principle 11 — Standard Before Custom, Joint Before Individual

| Attribute | Detail |
|-----------|--------|
| **ID** | 11 |
| **Principle** | When renewing applications, standard takes precedence over custom and joint over individual realisation |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Employees and Applications |
| **Source** | — |

**Explanation**

When renewing information services, functionality is realised in the
following order of preference:

1. Reuse own provisions
2. Reuse provisions of collaboration partner
3. Jointly purchase standard provisions
4. Individually purchase standard provisions
5. Jointly realise custom solutions
6. Individually realise custom solutions

**Motivation**

Effectiveness:

- Custom solutions entail higher costs and require more capacity for
  maintenance and management.
- By sharing systems and management, costs and capacity can be saved.

**Implications**

- Process harmonisation may be required so that joint procurement yields
  benefits.
- Process adaptation takes precedence over system adaptation, to
  minimise the need for custom solutions.

**Examples**

- When purchasing a standard application, the working process is adapted
  on certain points so the application does not need modification.
- When an application needs replacement, the application in use at the
  collaboration partner is first assessed for suitability.

---

### Principle 12 — One Application per Type of Functionality

| Attribute | Detail |
|-----------|--------|
| **ID** | 12 |
| **Principle** | One application is deployed per type of functionality |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Employees and Applications |
| **Source** | DRS, WILMA PR.MA.01 |

**Explanation**

We steer towards ensuring that the same type of functionality is not
used in multiple applications.

**Motivation**

- Using only one application per functionality reduces the number of
  applications needed, which can save costs.
- Makes changes easier to implement.
- Makes renewal of parts of the information landscape easier.
- Supports uniform, standardised processes.

**Implications**

- When renewing information services, the new functionality must be
  thoroughly analysed to determine overlap with existing applications.
- For each application, it must be determined which functionalities it
  is used for.
- Increasingly, applications contain more functionality than needed.
  Therefore, for all applications, it must be documented which
  functionalities are used and which are not.

**Examples**

- For organisation-wide (cross-business-function) reporting, one
  reporting system is used.
- For time registration, one system is used.
- Different applications (e.g. Oracle eBS, Primavera, MS Projects) all
  contain project planning functionality. To support a uniform,
  standardised working method, one application is chosen for project
  planning; the planning functionality of the others is not used.

---

### Principle 13 — A Data Element Has One Source

| Attribute | Detail |
|-----------|--------|
| **ID** | 13 |
| **Principle** | A data element has one source |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Messages and Data |
| **Source** | WILMA PR.BG.01, GEMMA P2.4 |

**Explanation**

Data is managed under one responsibility, at the source, and can be used
multiple times. This applies both to external data (base registrations)
and internal data.

**Motivation**

- Managing data in only one place makes changes easier to implement.
- Uniform use of data facilitates data exchange.
- Quality is easier to guarantee.

**Implications**

- National base registration data is received and accessed via one
  source system.
- The source system makes data available for internal
  processes/provisions.
- A distinction is made between process data, core data, and base data.
- Process data used only within one business function does not need to
  meet all requirements for core and base data.
- Data is traceable to its source.
- Stored data is always accompanied by sufficient supporting information
  for management and access.
- Internal agreements are made on the obligation to report back
  erroneous data.
- When own copies of data are stored, these must be kept up to date.
- Source ownership is assigned.

**Examples**

- Personnel data is managed in the HR system but used in many other
  places.
- BAG (Base Registration for Addresses and Buildings) data is accessed
  once and reused. When an error is found, it is not corrected in Water
  Authority systems but reported back to the administrator.

---

### Principle 14 — We Use Standards

| Attribute | Detail |
|-----------|--------|
| **ID** | 14 |
| **Principle** | We use standards |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Messages and Data |
| **Source** | NORA AP08, WILMA MA.02, WILMA PR.IU.02 |

**Explanation**

We use nationally or sector-established standards.

**Motivation**

- Government directive (open standards). Striving for open standards is a
  prerequisite for making government information about services and
  products accessible and keeping it accessible.
- Prevents product dependency (vendor lock-in).
- Collaboration and data exchange with customers and chain partners are
  becoming the rule rather than the exception. This presupposes the
  ability to interpret each other's data.

**Implications**

- Requirements must be set for purchased packages regarding integration
  with other applications.
- We apply the data standards common in the water sector (Aquo, DAMO,
  etc.).
- "Apply or explain" principle.

**Examples**

- The Aquo standard: This data standard enables uniform data exchange
  between parties involved in water management and contributes to quality
  improvement. Simple and unambiguous information sharing saves time and
  money.
- IPv6: An internet standard on the open standards list specifying how
  internet addresses must be structured.

---

### Principle 15 — All Information Is Public Unless Determined Otherwise

| Attribute | Detail |
|-----------|--------|
| **ID** | 15 |
| **Principle** | All information is public unless determined otherwise |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Information Exchange |
| **Source** | WILMA PR.BG.03, NORA BP01, NORA BP03 |

**Explanation**

Open data is freely available information. Open data aims to maximally
facilitate reuse. The open government principle focuses on actively
making government information available for inspection, reuse, and
correction by citizens, providing insight into how the government works,
and enabling citizen participation in government processes.

Key components:

1. Proactively making public (non-privacy-sensitive) government
   information available for inspection and reuse. The principle is
   "actively make available, unless".
2. Giving citizens and businesses access to their own personal and
   business-related information.
3. Citizen participation in executive and policy-forming processes.

**Motivation**

Openness of governance, collaboration, customer orientation, thinking
from the outside in.

**Implications**

- All information is public unless legally determined otherwise. The
  Freedom of Information Act (Wob/Woo) and personal data protection
  legislation serve as frameworks.
- All relevant legislation must be mapped.
- Guidelines on confidentiality are needed.
- The quality level of data and information must be documented.
- The agreed quality of data and information must be guaranteed.
- Effort must be made to prevent data and information from being
  misinterpreted and misused.

**Examples**

- Publishing measured water levels on the website.
- Making permit application status information available on a personal
  internet page.
- Soliciting citizen input for developing a new Water Management Plan.
- Combining opened data and publishing via mobile or web applications so
  citizens can use it — for example, Buienradar using KNMI data.
- Stimulating citizens to report problems in their neighbourhood via the
  internet.

---

### Principle 16 — Processes Are Supported by Services

| Attribute | Detail |
|-----------|--------|
| **ID** | 16 |
| **Principle** | Processes are supported by services |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Information Exchange |
| **Source** | WILMA |

**Explanation**

For automated exchange of information between applications, services are
used. This applies both within the internal application landscape and
for exchange with external parties. Services can be composed of multiple
functionalities from different applications.

**Motivation**

- Flexibility — changes are easier to implement.
- Reuse — can save costs.
- Efficiency — easier to renew parts of the information landscape.

**Implications**

- New applications are expected to be service-oriented.
- Services are designed to be reusable and process-independent.
- Functionality is supported by only one application. For standard
  packages, it is explicitly established which functionality is used and
  which is not.
- Careful delineation of functionalities is needed.
- May initially lead to higher costs.
- Services have exactly one provider and one or more consumers. There is
  no a priori hierarchical relationship between these roles.
- Service orientation places consumer-driven steering above
  provider-driven steering where possible, but this is not absolute.
- Services separate responsibility and execution. The provider remains
  responsible for delivery; execution can be (partially) outsourced.
- Services separate the outside from the inside. The consumer knows
  exactly what they get but does not concern themselves with how the
  service is realised.
- Services are maximally predictable for the consumer.

**Examples**

- Applications that work with documents (e.g. case system, collaboration
  portal, HR system) are expected to store documents in the DMS using
  services.
- An incident service retrieves location data from GIS and handling data
  from the case system.

---

### Principle 17 — We Request Data Only Once

| Attribute | Detail |
|-----------|--------|
| **ID** | 17 |
| **Principle** | We request data only once |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Information Exchange |
| **Source** | NORA AP12, GEMMA P2.1 |

**Explanation**

Consumers are not asked for information that is already known.

**Motivation**

- Reusing already-known information limits the costs of data
  registration and management.
- Having to provide the same information multiple times is one of the
  biggest frustrations for citizens and businesses. Unnecessary data
  requests must therefore be prevented.

**Implications**

- Applies to both internal and external data.
- There is an overview of all data necessary for delivering the internal
  or external service.
- For each data element, it is established whether it is already
  registered with the government or not.
- If authentic data is needed, it is obtained from base registrations.
- If non-authentic data is needed, it is first checked whether it is
  already available in-house or at other government organisations.

**Examples**

- Enforcing a permit may use the BRP (Personal Records Database).
- Sending an invitation for a New Year's reception may not use the BRP.

---

### Principle 18 — Standardisation on Interfaces

| Attribute | Detail |
|-----------|--------|
| **ID** | 18 |
| **Principle** | Interfaces are standardised |
| **Architecture Layer** | Technical Architecture |
| **Architecture Domain** | Technical Components |
| **Source** | — |

**Explanation**

Data exchange between internal and external applications must take place
via standardised interfaces. We limit the number of different types of
interfaces.

**Motivation**

- Simplifies management.
- Increases security through a limited set of connection types.
- Prevents vendor lock-in.
- Increases flexibility to modify connections.

**Implications**

- Define interfaces as broadly as possible so that custom work is no
  longer necessary ("smooth" interfaces).

**Examples**

- StUF: A universal messaging standard for electronically exchanging
  data between applications. The domain encompasses information chains
  between government organisations and municipality-wide information
  chains and functionality.
- Web service connections between applications.
- Standard interfaces include: HTTP(S) ports 80 and 443, VDI, ICA.
- Offering a virtual desktop.

---

### Principle 19 — Information Services Are Managed

| Attribute | Detail |
|-----------|--------|
| **ID** | 19 |
| **Principle** | Information services are managed |
| **Architecture Layer** | Management Architecture |
| **Architecture Domain** | *(cross-cutting)* |
| **Source** | — |

**Explanation**

All information services are managed, including remotely. This applies
to business information, infrastructure, applications,
objects/installations, and mobile devices.

**Motivation**

- Standardising the configuration of infrastructure, applications,
  objects, and devices.
- Standardising management activities.
- Increasing flexibility and speed of management operations.
- Minimising travel between locations for both administrators and
  employees.

**Implications**

- Provisions must be made so that infrastructure, applications, objects,
  and devices can be centrally managed.
- Places requirements on applications (scripting, virtualisation).
- Places requirements on hardware (ILO).
- Places requirements on management tooling: support remote management
  for all types of managed objects, including implementation of Mobile
  Device Management.
- In collaboration arrangements for management, collaboration partners
  must also be able to manage centrally.

**Examples**

- If business information is used on unmanaged equipment (e.g.
  employees' own devices), this occurs within a shell that is remotely
  managed through Mobile Device Management.
- Implementation of software that allows administrators to view sessions
  on all device types.
- Identity Management takes place centrally and uses open standards such
  as SAML and SCIM.

---

### Principle 20 — We Meet Information Security and Business Continuity Standards

| Attribute | Detail |
|-----------|--------|
| **ID** | 20 |
| **Principle** | We meet the standards for information security and business continuity |
| **Architecture Layer** | Security Architecture |
| **Architecture Domain** | *(cross-cutting)* |
| **Source** | BIWA (Baseline Information Security for Water Authorities) |

**Explanation**

- The protection of information in work processes meets at minimum the
  applicable baseline for information security and business continuity,
  as established in BIWA.
- Measures for information security and business continuity are
  proportional and based on risk analysis and classification of
  availability, integrity, and confidentiality.
- Access to information services is always and everywhere secured
  according to the applicable standard.
- Through risk analysis and classification of business functions,
  supporting resources, and information, the required protection level is
  indicated in terms of availability, integrity, and confidentiality.
  This protection level may exceed BIWA when additional measures are
  needed.
- Protection requirements apply to all premises, related buildings,
  managed objects such as engineering structures, and equipment used by
  employees.
- Security requirements for information systems relate to the
  information processed within them. Even when systems do not physically
  run within the Water Authority or tasks are outsourced, these
  requirements apply.

**Motivation**

The ever-growing dependency on information systems and information flows
leads to tangible risks for the continuity of Water Authority service
delivery. Reliable, available, and correct information is crucial for
the primary processes and operations of all Water Authorities.

**Implications**

- There is a board-approved information security policy based on and
  compliant with BIWA.
- There are up-to-date information security and business continuity
  plans.
- All responsibilities for information security are clearly defined and
  assigned.
- Line management is responsible for the quality of operations and
  thereby for the security of information systems.
- The system owner is responsible for security classification at process,
  system, and data level, and for implementing protection measures.
- Both during design/implementation and during use, tests are conducted
  on the effectiveness of security measures.
- Employees, hired staff, and external users understand their
  responsibilities regarding information security and act accordingly.
- The Security Officer is informed about security classification,
  measures taken, and effectiveness.

**Examples**

- Passwords for accessing applications and systems are personal and are
  not disclosed to others.
- Regular backups are made and recovery is tested.

---

### Principle 21 — Applications Meet Requirements for Sustainable Information Accessibility

| Attribute | Detail |
|-----------|--------|
| **ID** | 21 |
| **Principle** | The design of applications meets requirements for sustainable accessibility of information |
| **Architecture Layer** | Information Architecture |
| **Architecture Domain** | Employees and Applications |
| **Source** | — |

**Explanation**

To realise and safeguard sustainable accessibility of information, the
guidelines for a well-ordered and accessible state of information (data
and documents) are followed when procuring and implementing applications.

Note: There is a close relationship with principles 7, 14, 15, and 20.

**Motivation**

Government bodies are obligated to comply with the Archives Act.

Information is the societal capital of the organisation. Having reliable,
available, findable, and usable information is important for good
operations, democratic oversight, and cultural-historical research.
Applications must therefore be configured to create the right
preconditions.

**Implications**

The implications are extensively described in the RODIN guideline. Key
points:

- Information objects are linked to a classification structure that can
  be adapted without disrupting existing structures and links.
- Each individual information object has a unique identifier (GUID).
- Information objects contain the metadata required for management,
  derived from an established metadata schema.
- The reliability of information objects is demonstrable and safeguarded.
- Information objects are assigned a retention period based on the
  applicable selection list and are destroyed after expiry.
- The application owner and process owner are jointly responsible for
  correct application of these archiving functionalities.

**Examples**

- Commonly used decentralised classification structures include the
  Basic Archive Code and Case Type Catalogue.
- Information objects are always traceable to the work processes in which
  they were created or used.
- Information objects are always findable based on linked metadata.

---

### Principle 22 — Privacy by Design and Privacy by Default

| Attribute | Detail |
|-----------|--------|
| **ID** | 22 |
| **Principle** | We work according to Privacy by Design and Privacy by Default (PbD²) |
| **Architecture Layer** | Security Architecture |
| **Architecture Domain** | *(cross-cutting)* |
| **Source** | CIP Handbook Privacy by Design, CIP Privacy Baseline |

**Explanation**

To handle personal data safely and comply with the GDPR (General Data
Protection Regulation), we work according to PbD². This covers the
entire lifecycle of data processing, from collection to archiving, both
automated and manual. We follow the CIP guidelines "PbD Handbook" and
the "Privacy Baseline" for assurance.

Note: There is a close relationship with principles 20 and 21.

**Motivation**

Government bodies are legally obligated under the GDPR to work according
to PbD². Information is the societal capital of the organisation. Having
reliable and integer information regarding personal data is important
for good operations. Operations — including processes, organisation, and
applications — must be configured to create the right preconditions.

The goal of Privacy by Design is to proactively embed privacy criteria
into the design and management of information systems, and to embed
privacy measures into the technology.

PbD not only reduces the likelihood of privacy breaches but also the
risk of fines and damage claims. Retrofitting is harder and costlier
than building it in from the start.

**Implications**

- We use the CIP guidelines "PbD Handbook" and the "Privacy Baseline" as
  starting points in the practical application of this principle.
- There is a board-approved privacy policy based on and compliant with
  the GDPR and thereby the BIO (Baseline Information Security for
  Government).
- All privacy responsibilities are clearly defined and assigned.
- Line management is responsible for the quality of operations and
  thereby for handling personal data.
- The system and process owner is responsible for:
  - Privacy classification at process, system, and data level.
  - Implementing protection measures to achieve the required level of
    personal data protection.
- Employees, hired staff, and external users understand their
  responsibilities regarding personal data handling and act accordingly.
- PbD² is based on risk assessment, starting from the very first
  thoughts about changes in data processing, such as new or modified
  systems.
- Appropriate concrete measures are taken — preferably already in the
  design phase — to systematically meet data protection requirements.
- Both during design/implementation and during use, tests are conducted
  on the effectiveness of privacy measures.
- The DPO (Data Protection Officer) and ISO (Information Security
  Office) are informed about privacy classification, measures taken, and
  effectiveness.
- Safeguarding PbD² requirements is a continuous, cyclical process and
  must be embedded in the PDCA cycle.

**Examples**

- Authorisations regarding processing of personal data in processes and
  applications (logical and physical access) are properly arranged.
- It is always documented where and why personal data is present in a
  processing operation (processing register).
- If privacy-sensitive data is managed by an external party, a data
  processing agreement is concluded.

---

## Principles by Architecture Layer — Summary

| Layer | Domain | # | Principle |
|-------|--------|---|-----------|
| Business Architecture | Organisation | 1 | Central governance on ICT and information services |
| Business Architecture | Organisation | 2 | Sourcing via established assessment framework |
| Business Architecture | Organisation | 3 | Every primary data element, process, and application has an owner |
| Business Architecture | Services & Products | 4 | Digital channel first for service delivery |
| Business Architecture | Services & Products | 5 | ICT facilities aligned with business availability requirements |
| Business Architecture | Processes | 6 | We work under architecture |
| Business Architecture | Processes | 7 | Process optimisation through digitisation and standardisation |
| Business Architecture | Processes | 8 | Case-oriented working in service delivery |
| Business Architecture | Processes | 9 | Harmonise processes and applications for collaboration |
| Information Architecture | Employees & Applications | 10 | Location- and time-independent working |
| Information Architecture | Employees & Applications | 11 | Standard before custom, joint before individual |
| Information Architecture | Employees & Applications | 12 | One application per type of functionality |
| Information Architecture | Employees & Applications | 21* | Sustainable accessibility of information |
| Information Architecture | Messages & Data | 13 | A data element has one source |
| Information Architecture | Messages & Data | 14 | We use standards |
| Information Architecture | Information Exchange | 15 | All information is public unless determined otherwise |
| Information Architecture | Information Exchange | 16 | Processes are supported by services |
| Information Architecture | Information Exchange | 17 | We request data only once |
| Technical Architecture | Technical Components | 18 | Standardisation on interfaces |
| Management Architecture | *(cross-cutting)* | 19 | Information services are managed |
| Security Architecture | *(cross-cutting)* | 20 | Information security and business continuity standards |
| Security Architecture | *(cross-cutting)* | 22* | Privacy by Design and Privacy by Default |

*\* Principles 21 and 22 were added later.*
