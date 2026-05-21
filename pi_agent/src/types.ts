/**
 * Core types for the pi_agent package.
 */

// ── Task Input ──────────────────────────────────────────────

/** A task specification that the system will build. */
export interface TaskSpec {
  description: string;
  language: string;
  targetDir?: string;
  contextFiles?: string[];
  skills?: string[];
  pushOnComplete?: boolean;
  branch?: string;
  testCommand?: string;
  buildCommand?: string;
  /** If set, the host clones this repo (using sandbox.pushToken or the minted
   * App token) and ships the contents into the sandbox as a git bundle before
   * the agent starts. The sandbox never sees the remote URL or the token. */
  sourceRepoUrl?: string;
  /** Branch in sourceRepoUrl to base the agent's work on. Default: "main". */
  sourceBranch?: string;
}
