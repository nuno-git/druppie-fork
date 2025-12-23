# 🐘 pgAdmin - PostgreSQL Management

## Wat is het?
pgAdmin is de beheerinterface voor de PostgreSQL databases die in het cluster draaien.

## Waarvoor gebruik je het?
- **Database Beheer**: Tabellen bekijken, maken en wijzigen.
- **Queries**: SQL queries uitvoeren voor analyse of debugging.
- **Onderhoud**: Backups maken en gebruikers beheren.

## Inloggen
- **URL**: [https://pgadmin.localhost](https://pgadmin.localhost)
- **Gebruikersnaam**: `admin@druppie.nl` (pgAdmin vereist een e-mailadres, 'admin' alleen werkt niet)
- **Wachtwoord**: Zie het `.secrets` bestand (vaak gelijk aan `DRUPPIE_POSTGRES_PASS`)

## Hoe te gebruiken
1. Na inloggen zie je links de server "Druppie Shared DB" (of vergelijkbaar).
2. Klik het open en voer het database wachtwoord in (zie `.secrets` bestand, `DRUPPIE_POSTGRES_PASS`).
3. Browse door Databases > Schemas > Tables.
4. Gebruik de **Query Tool** (rechtermuisknop op een database) om SQL te schrijven.
