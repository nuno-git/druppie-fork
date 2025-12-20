# Knowledge Bot (RAG Agent)

## 🎯 Doelstelling
De **Knowledge Bot** is een gespecialiseerd bouwblok voor informatieontsluiting. Het stelt gebruikers in staat om via natuurlijke taal vragen te stellen over grote hoeveelheden ongestructureerde data (PDFs, documentatie, tickets) die specifiek zijn voor de organisatie. Het implementeert het Retrieval-Augmented Generation (RAG) patroon.

## 📋 Functionele Specificaties

### 1. Ingest & Indexing
- **Multi-format Support**: Moet tekst kunnen extraheren uit PDF, Word, Markdown, HTML, etc.
- **Chunking Strategy**: Slim opbreken van tekst in behapbare stukken met behoud van context.
- **Continuous Update**: Index moet up-to-date blijven als brondocumenten wijzigen.

### 2. Retrieval & Synthesis
- **Semantisch Zoeken**: Zoeken op betekenis, niet alleen trefwoorden (Vector Search).
- **Bronvermelding**: De bot MOET bij elk antwoord verwijzen naar de bron (pagina/document) waar de info vandaan komt (traceerbaarheid).
- **Hallucinatie Preventie**: Instructies om alleen te antwoorden op basis van de gevonden context ("Weet ik niet" is een geldig antwoord).

## 🔧 Technische Requirements

- **Vector Database**: Gebruik van een geoptimaliseerde DB (bijv. Qdrant, Pinecone, pgvector).
- **Embedding Models**: Gebruik van efficiënte modellen voor vectorisatie.
- **Hybrid Search**: Combinatie van keyword search (BM25) en vector search voor beste resultaten.

## 🔒 Security & Compliance

- **Document Level Security**: De bot mag alleen resultaten tonen uit documenten waar de gebruiker leesrechten op heeft (ACL filtering in de zoekopdracht).
- **Data Residency**: Documenten en vectoren blijven binnen de vertrouwde zone.

## 🔌 Interacties

| Input | Output |
| :--- | :--- |
| **Vraag** ("Hoe reset ik mijn wachtwoord?") | **Antwoord** + **Referenties** ([Handleiding.pdf, p.3]) |
| **Nieuw Document** (Upload) | **Bevestiging** (Geïndexeerd) |

## 🏗️ Relaties tot andere blokken
- **Aangestuurd door**: [Druppie Core](./druppie_core.md) (als de intentie "Informational" is).
- **Maakt gebruik van**: [Bouwblok Definities](./bouwblok_definities.md) voor configuratie.
