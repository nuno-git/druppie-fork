/**
 * Skill loader — discovers and loads installable skills from:
 * 1. Built-in skills (./builtin/)
 * 2. Project skills (.pi/skills/)
 * 3. Custom skill paths from config
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createSyntheticSourceInfo, type Skill } from "@mariozechner/pi-coding-agent";

/** A loadable skill definition. */
export interface SkillDefinition {
  name: string;
  description: string;
  filePath: string;
  baseDir: string;
}

const SKILL_FILE = "SKILL.md";

export function discoverSkills(searchPaths: string[]): SkillDefinition[] {
  const skills: SkillDefinition[] = [];

  for (const basePath of searchPaths) {
    const resolved = resolve(basePath);
    if (!existsSync(resolved)) continue;

    const entries = readdirSync(resolved, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const skillFile = join(resolved, entry.name, SKILL_FILE);
      if (!existsSync(skillFile)) continue;

      const content = readFileSync(skillFile, "utf-8");
      const description = extractDescription(content);

      skills.push({
        name: entry.name,
        description,
        filePath: skillFile,
        baseDir: join(resolved, entry.name),
      });
    }
  }

  return skills;
}

function extractDescription(content: string): string {
  // Extract first paragraph or line after the heading
  const lines = content.split("\n").filter((l) => l.trim());
  for (const line of lines) {
    if (!line.startsWith("#")) return line.trim();
  }
  return "No description";
}

export function toSdkSkills(definitions: SkillDefinition[]): Skill[] {
  return definitions.map((def) => ({
    name: def.name,
    description: def.description,
    filePath: def.filePath,
    baseDir: def.baseDir,
    sourceInfo: createSyntheticSourceInfo(def.filePath, {
      source: "custom",
      scope: "project",
      origin: "top-level",
      baseDir: def.baseDir,
    }),
    disableModelInvocation: false,
  }));
}
