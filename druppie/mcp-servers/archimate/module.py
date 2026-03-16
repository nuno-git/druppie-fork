"""ArchiMate MCP Server - Business Logic Module.

Parses ArchiMate Open Exchange Format XML files and provides
structured access to elements, relationships, views, and organizations.
"""

import logging
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger("archimate-mcp")

NS = {"am": "http://www.opengroup.org/xsd/archimate/3.0/"}
XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Properties to skip (internal Archi metadata, not useful for architecture)
SKIP_PROPERTIES = {"Object ID", "Original ID", "Semanticsearch"}

LAYER_MAP = {
    # Strategy
    "Capability": "Strategy",
    "Resource": "Strategy",
    "CourseOfAction": "Strategy",
    "ValueStream": "Strategy",
    # Motivation
    "Stakeholder": "Motivation",
    "Driver": "Motivation",
    "Assessment": "Motivation",
    "Goal": "Motivation",
    "Outcome": "Motivation",
    "Principle": "Motivation",
    "Requirement": "Motivation",
    "Constraint": "Motivation",
    "Meaning": "Motivation",
    "Value": "Motivation",
    # Business
    "BusinessActor": "Business",
    "BusinessRole": "Business",
    "BusinessCollaboration": "Business",
    "BusinessInterface": "Business",
    "BusinessProcess": "Business",
    "BusinessFunction": "Business",
    "BusinessInteraction": "Business",
    "BusinessEvent": "Business",
    "BusinessService": "Business",
    "BusinessObject": "Business",
    "Contract": "Business",
    "Representation": "Business",
    "Product": "Business",
    # Application
    "ApplicationComponent": "Application",
    "ApplicationCollaboration": "Application",
    "ApplicationInterface": "Application",
    "ApplicationFunction": "Application",
    "ApplicationInteraction": "Application",
    "ApplicationProcess": "Application",
    "ApplicationEvent": "Application",
    "ApplicationService": "Application",
    "DataObject": "Application",
    # Technology
    "Node": "Technology",
    "Device": "Technology",
    "SystemSoftware": "Technology",
    "TechnologyCollaboration": "Technology",
    "TechnologyInterface": "Technology",
    "Path": "Technology",
    "CommunicationNetwork": "Technology",
    "TechnologyFunction": "Technology",
    "TechnologyProcess": "Technology",
    "TechnologyInteraction": "Technology",
    "TechnologyEvent": "Technology",
    "TechnologyService": "Technology",
    "Artifact": "Technology",
    # Physical
    "Equipment": "Physical",
    "Facility": "Physical",
    "DistributionNetwork": "Physical",
    "Material": "Physical",
    # Implementation & Migration
    "WorkPackage": "Implementation & Migration",
    "Deliverable": "Implementation & Migration",
    "ImplementationEvent": "Implementation & Migration",
    "Plateau": "Implementation & Migration",
    "Gap": "Implementation & Migration",
    # Other
    "Grouping": "Other",
    "Location": "Other",
    "Junction": "Other",
}

RELATION_LABELS = {
    "Serving": ("serves", "served by"),
    "Flow": ("flows to", "flows from"),
    "Composition": ("composed of", "part of"),
    "Aggregation": ("aggregates", "aggregated by"),
    "Assignment": ("assigned to", "assigned from"),
    "Realization": ("realizes", "realized by"),
    "Triggering": ("triggers", "triggered by"),
    "Access": ("accesses", "accessed by"),
    "Influence": ("influences", "influenced by"),
    "Specialization": ("specializes", "specialized by"),
    "Association": ("associated with", "associated with"),
}


class ArchiMateModule:
    """Business logic for ArchiMate model operations."""

    def __init__(self, models_dir):
        self.models_dir = Path(models_dir)
        self.models = {}
        self._load_all_models()

    def _load_all_models(self):
        """Load and parse all XML files in the models directory."""
        for xml_file in self.models_dir.glob("*.xml"):
            try:
                model = self._parse_model(xml_file)
                self.models[model["name"]] = model
                logger.info(
                    "Loaded model '%s' from %s: %d elements, %d relationships, %d views",
                    model["name"],
                    xml_file.name,
                    len(model["elements"]),
                    len(model["relationships"]),
                    len(model["views"]),
                )
            except Exception as e:
                logger.error("Failed to parse %s: %s", xml_file, e)

    def _get_text(self, elem, tag):
        """Extract text from a child element."""
        child = elem.find(f"am:{tag}", NS)
        if child is not None and child.text:
            return child.text.strip()
        return ""

    def _parse_properties(self, elem, prop_defs):
        """Parse properties from an element, resolving definition refs to names."""
        props = {}
        props_elem = elem.find("am:properties", NS)
        if props_elem is None:
            return props
        for prop in props_elem.findall("am:property", NS):
            ref = prop.get("propertyDefinitionRef", "")
            name = prop_defs.get(ref, ref)
            if name in SKIP_PROPERTIES:
                continue
            value_elem = prop.find("am:value", NS)
            if value_elem is not None and value_elem.text:
                props[name] = value_elem.text.strip()
        return props

    def _parse_property_definitions(self, root):
        """Parse propertyDefinitions section to map propid-X to names."""
        defs = {}
        pd_section = root.find("am:propertyDefinitions", NS)
        if pd_section is None:
            return defs
        for pd in pd_section.findall("am:propertyDefinition", NS):
            identifier = pd.get("identifier", "")
            name_elem = pd.find("am:name", NS)
            if name_elem is not None and name_elem.text:
                defs[identifier] = name_elem.text.strip()
        return defs

    def _parse_element(self, elem, prop_defs):
        """Parse a single element."""
        elem_type = elem.get(f"{{{XSI}}}type", "Unknown")
        return {
            "id": elem.get("identifier", ""),
            "name": self._get_text(elem, "name"),
            "type": elem_type,
            "layer": LAYER_MAP.get(elem_type, "Unknown"),
            "documentation": self._get_text(elem, "documentation"),
            "properties": self._parse_properties(elem, prop_defs),
        }

    def _parse_relationship(self, rel, prop_defs):
        """Parse a single relationship."""
        rel_type = rel.get(f"{{{XSI}}}type", "Unknown")
        parsed = {
            "id": rel.get("identifier", ""),
            "type": rel_type,
            "name": self._get_text(rel, "name"),
            "source": rel.get("source", ""),
            "target": rel.get("target", ""),
            "documentation": self._get_text(rel, "documentation"),
            "properties": self._parse_properties(rel, prop_defs),
        }
        access_type = rel.get("accessType")
        if access_type:
            parsed["access_type"] = access_type
        return parsed

    def _collect_view_refs(self, node):
        """Recursively collect element and relationship refs from view nodes."""
        element_refs = set()
        relationship_refs = set()

        elem_ref = node.get("elementRef")
        if elem_ref:
            element_refs.add(elem_ref)

        for child_node in node.findall("am:node", NS):
            child_elems, child_rels = self._collect_view_refs(child_node)
            element_refs.update(child_elems)
            relationship_refs.update(child_rels)

        for conn in node.findall("am:connection", NS):
            rel_ref = conn.get("relationshipRef")
            if rel_ref:
                relationship_refs.add(rel_ref)

        return element_refs, relationship_refs

    def _parse_view(self, view):
        """Parse a single view/diagram."""
        element_refs = set()
        relationship_refs = set()

        for node in view.findall("am:node", NS):
            elems, rels = self._collect_view_refs(node)
            element_refs.update(elems)
            relationship_refs.update(rels)

        for conn in view.findall("am:connection", NS):
            rel_ref = conn.get("relationshipRef")
            if rel_ref:
                relationship_refs.add(rel_ref)

        return {
            "id": view.get("identifier", ""),
            "name": self._get_text(view, "name"),
            "documentation": self._get_text(view, "documentation"),
            "element_refs": element_refs,
            "relationship_refs": relationship_refs,
        }

    def _parse_organizations(self, root):
        """Parse organization tree and build element-to-path index."""
        org_index = {}

        def traverse(item, path):
            label_elem = item.find("am:label", NS)
            if label_elem is not None and label_elem.text:
                current_path = f"{path} > {label_elem.text.strip()}" if path else label_elem.text.strip()
            else:
                current_path = path

            identifier_ref = item.get("identifierRef")
            if identifier_ref:
                org_index[identifier_ref] = current_path

            for child in item.findall("am:item", NS):
                traverse(child, current_path)

        orgs = root.find("am:organizations", NS)
        if orgs is not None:
            for item in orgs.findall("am:item", NS):
                traverse(item, "")

        return org_index

    def _parse_model(self, xml_path):
        """Parse a complete ArchiMate model from XML."""
        tree = ET.parse(xml_path)
        root = tree.getroot()

        model_name = self._get_text(root, "name") or xml_path.stem
        model_doc = self._get_text(root, "documentation")
        prop_defs = self._parse_property_definitions(root)

        elements = {}
        for elem in root.findall("am:elements/am:element", NS):
            parsed = self._parse_element(elem, prop_defs)
            elements[parsed["id"]] = parsed

        relationships = {}
        for rel in root.findall("am:relationships/am:relationship", NS):
            parsed = self._parse_relationship(rel, prop_defs)
            relationships[parsed["id"]] = parsed

        views = {}
        for view in root.findall("am:views/am:diagrams/am:view", NS):
            parsed = self._parse_view(view)
            views[parsed["id"]] = parsed

        organizations = self._parse_organizations(root)

        # Build indexes
        relations_by_source = defaultdict(list)
        relations_by_target = defaultdict(list)
        for rel in relationships.values():
            relations_by_source[rel["source"]].append(rel)
            relations_by_target[rel["target"]].append(rel)

        element_views = defaultdict(list)
        for view_id, view in views.items():
            for elem_ref in view["element_refs"]:
                element_views[elem_ref].append({"id": view_id, "name": view["name"]})

        # Name index for fast lookup
        name_index = defaultdict(list)
        for elem in elements.values():
            if elem["name"]:
                name_index[elem["name"].lower()].append(elem)

        return {
            "name": model_name,
            "documentation": model_doc,
            "file": xml_path.name,
            "prop_defs": prop_defs,
            "elements": elements,
            "relationships": relationships,
            "views": views,
            "organizations": organizations,
            "relations_by_source": relations_by_source,
            "relations_by_target": relations_by_target,
            "element_views": element_views,
            "name_index": name_index,
        }

    # --- Helpers ---

    def _get_model(self, model_name=""):
        """Get model by name (case-insensitive). If empty, return first/only model."""
        if not model_name:
            if self.models:
                return next(iter(self.models.values()))
            return None
        for name, model in self.models.items():
            if name.lower() == model_name.lower():
                return model
        return None

    def _find_element(self, model, identifier):
        """Find element by ID or name."""
        # Try exact ID match
        if identifier in model["elements"]:
            return model["elements"][identifier]

        # Try case-insensitive name match
        lower_id = identifier.lower()
        matches = model["name_index"].get(lower_id, [])
        if matches:
            return matches[0]

        # Try substring match on name
        for elem in model["elements"].values():
            if lower_id in elem["name"].lower():
                return elem

        return None

    def _find_view(self, model, identifier):
        """Find view by ID or name."""
        if identifier in model["views"]:
            return model["views"][identifier]

        lower_id = identifier.lower()
        for view in model["views"].values():
            if view["name"].lower() == lower_id:
                return view

        for view in model["views"].values():
            if lower_id in view["name"].lower():
                return view

        return None

    def _element_summary(self, elem):
        """Return a concise element summary."""
        summary = {
            "id": elem["id"],
            "name": elem["name"],
            "type": elem["type"],
            "layer": elem["layer"],
        }
        if elem["documentation"]:
            summary["documentation"] = elem["documentation"][:200]
        return summary

    def _get_element_relations(self, model, element_id):
        """Get all relations for an element, resolved with names."""
        outgoing = []
        for rel in model["relations_by_source"].get(element_id, []):
            target = model["elements"].get(rel["target"])
            labels = RELATION_LABELS.get(rel["type"], (rel["type"], rel["type"]))
            entry = {
                "type": rel["type"],
                "label": labels[0],
                "target_name": target["name"] if target else rel["target"],
                "target_type": target["type"] if target else "Unknown",
                "target_id": rel["target"],
            }
            if rel.get("name"):
                entry["relation_name"] = rel["name"]
            if rel.get("access_type"):
                entry["access_type"] = rel["access_type"]
            outgoing.append(entry)

        incoming = []
        for rel in model["relations_by_target"].get(element_id, []):
            source = model["elements"].get(rel["source"])
            labels = RELATION_LABELS.get(rel["type"], (rel["type"], rel["type"]))
            entry = {
                "type": rel["type"],
                "label": labels[1],
                "source_name": source["name"] if source else rel["source"],
                "source_type": source["type"] if source else "Unknown",
                "source_id": rel["source"],
            }
            if rel.get("name"):
                entry["relation_name"] = rel["name"]
            if rel.get("access_type"):
                entry["access_type"] = rel["access_type"]
            incoming.append(entry)

        return {"outgoing": outgoing, "incoming": incoming}

    # --- Public API ---

    def list_models(self):
        """List all loaded ArchiMate models."""
        models = []
        for name, model in self.models.items():
            models.append({
                "name": name,
                "file": model["file"],
                "description": model["documentation"][:300] if model["documentation"] else "",
                "element_count": len(model["elements"]),
                "relationship_count": len(model["relationships"]),
                "view_count": len(model["views"]),
            })
        return {"success": True, "models": models, "count": len(models)}

    def get_statistics(self, model_name=""):
        """Get overview statistics for a model."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found. Use list_models to see available models."}

        # Count by layer
        layer_counts = defaultdict(int)
        type_counts = defaultdict(int)
        for elem in model["elements"].values():
            layer_counts[elem["layer"]] += 1
            type_counts[elem["type"]] += 1

        # Count relationship types
        rel_type_counts = defaultdict(int)
        for rel in model["relationships"].values():
            rel_type_counts[rel["type"]] += 1

        return {
            "success": True,
            "model": model["name"],
            "description": model["documentation"][:500] if model["documentation"] else "",
            "totals": {
                "elements": len(model["elements"]),
                "relationships": len(model["relationships"]),
                "views": len(model["views"]),
            },
            "elements_by_layer": dict(sorted(layer_counts.items())),
            "elements_by_type": dict(sorted(type_counts.items())),
            "relationships_by_type": dict(sorted(rel_type_counts.items())),
        }

    def list_elements(self, model_name="", layer="", element_type="", max_results=50, offset=0):
        """List elements with optional filtering."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        filtered = []
        for elem in model["elements"].values():
            if layer and elem["layer"].lower() != layer.lower():
                continue
            if element_type and elem["type"].lower() != element_type.lower():
                continue
            filtered.append(self._element_summary(elem))

        filtered.sort(key=lambda e: e["name"])
        total = len(filtered)
        page = filtered[offset:offset + max_results]

        return {
            "success": True,
            "elements": page,
            "total": total,
            "offset": offset,
            "returned": len(page),
            "has_more": (offset + max_results) < total,
        }

    def get_element(self, model_name="", element_name=""):
        """Get full details of an element."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        elem = self._find_element(model, element_name)
        if not elem:
            return {"success": False, "error": f"Element '{element_name}' not found. Use search_model or list_elements to find elements."}

        relations = self._get_element_relations(model, elem["id"])
        views = model["element_views"].get(elem["id"], [])
        org_path = model["organizations"].get(elem["id"], "")

        result = {
            "id": elem["id"],
            "name": elem["name"],
            "type": elem["type"],
            "layer": elem["layer"],
            "documentation": elem["documentation"],
            "properties": elem["properties"],
            "relations": relations,
            "views": views,
        }
        if org_path:
            result["organization_path"] = org_path

        return {"success": True, "element": result}

    def list_views(self, model_name=""):
        """List all views in the model."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        views = []
        for view in sorted(model["views"].values(), key=lambda v: v["name"]):
            views.append({
                "id": view["id"],
                "name": view["name"],
                "element_count": len(view["element_refs"]),
                "relationship_count": len(view["relationship_refs"]),
            })

        return {"success": True, "views": views, "count": len(views)}

    def get_view(self, model_name="", view_id=""):
        """Get full contents of a view."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        view = self._find_view(model, view_id)
        if not view:
            return {"success": False, "error": f"View '{view_id}' not found. Use list_views to see available views."}

        elements = []
        for elem_ref in view["element_refs"]:
            elem = model["elements"].get(elem_ref)
            if elem:
                elements.append(self._element_summary(elem))
        elements.sort(key=lambda e: (e["layer"], e["type"], e["name"]))

        relationships = []
        for rel_ref in view["relationship_refs"]:
            rel = model["relationships"].get(rel_ref)
            if not rel:
                continue
            source = model["elements"].get(rel["source"])
            target = model["elements"].get(rel["target"])
            entry = {
                "type": rel["type"],
                "source_name": source["name"] if source else rel["source"],
                "target_name": target["name"] if target else rel["target"],
            }
            if rel.get("name"):
                entry["relation_name"] = rel["name"]
            relationships.append(entry)

        return {
            "success": True,
            "view": {
                "id": view["id"],
                "name": view["name"],
                "documentation": view["documentation"],
                "elements": elements,
                "relationships": relationships,
            },
        }

    def search_model(self, model_name="", query="", layer="", element_type="", max_results=20):
        """Search for elements by name or description."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        query_lower = query.lower()
        results = []

        for elem in model["elements"].values():
            if layer and elem["layer"].lower() != layer.lower():
                continue
            if element_type and elem["type"].lower() != element_type.lower():
                continue

            score = 0
            if elem["name"].lower() == query_lower:
                score = 3  # Exact name match
            elif query_lower in elem["name"].lower():
                score = 2  # Partial name match
            elif query_lower in elem["documentation"].lower():
                score = 1  # Documentation match
            else:
                # Check properties
                for val in elem["properties"].values():
                    if query_lower in val.lower():
                        score = 1
                        break

            if score > 0:
                entry = self._element_summary(elem)
                entry["_score"] = score
                results.append(entry)

        results.sort(key=lambda e: (-e["_score"], e["name"]))
        results = results[:max_results]

        # Remove internal score
        for r in results:
            del r["_score"]

        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results),
        }

    def get_impact(self, model_name="", element_name="", direction="both", max_depth=3):
        """Analyze impact by traversing relationships from an element."""
        model = self._get_model(model_name)
        if not model:
            return {"success": False, "error": f"Model '{model_name}' not found."}

        start = self._find_element(model, element_name)
        if not start:
            return {"success": False, "error": f"Element '{element_name}' not found."}

        visited = set()
        impacts = []
        queue = [(start["id"], 0, None, None)]  # (id, depth, via_relation_type, from_element_name)

        while queue:
            current_id, depth, via_rel, from_name = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)

            if depth > 0:
                elem = model["elements"].get(current_id)
                if elem:
                    impacts.append({
                        "element": self._element_summary(elem),
                        "depth": depth,
                        "via_relation": via_rel,
                        "from_element": from_name,
                    })

            if direction in ("downstream", "both"):
                for rel in model["relations_by_source"].get(current_id, []):
                    if rel["target"] not in visited:
                        source_elem = model["elements"].get(current_id)
                        labels = RELATION_LABELS.get(rel["type"], (rel["type"],))
                        queue.append((
                            rel["target"],
                            depth + 1,
                            f"{labels[0]} ({rel['type']})",
                            source_elem["name"] if source_elem else current_id,
                        ))

            if direction in ("upstream", "both"):
                for rel in model["relations_by_target"].get(current_id, []):
                    if rel["source"] not in visited:
                        target_elem = model["elements"].get(current_id)
                        labels = RELATION_LABELS.get(rel["type"], (rel["type"], rel["type"]))
                        queue.append((
                            rel["source"],
                            depth + 1,
                            f"{labels[1]} ({rel['type']})",
                            target_elem["name"] if target_elem else current_id,
                        ))

        # Group by depth
        by_depth = defaultdict(list)
        for impact in impacts:
            by_depth[impact["depth"]].append(impact)

        return {
            "success": True,
            "start_element": self._element_summary(start),
            "direction": direction,
            "max_depth": max_depth,
            "total_impacted": len(impacts),
            "impacts_by_depth": {str(d): items for d, items in sorted(by_depth.items())},
        }
