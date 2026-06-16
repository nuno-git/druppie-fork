"""Message compaction for the agent runtime.

Progressive compression of conversation history to stay within context
limits while preserving semantic context about what the agent has done.

Three-phase compression:
  Phase 1  (>threshold1): Content-aware tool result summarization
  Phase 2  (>threshold2): Replace old turns with rich one-line summaries
  Phase 3  (>threshold3): LLM-summarize the compressed history
  Overflow (>100%):       Force done() — agent must terminate
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.events import EventEmitter
from druppie.agent_runtime.types import AgentEvent

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    """Per-run compression configuration."""

    max_context_tokens: int = 150_000
    keep_recent: int = 6
    phase1_threshold: float = 0.50
    phase2_threshold: float = 0.70
    phase3_threshold: float = 0.85
    phase1_truncate_chars: int = 500
    phase1_head_tail: tuple[int, int] = (200, 200)
    phase3_max_input_chars: int = 20_000
    phase3_max_output_tokens: int = 1024
    content_aware: bool = True
    adaptive_recent: bool = True
    tool_result_max_chars: int = 15_000


@dataclass
class ToolResultMeta:
    """Metadata extracted from a tool result before truncation."""

    tool_name: str
    key_arg: str = ""
    status: str = "ok"
    line_count: int | None = None
    structures: list[str] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    match_count: int | None = None
    summary_hint: str = ""


@dataclass
class CompactionState:
    """Mutable state persisted across compression calls within a run."""

    last_compressed_group_count: int = 0
    calibration_ratio: float = 4.0
    calibration_samples: int = 0
    tool_result_metadata: dict[str, ToolResultMeta] = field(default_factory=dict)


class MessageCompactor:
    """Manages progressive message compression for an agent run."""

    def __init__(
        self,
        config: CompactionConfig | None = None,
        summary_llm: Callable | None = None,
    ):
        self.config = config or CompactionConfig()
        self.state = CompactionState()
        self._summary_llm = summary_llm

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Estimate token count using structured counting with calibration.

        Counts content strings per message type separately to avoid
        double-counting from str(dict) on structured messages.
        """
        total = 0
        ratio = self.state.calibration_ratio

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            chars = len(content) if isinstance(content, str) else len(str(content))

            tool_calls = msg.get("tool_calls")
            if role == "assistant" and tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    chars += len(func.get("name", ""))
                    chars += len(func.get("arguments", ""))

            total += int(chars / ratio) + 4  # 4 tokens overhead per message

        return total

    def calibrate(self, actual_prompt_tokens: int, messages: list[dict]) -> None:
        """Refine the chars-per-token ratio using real API data."""
        if actual_prompt_tokens < 100:
            return

        total_chars = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total_chars += len(content) if isinstance(content, str) else len(str(content))
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    total_chars += len(func.get("name", ""))
                    total_chars += len(func.get("arguments", ""))

        real_ratio = total_chars / actual_prompt_tokens
        real_ratio = max(2.5, min(6.0, real_ratio))

        old = self.state.calibration_ratio
        self.state.calibration_ratio = 0.7 * old + 0.3 * real_ratio
        self.state.calibration_samples += 1

    # ------------------------------------------------------------------
    # Main compression entry point
    # ------------------------------------------------------------------

    async def compress(
        self,
        messages: list[dict],
        llm: Callable | None,
        agent: AgentDefinition,
        emitter: EventEmitter | None,
    ) -> list[dict]:
        """Progressively compress conversation history.

        Phase 1 (>phase1_threshold): Content-aware tool result summarization.
        Phase 2 (>phase2_threshold): Replace old turns with rich one-line summaries.
        Phase 3 (>phase3_threshold): LLM-summarize the compressed history.
        """
        token_count = self.estimate_tokens(messages)
        max_tokens = self.config.max_context_tokens

        if token_count <= int(max_tokens * self.config.phase1_threshold):
            logger.debug(
                "compress_skip",
                estimated_tokens=token_count,
                threshold=int(max_tokens * self.config.phase1_threshold),
                ratio=round(token_count / max_tokens, 2),
            )
            return messages

        groups = self._group_into_turns(messages)

        header_count = 0
        for g in groups:
            if g[0].get("role") in ("system", "user"):
                header_count += 1
            else:
                break

        keep_recent = self._compute_keep_recent(
            len(groups), token_count / max_tokens,
        )

        if len(groups) <= header_count + keep_recent:
            return messages

        header_groups = groups[:header_count]
        body_groups = groups[header_count:-keep_recent]
        recent_groups = groups[-keep_recent:]

        # Phase 1: content-aware tool result summarization
        self._phase1_summarize_tool_results(body_groups)

        flat = self._flatten(header_groups, body_groups, recent_groups)
        token_count = self.estimate_tokens(flat)

        if token_count <= int(max_tokens * self.config.phase2_threshold):
            if emitter:
                emitter.emit(AgentEvent.now("context_compressed", {
                    "phase": 1, "tokens_after": token_count,
                }))
            return flat

        # Phase 2: replace old turns with rich one-line summaries
        condensed_lines = []
        for group in body_groups:
            line = self._condense_turn_group(group)
            if line:
                condensed_lines.append(line)

        summary_msg = {
            "role": "user",
            "content": (
                "[COMPRESSED HISTORY — older conversation turns summarized]\n"
                + "\n".join(condensed_lines)
                + "\n[END COMPRESSED HISTORY]"
            ),
        }

        result = self._flatten(header_groups, [], recent_groups, insert=summary_msg)
        token_count = self.estimate_tokens(result)

        if token_count <= int(max_tokens * self.config.phase3_threshold):
            if emitter:
                emitter.emit(AgentEvent.now("context_compressed", {
                    "phase": 2,
                    "tokens_after": token_count,
                    "turns_compressed": len(body_groups),
                }))
            return result

        # Phase 3: LLM summarization
        summarize_llm = self._summary_llm or llm
        if summarize_llm is not None:
            try:
                llm_summary = await self._summarize_with_llm(
                    summary_msg["content"], summarize_llm, agent,
                )
                if llm_summary:
                    summary_msg["content"] = (
                        "[CONVERSATION SUMMARY — previous work condensed by LLM]\n"
                        + llm_summary
                        + "\n[END SUMMARY — continue from recent context below]"
                    )
                    result = self._flatten(
                        header_groups, [], recent_groups, insert=summary_msg,
                    )
                    if emitter:
                        emitter.emit(AgentEvent.now("context_compressed", {
                            "phase": 3,
                            "tokens_after": self.estimate_tokens(result),
                            "turns_compressed": len(body_groups),
                        }))
                    return result
            except Exception as exc:
                logger.warning(
                    "context_llm_summary_failed", extra={"error": str(exc)},
                )

        # Fallback: reduce recent window
        reduced = recent_groups[-3:] if len(recent_groups) > 3 else recent_groups
        result = self._flatten(header_groups, [], reduced, insert=summary_msg)

        if emitter:
            emitter.emit(AgentEvent.now("context_compressed", {
                "phase": "3_fallback",
                "tokens_after": self.estimate_tokens(result),
            }))
        return result

    # ------------------------------------------------------------------
    # Phase 1: Content-aware tool result summarization
    # ------------------------------------------------------------------

    def _phase1_summarize_tool_results(self, body_groups: list[list[dict]]) -> None:
        """Summarize tool results in body groups, extracting metadata."""
        for group in body_groups:
            first = group[0]
            tool_calls = first.get("tool_calls", []) if first.get("role") == "assistant" else []
            tc_by_id = {tc.get("id"): tc for tc in tool_calls}

            for idx, msg in enumerate(group):
                if msg.get("role") != "tool":
                    continue

                content = msg.get("content", "")
                if not isinstance(content, str) or len(content) <= self.config.phase1_truncate_chars:
                    continue

                call_id = msg.get("tool_call_id", "")
                tc = tc_by_id.get(call_id, {})
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args = {}

                meta = self._extract_tool_metadata(tool_name, content, args)
                if call_id:
                    self.state.tool_result_metadata[call_id] = meta

                if self.config.content_aware:
                    summarized = self._summarize_tool_result(tool_name, content, args)
                else:
                    head, tail = self.config.phase1_head_tail
                    summarized = self._blind_truncate(content, head, tail)

                group[idx] = dict(msg)
                group[idx]["content"] = summarized

    def _summarize_tool_result(
        self, tool_name: str, content: str, args: dict,
    ) -> str:
        """Content-aware summarization of a tool result."""
        if tool_name in ("coding_read_file", "read_file"):
            return self._summarize_file_read(content, args.get("path", ""))
        elif tool_name in ("coding_bash", "bash"):
            return self._summarize_bash(content)
        elif tool_name in ("coding_grep", "grep", "coding_find", "find",
                           "coding_search_files", "search_files"):
            return self._summarize_search(content)
        elif tool_name in ("coding_write_file", "write_file",
                           "coding_edit_file", "edit_file",
                           "coding_batch_write_files", "batch_write_files"):
            return self._summarize_write(content)
        else:
            head, tail = self.config.phase1_head_tail
            return self._blind_truncate(content, head, tail)

    def _summarize_file_read(self, content: str, path: str) -> str:
        """Summarize a file read result, preserving structural markers."""
        lines = content.split("\n")
        line_count = len(lines)
        structures = _extract_code_structures(content, path)
        struct_str = ", ".join(structures[:15]) if structures else "no key structures found"
        head = content[:300]
        tail = content[-150:] if len(content) > 450 else ""
        parts = [f"[File: {path}, {line_count} lines] Structures: {struct_str}"]
        parts.append(f"Head:\n{head}")
        if tail:
            parts.append(f"...[{len(content)} chars truncated]...\nTail:\n{tail}")
        return "\n".join(parts)

    def _summarize_bash(self, content: str) -> str:
        """Summarize bash output, preserving errors and final lines."""
        lines = content.split("\n")
        total = len(lines)

        error_lines = []
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in ("error", "traceback", "fail", "exception", "fatal")):
                error_lines.append(line.strip())
                if len(error_lines) >= 10:
                    break

        first_lines = lines[:3]
        last_lines = lines[-5:] if total > 8 else lines[3:]

        parts = [f"[Bash output: {len(content)} chars, {total} lines]"]
        if first_lines:
            parts.append("First lines:\n" + "\n".join(first_lines))
        if error_lines:
            parts.append("Errors/failures:\n" + "\n".join(error_lines[:5]))
        if last_lines:
            parts.append("Last lines:\n" + "\n".join(last_lines))
        return "\n".join(parts)

    def _summarize_search(self, content: str) -> str:
        """Summarize grep/find results, keeping first matches + count."""
        lines = content.strip().split("\n")
        total = len(lines)
        kept = lines[:15]
        parts = [f"[{total} result lines]"]
        parts.append("\n".join(kept))
        if total > 15:
            parts.append(f"... and {total - 15} more results")
        return "\n".join(parts)

    def _summarize_write(self, content: str) -> str:
        """Summarize write/edit results — usually short, keep most of it."""
        if len(content) <= 500:
            return content
        return content[:400] + f"\n...[{len(content)} chars truncated]..."

    @staticmethod
    def _blind_truncate(content: str, head: int, tail: int) -> str:
        """Blind head/tail truncation fallback."""
        return (
            content[:head]
            + f"\n... [{len(content)} chars truncated] ...\n"
            + content[-tail:]
        )

    def _extract_tool_metadata(
        self, tool_name: str, content: str, args: dict,
    ) -> ToolResultMeta:
        """Extract metadata from a tool result for use in Phase 2 summaries."""
        key_arg = (
            args.get("path", "")
            or args.get("command", "")[:80]
            or args.get("query", "")[:80]
            or args.get("pattern", "")[:80]
            or ""
        )
        status = "ok"
        if isinstance(content, str) and content[:300].lower().find("error") >= 0:
            status = "err"

        meta = ToolResultMeta(tool_name=tool_name, key_arg=key_arg, status=status)

        if tool_name in ("coding_read_file", "read_file"):
            lines = content.split("\n")
            meta.line_count = len(lines)
            meta.structures = _extract_code_structures(content, args.get("path", ""))
        elif tool_name in ("coding_bash", "bash"):
            for line in content.split("\n"):
                lower = line.lower()
                if any(kw in lower for kw in ("error", "fail", "traceback")):
                    meta.error_lines.append(line.strip())
                    if len(meta.error_lines) >= 5:
                        break
            test_summary = _extract_test_summary(content)
            if test_summary:
                meta.summary_hint = test_summary
        elif tool_name in ("coding_grep", "grep", "coding_find", "find"):
            meta.match_count = len(content.strip().split("\n"))

        return meta

    # ------------------------------------------------------------------
    # Phase 2: Rich condensed summaries
    # ------------------------------------------------------------------

    def _condense_turn_group(self, group: list[dict]) -> str | None:
        """Create a rich one-line summary of a turn group."""
        if not group:
            return None
        first = group[0]
        role = first.get("role")

        if role == "assistant":
            tool_calls = first.get("tool_calls", [])
            if tool_calls:
                results_by_id: dict[str, str] = {}
                for msg in group[1:]:
                    if msg.get("role") == "tool":
                        results_by_id[msg.get("tool_call_id", "")] = msg.get("content", "")

                parts = []
                for tc in tool_calls:
                    call_id = tc.get("id", "")
                    name = tc.get("function", {}).get("name", "?")
                    args_str = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    key_arg = (
                        args.get("path", "")
                        or args.get("command", "")[:80]
                        or args.get("query", "")[:80]
                        or ""
                    )

                    result_content = results_by_id.get(call_id, "")
                    status = "ok"
                    if isinstance(result_content, str) and (
                        "error" in result_content.lower()[:200]
                        or '"success": false' in result_content.lower()[:200]
                    ):
                        status = "err"

                    meta = self.state.tool_result_metadata.get(call_id)
                    annotation = ""
                    if meta:
                        annotation = self._build_annotation(meta)

                    base = f"{name}({key_arg})→{status}" if key_arg else f"{name}→{status}"
                    if annotation:
                        base += f" [{annotation}]"
                    parts.append(base)

                return "  " + ", ".join(parts)
            else:
                content = first.get("content", "")
                if content:
                    return f"  [text]: {content[:80]}"
        elif role == "user":
            content = first.get("content", "")
            if "[SYSTEM]" in content:
                return None
            return f"  [user]: {content[:80]}"
        elif role == "system":
            return f"  [system]: {first.get('content', '')[:80]}"
        return None

    @staticmethod
    def _build_annotation(meta: ToolResultMeta) -> str:
        """Build a bracket annotation from tool result metadata."""
        parts = []
        if meta.line_count is not None:
            parts.append(f"{meta.line_count} lines")
        if meta.structures:
            parts.append("; ".join(meta.structures[:5]))
        if meta.match_count is not None:
            parts.append(f"{meta.match_count} matches")
        if meta.error_lines:
            parts.append("errors: " + "; ".join(meta.error_lines[:2]))
        if meta.summary_hint:
            parts.append(meta.summary_hint)
        return ", ".join(parts)[:150]

    # ------------------------------------------------------------------
    # Phase 3: LLM summarization
    # ------------------------------------------------------------------

    async def _summarize_with_llm(
        self,
        history_text: str,
        llm: Callable,
        agent: AgentDefinition,
    ) -> str:
        response = await llm(
            model=agent.llm_profile,
            messages=[
                {"role": "system", "content": (
                    "Summarize this coding agent conversation history. Focus on:\n"
                    "1. Files read and their key contents (class/function names, routes, schemas)\n"
                    "2. Files created or modified and what changes were made\n"
                    "3. Tests run and their results\n"
                    "4. Errors encountered and whether they were resolved\n"
                    "5. Current state of the task and remaining work\n"
                    "\n"
                    "Be specific with file paths, function names, and variable names.\n"
                    "Use bullet points. Maximum 300 words."
                )},
                {"role": "user", "content": history_text[:self.config.phase3_max_input_chars]},
            ],
            tools=[],
            temperature=0.0,
            max_tokens=self.config.phase3_max_output_tokens,
        )
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    # ------------------------------------------------------------------
    # Adaptive keep_recent
    # ------------------------------------------------------------------

    def _compute_keep_recent(
        self, total_groups: int, token_ratio: float,
    ) -> int:
        """Compute adaptive recent window size based on context pressure."""
        base = self.config.keep_recent

        if not self.config.adaptive_recent:
            return base

        if token_ratio < 0.6:
            target = base + 4
        elif token_ratio < 0.8:
            target = base
        else:
            target = max(3, base - 2)

        return min(target, total_groups - 2)

    # ------------------------------------------------------------------
    # Tool result truncation (per-result, before adding to messages)
    # ------------------------------------------------------------------

    @staticmethod
    def truncate_tool_result(content: str, max_chars: int = 15_000) -> str:
        """Truncate an individual tool result before adding to messages."""
        if len(content) <= max_chars:
            return content
        if len(content) > 50_000:
            head, tail = 3000, 1000
        else:
            head, tail = 5000, 2000
        return (
            content[:head]
            + f"\n\n... [output truncated: {len(content)} chars, "
            f"showing first {head} and last {tail}] ...\n\n"
            + content[-tail:]
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_into_turns(messages: list[dict]) -> list[list[dict]]:
        """Group messages into logical turns preserving tool_call_id pairing."""
        groups: list[list[dict]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                group = [msg]
                expected_ids = {tc.get("id") for tc in msg["tool_calls"]}
                j = i + 1
                while (
                    j < len(messages)
                    and messages[j].get("role") == "tool"
                    and messages[j].get("tool_call_id") in expected_ids
                ):
                    group.append(messages[j])
                    j += 1
                groups.append(group)
                i = j
            else:
                groups.append([msg])
                i += 1
        return groups

    @staticmethod
    def _flatten(
        header_groups: list[list[dict]],
        body_groups: list[list[dict]],
        recent_groups: list[list[dict]],
        insert: dict | None = None,
    ) -> list[dict]:
        """Flatten groups back into a message list, with optional insert."""
        result: list[dict] = []
        for g in header_groups:
            result.extend(g)
        for g in body_groups:
            result.extend(g)
        if insert:
            result.append(insert)
        for g in recent_groups:
            result.extend(g)
        return result


# ------------------------------------------------------------------
# Code structure extraction helpers
# ------------------------------------------------------------------

_PYTHON_STRUCTURE_RE = re.compile(
    r"^(?:class\s+(\w+)|def\s+(\w+)|(?:from\s+\S+\s+)?import\s+(.+))",
    re.MULTILINE,
)
_JS_STRUCTURE_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)"
    r"|(?:class|function)\s+(\w+)"
    r"|import\s+.+\s+from\s+['\"](.+)['\"])",
    re.MULTILINE,
)
_ROUTE_RE = re.compile(
    r"""(?:@\w+\.(?:route|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]"""
    r"""|app\.(?:get|post|put|delete|patch|route)\s*\(\s*['"]([^'"]+)['"])""",
)


def _extract_code_structures(content: str, path: str) -> list[str]:
    """Extract structural markers from code content."""
    structures: list[str] = []
    ext = path.rsplit(".", 1)[-1] if "." in path else ""

    if ext in ("py", "pyi"):
        for m in _PYTHON_STRUCTURE_RE.finditer(content):
            cls, func, imp = m.groups()
            if cls:
                structures.append(f"class {cls}")
            elif func:
                structures.append(f"def {func}")
    elif ext in ("js", "jsx", "ts", "tsx", "mjs"):
        for m in _JS_STRUCTURE_RE.finditer(content):
            name = m.group(1) or m.group(2) or m.group(3)
            if name:
                structures.append(name)
    elif ext == "json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                structures = [f"key:{k}" for k in list(data.keys())[:5]]
        except (json.JSONDecodeError, TypeError):
            pass

    for m in _ROUTE_RE.finditer(content):
        route = m.group(1) or m.group(2)
        if route:
            structures.append(f"route:{route}")

    return structures[:20]


def _extract_test_summary(content: str) -> str:
    """Try to extract a test result summary line from bash output."""
    patterns = [
        re.compile(r"(\d+)\s+passed.*?(\d+)\s+failed", re.IGNORECASE),
        re.compile(r"Tests:\s*(\d+)\s+passed,\s*(\d+)\s+failed", re.IGNORECASE),
        re.compile(r"(\d+)\s+passing.*?(\d+)\s+failing", re.IGNORECASE),
        re.compile(r"TOTAL.*?(\d+).*?(\d+)\s+errors?", re.IGNORECASE),
    ]
    for pat in patterns:
        m = pat.search(content[-2000:])
        if m:
            return m.group(0).strip()[:80]
    passed_match = re.search(r"(\d+)\s+(?:passed|passing|tests?\s+passed)", content[-2000:], re.IGNORECASE)
    if passed_match:
        return passed_match.group(0).strip()[:80]
    return ""
