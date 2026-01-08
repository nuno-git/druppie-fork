# TODO

- [ ] Fix GeoNode installation, worrks only on intel based machines
- [x] Fix KeyCloak installation
- [x] Fix Press key ... message so it is only shown once on all
- [x] Add ingress path to UI
    - [x] Add ingress path to KeyCloak (/sys/keycloak)
    - [x] Add ingress path to GeoNode (/app/geonode)
    - [x] Add ingress path to GeoServer (/app/geoserver)
    - [x] Add ingress path to KONG API Gateway (/api)
    - [x] Add ingress path to NodeODM (/app/nodeodm)
    - [x] Add ingress path to Postgres Admin tool (/sys/postgres) (Skipped - Tool not installed)
    - [x] Add ingress path to Rancher UI (/sys/rancher)
    - [x] Add ingress path to Grafana (/sys/grafana)
- [x] Add multi user support, login via KeyCloak
- [ ] Add support for multiple pods (one per druppie project)
- [x] Add ai provider selection
- [x] Add authentication groups
- [ ] Add K3D support intel based macs
- [x] Configure the total solution as one working piece 
- [x] Convert generate_search_index to a druppie command and run it in docker file
- [x] Add security provider selection
- [x] Add authentication groups
- [ ] Secret management
- [ ] Finish the admin UI
- [x] Version number by checking git tags
- [x] Cost management, tokens used by plan
- [x] Build plane
- [ ] Plugin system
- [ ] Git saving of plans
- [x] Resume command
- [x] MCP support
- [ ] Optimize LLM context loading, remove headers
- [x] LLM Memory : https://medium.com/@sonitanishk2003/the-ultimate-guide-to-llm-memory-from-context-windows-to-advanced-agent-memory-systems-3ec106d2a345
- [x] Deep rescearch the core of druppie to get new spec
- [ ] Add background job processing
- [x] Add common function for directory location
- [ ] Add common function to call a tool script or mcp from an internal agent


