-- =============================================================================
-- Azure Synapse Serverless SQL Pool - Test Data & Security Setup
-- =============================================================================
--
-- Prerequisites:
--   1. Synapse workspace has an Entra ID admin configured
--   2. Run this script connected AS the Entra ID admin (or Synapse admin)
--   3. The Entra ID account dataplatformtest@waterschap.org must exist in
--      the same tenant as the Synapse workspace
--
-- What this script does:
--   - Creates a test database with fake waterschap data (all in dbo)
--   - Creates the Entra ID external user
--   - GRANTs SELECT on specific views, no access to the rest
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. DATABASE
-- ---------------------------------------------------------------------------

USE master;
GO

-- Make sure no other query tabs are connected to WaterschapTestDB before running this
IF EXISTS (SELECT * FROM sys.databases WHERE name = 'WaterschapTestDB')
    DROP DATABASE WaterschapTestDB;
GO

CREATE DATABASE WaterschapTestDB;
GO

USE WaterschapTestDB;
GO


-- ---------------------------------------------------------------------------
-- 2. FAKE DATA (all views in dbo)
-- ---------------------------------------------------------------------------

-- Water quality measurements
CREATE VIEW water_quality AS
SELECT *
FROM (VALUES
    (1,  'Noord', 'Kanaal A',  '2026-06-01', 7.2, 12.5, 0.03, 8.1, 'good'),
    (2,  'Noord', 'Kanaal A',  '2026-06-15', 7.1, 13.0, 0.04, 7.9, 'good'),
    (3,  'Noord', 'Sloot B',   '2026-06-01', 6.8, 15.2, 0.12, 6.5, 'moderate'),
    (4,  'Zuid',  'Rivier C',  '2026-06-01', 7.5, 11.8, 0.02, 8.8, 'good'),
    (5,  'Zuid',  'Rivier C',  '2026-06-15', 7.4, 12.1, 0.05, 8.5, 'good'),
    (6,  'Zuid',  'Plas D',    '2026-06-01', 6.5, 18.3, 0.25, 5.2, 'poor'),
    (7,  'Oost', 'Beek E',    '2026-06-01', 7.0, 10.5, 0.01, 9.0, 'good'),
    (8,  'Oost', 'Vijver F',  '2026-06-01', 6.9, 16.7, 0.08, 7.0, 'moderate'),
    (9,  'Oost', 'Vijver F',  '2026-06-15', 6.7, 17.5, 0.15, 6.2, 'moderate'),
    (10, 'West', 'Gracht G',  '2026-06-01', 7.3, 13.9, 0.06, 7.8, 'good'),
    (11, 'West', 'Gracht G',  '2026-06-15', 7.1, 14.5, 0.09, 7.2, 'moderate'),
    (12, 'West', 'Vaart H',   '2026-06-01', 6.6, 19.0, 0.30, 4.8, 'poor')
) AS t(id, region, location_name, measurement_date, ph, temperature_c, nitrogen_mg_l, oxygen_mg_l, quality_class);
GO

-- Pump stations
CREATE VIEW pump_stations AS
SELECT *
FROM (VALUES
    (1, 'Noord', 'Gemaal De Brug',    52.3456, 4.8901, 1200, 'operational', '2026-06-30 08:00', 850,  72.5),
    (2, 'Noord', 'Gemaal Polderweg',   52.3678, 4.9123, 800,  'operational', '2026-06-30 08:00', 620,  78.0),
    (3, 'Zuid',  'Gemaal Rivierzicht', 51.9234, 4.5678, 2000, 'operational', '2026-06-30 08:00', 1800, 90.0),
    (4, 'Zuid',  'Gemaal Zuidpolder',  51.8901, 4.5234, 1500, 'maintenance', '2026-06-28 14:00', 0,    0.0),
    (5, 'Oost', 'Gemaal Beekdal',     52.1567, 5.3456, 600,  'operational', '2026-06-30 08:00', 450,  75.0),
    (6, 'Oost', 'Gemaal Heuvelhof',   52.1890, 5.3890, 900,  'alarm',       '2026-06-30 06:30', 900,  100.0),
    (7, 'West', 'Gemaal Havenmond',   52.0123, 4.3456, 3000, 'operational', '2026-06-30 08:00', 2100, 70.0),
    (8, 'West', 'Gemaal Duinrand',    52.0456, 4.3123, 1100, 'operational', '2026-06-30 08:00', 780,  71.0)
) AS t(id, region, station_name, lat, lon, capacity_m3h, status, last_reading, current_flow_m3h, utilization_pct);
GO

-- Water level sensors
CREATE VIEW water_levels AS
SELECT *
FROM (VALUES
    (1, 'Noord', 'Kanaal A - km 2.5', '2026-06-30 07:00', -1.20, -1.50, -0.80, 'normal'),
    (2, 'Noord', 'Kanaal A - km 8.0', '2026-06-30 07:00', -1.15, -1.50, -0.80, 'normal'),
    (3, 'Noord', 'Sloot B - km 0.5',  '2026-06-30 07:00', -0.75, -1.00, -0.50, 'warning'),
    (4, 'Zuid',  'Rivier C - km 3.0', '2026-06-30 07:00', -0.90, -1.20, -0.60, 'normal'),
    (5, 'Zuid',  'Plas D',            '2026-06-30 07:00', -0.55, -1.00, -0.30, 'critical'),
    (6, 'Oost', 'Beek E - km 1.0',   '2026-06-30 07:00', -1.30, -1.60, -0.90, 'normal'),
    (7, 'Oost', 'Vijver F',          '2026-06-30 07:00', -0.85, -1.10, -0.60, 'normal'),
    (8, 'West', 'Gracht G - km 4.0', '2026-06-30 07:00', -1.00, -1.30, -0.70, 'normal'),
    (9, 'West', 'Vaart H - km 2.0',  '2026-06-30 07:00', -0.40, -0.80, -0.20, 'critical')
) AS t(id, region, sensor_location, reading_time, level_m_nap, target_min_m, target_max_m, alert_status);
GO

-- Budget data (sensitive)
CREATE VIEW budget AS
SELECT *
FROM (VALUES
    (1,  'Noord', 2026, 'Onderhoud',    450000.00,  280000.00,  62.2),
    (2,  'Noord', 2026, 'Investeringen', 1200000.00, 350000.00,  29.2),
    (3,  'Zuid',  2026, 'Onderhoud',    680000.00,  520000.00,  76.5),
    (4,  'Zuid',  2026, 'Investeringen', 2500000.00, 1800000.00, 72.0),
    (5,  'Oost', 2026, 'Onderhoud',    320000.00,  190000.00,  59.4),
    (6,  'Oost', 2026, 'Investeringen', 800000.00,  150000.00,  18.8),
    (7,  'West', 2026, 'Onderhoud',    550000.00,  410000.00,  74.5),
    (8,  'West', 2026, 'Investeringen', 1800000.00, 900000.00,  50.0),
    (9,  'Noord', 2026, 'Personeel',    890000.00,  445000.00,  50.0),
    (10, 'Zuid',  2026, 'Personeel',    1100000.00, 550000.00,  50.0),
    (11, 'Oost', 2026, 'Personeel',    670000.00,  335000.00,  50.0),
    (12, 'West', 2026, 'Personeel',    780000.00,  390000.00,  50.0)
) AS t(id, region, year, category, budget_eur, spent_eur, spent_pct);
GO

-- Incidents
CREATE VIEW incidents AS
SELECT *
FROM (VALUES
    (1, 'Zuid',  '2026-06-25 03:15', '2026-06-25 11:30', 'high',     'Dijk lekkage bij Plas D',                'Noodpompen geplaatst, reparatie uitgevoerd'),
    (2, 'Oost', '2026-06-29 18:45', NULL,                'critical', 'Gemaal Heuvelhof capaciteit overschreden','Onderzoek lopend, extra pompcapaciteit aangevraagd'),
    (3, 'Noord','2026-06-20 09:00', '2026-06-20 16:00', 'medium',   'Algengroei Sloot B',                     'Monsters genomen, behandelplan opgesteld'),
    (4, 'West', '2026-06-28 14:20', NULL,                'high',     'Kritiek waterpeil Vaart H',              'Gemaal Havenmond op vol vermogen'),
    (5, 'Zuid', '2026-06-15 07:00', '2026-06-15 09:30', 'low',      'Sensor storing Rivier C km 3.0',         'Sensor vervangen')
) AS t(id, region, reported_at, resolved_at, severity, description, action_taken);
GO


-- ---------------------------------------------------------------------------
-- 3. ENTRA ID USER
-- ---------------------------------------------------------------------------

CREATE USER [dataplatformtest@waterschap.org] FROM EXTERNAL PROVIDER;
GO


-- ---------------------------------------------------------------------------
-- 4. PERMISSIONS (per object)
-- ---------------------------------------------------------------------------
-- Grant: water_quality, pump_stations, water_levels  (user CAN see these)
-- Deny:  budget, incidents                            (user CANNOT see these)

GRANT SELECT ON OBJECT::dbo.water_quality  TO [dataplatformtest@waterschap.org];
GO
GRANT SELECT ON OBJECT::dbo.pump_stations  TO [dataplatformtest@waterschap.org];
GO
GRANT SELECT ON OBJECT::dbo.water_levels   TO [dataplatformtest@waterschap.org];
GO

DENY SELECT ON OBJECT::dbo.budget    TO [dataplatformtest@waterschap.org];
GO
DENY SELECT ON OBJECT::dbo.incidents TO [dataplatformtest@waterschap.org];
GO


-- ---------------------------------------------------------------------------
-- 5. VERIFICATION (run as admin)
-- ---------------------------------------------------------------------------

SELECT name, type_desc, authentication_type_desc
FROM sys.database_principals
WHERE name = 'dataplatformtest@waterschap.org';
GO

SELECT
    dp.name  AS principal_name,
    s.name   AS schema_name,
    o.name   AS object_name,
    p.permission_name,
    p.state_desc
FROM sys.database_permissions p
JOIN sys.database_principals dp ON p.grantee_principal_id = dp.principal_id
LEFT JOIN sys.objects o ON p.major_id = o.object_id
LEFT JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE dp.name = 'dataplatformtest@waterschap.org'
ORDER BY p.state_desc, o.name;
GO

-- Test as the user (or log in as dataplatformtest@waterschap.org)
-- EXECUTE AS USER = 'dataplatformtest@waterschap.org';
-- GO
--
-- SELECT * FROM water_quality;   -- should work  (12 rows)
-- SELECT * FROM pump_stations;   -- should work  (8 rows)
-- SELECT * FROM water_levels;    -- should work  (9 rows)
-- SELECT * FROM budget;          -- should FAIL  (access denied)
-- SELECT * FROM incidents;       -- should FAIL  (access denied)
--
-- REVERT;
-- GO
