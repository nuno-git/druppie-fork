"""Compliance executor for policy and regulatory actions."""

import json
import structlog
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from .base import Executor, ExecutorResult
from druppie.core.models import Step, TokenUsage

logger = structlog.get_logger()


COMPLIANCE_SYSTEM_PROMPT = """You are a Compliance AI assistant.
Your role is to validate deployments, configurations, and code against regulatory requirements and organizational policies.

You specialize in:
- Data protection regulations (GDPR, AVG, etc.)
- Security best practices
- Organizational policies
- Audit requirements

Always:
- Be thorough in your analysis
- Cite specific regulations or policies
- Provide actionable recommendations
- Flag potential risks clearly"""


class ComplianceExecutor(Executor):
    """Executes compliance actions for policy validation.

    Handles actions:
    - compliance_check: Check against compliance rules
    - validate_policy: Validate against specific policies
    - audit_request: Generate audit documentation
    - security_review: Review security aspects
    - data_classification: Classify data sensitivity
    """

    HANDLED_ACTIONS = {
        "compliance_check",
        "validate_policy",
        "audit_request",
        "security_review",
        "data_classification",
        "privacy_assessment",
        "risk_assessment",
    }

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        compliance_rules: dict[str, Any] | None = None,
    ):
        """Initialize the ComplianceExecutor.

        Args:
            llm: LangChain chat model for analysis
            compliance_rules: Dictionary of compliance rules
        """
        self.llm = llm
        self.compliance_rules = compliance_rules or {}
        self.logger = logger.bind(executor="compliance")

    def set_llm(self, llm: BaseChatModel) -> None:
        """Set the LLM for analysis."""
        self.llm = llm

    def set_rules(self, rules: dict[str, Any]) -> None:
        """Set compliance rules."""
        self.compliance_rules = rules

    def can_handle(self, action: str) -> bool:
        """Check if this executor handles the action."""
        return action in self.HANDLED_ACTIONS

    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute a compliance action."""
        context = context or {}
        action = step.action

        if self.llm is None:
            return ExecutorResult(
                success=False,
                error="No LLM configured for compliance executor",
            )

        try:
            if action == "compliance_check":
                return await self._compliance_check(step, context)
            elif action == "validate_policy":
                return await self._validate_policy(step, context)
            elif action == "audit_request":
                return await self._audit_request(step, context)
            elif action == "security_review":
                return await self._security_review(step, context)
            elif action == "data_classification":
                return await self._data_classification(step, context)
            elif action == "privacy_assessment":
                return await self._privacy_assessment(step, context)
            elif action == "risk_assessment":
                return await self._risk_assessment(step, context)
            else:
                return ExecutorResult(
                    success=False,
                    error=f"Unknown action: {action}",
                )
        except Exception as e:
            self.logger.error("compliance_action_failed", action=action, error=str(e))
            return ExecutorResult(success=False, error=str(e))

    async def _compliance_check(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Perform compliance check."""
        params = step.params
        artifact = params.get("artifact", "")
        artifact_type = params.get("type", "code")
        regulations = params.get("regulations", ["GDPR", "AVG"])
        rules_to_check = params.get("rules", list(self.compliance_rules.keys()))

        rules_text = ""
        for rule_id in rules_to_check:
            if rule_id in self.compliance_rules:
                rule = self.compliance_rules[rule_id]
                rules_text += f"- {rule.get('name', rule_id)}: {rule.get('description', '')}\n"

        prompt = f"""Perform a compliance check on the following {artifact_type}:

{artifact}

Regulations to check: {', '.join(regulations)}

{"Specific rules:" if rules_text else ""}
{rules_text}

Analyze for:
1. Data protection compliance
2. Security requirements
3. Audit trail requirements
4. Access control requirements
5. Data residency requirements

Provide:
- Compliance status (PASS/FAIL/NEEDS_REVIEW)
- List of findings
- Severity levels (Critical/High/Medium/Low)
- Recommendations for remediation"""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "compliance_report": response.content,
                "type": "compliance_check",
                "regulations": regulations,
            },
            usage=usage,
            output_messages=["Compliance check completed"],
        )

    async def _validate_policy(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Validate against specific policies."""
        params = step.params
        artifact = params.get("artifact", "")
        policy_name = params.get("policy", "")
        policy_content = params.get("policy_content", "")

        prompt = f"""Validate the following against the policy "{policy_name}":

Artifact:
{artifact}

{"Policy content:" if policy_content else ""}
{policy_content}

Check:
1. Policy adherence
2. Violations
3. Edge cases
4. Missing requirements

Provide a validation report with pass/fail status and recommendations."""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "policy_validation": response.content,
                "policy": policy_name,
                "type": "policy_validation",
            },
            usage=usage,
            output_messages=[f"Policy validation completed for: {policy_name}"],
        )

    async def _audit_request(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Generate audit documentation."""
        params = step.params
        subject = params.get("subject", "")
        audit_type = params.get("audit_type", "general")
        period = params.get("period", "")
        evidence = params.get("evidence", [])

        prompt = f"""Generate audit documentation for:

Subject: {subject}
Audit Type: {audit_type}
{"Period: " + period if period else ""}

{"Evidence provided:" if evidence else ""}
{json.dumps(evidence, indent=2) if evidence else ""}

Generate:
1. Audit scope and objectives
2. Methodology
3. Findings summary
4. Evidence documentation
5. Compliance status
6. Recommendations
7. Management response section (template)"""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "audit_documentation": response.content,
                "audit_type": audit_type,
                "type": "audit",
            },
            usage=usage,
            output_messages=["Audit documentation generated"],
        )

    async def _security_review(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Review security aspects."""
        params = step.params
        artifact = params.get("artifact", "")
        artifact_type = params.get("type", "code")
        focus_areas = params.get("focus_areas", [])

        prompt = f"""Perform a security review on the following {artifact_type}:

{artifact}

{"Focus areas: " + ', '.join(focus_areas) if focus_areas else ""}

Review for:
1. Authentication and authorization
2. Input validation
3. Data encryption
4. Injection vulnerabilities
5. Secure communication
6. Error handling
7. Logging and monitoring

Provide:
- Security rating
- Vulnerabilities found
- OWASP Top 10 mapping
- Remediation recommendations"""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "security_review": response.content,
                "type": "security_review",
            },
            usage=usage,
            output_messages=["Security review completed"],
        )

    async def _data_classification(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Classify data sensitivity."""
        params = step.params
        data_description = params.get("data", "")
        data_samples = params.get("samples", [])

        prompt = f"""Classify the sensitivity of the following data:

Description:
{data_description}

{"Sample data:" if data_samples else ""}
{json.dumps(data_samples, indent=2) if data_samples else ""}

Classify according to:
1. Sensitivity level (Public/Internal/Confidential/Restricted)
2. PII identification
3. Special category data (health, biometric, etc.)
4. Business criticality
5. Regulatory implications

Provide:
- Classification result
- Handling requirements
- Retention requirements
- Access restrictions"""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "data_classification": response.content,
                "type": "data_classification",
            },
            usage=usage,
            output_messages=["Data classification completed"],
        )

    async def _privacy_assessment(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Perform privacy impact assessment."""
        params = step.params
        processing_activity = params.get("activity", "")
        data_subjects = params.get("data_subjects", [])
        purpose = params.get("purpose", "")

        prompt = f"""Perform a Privacy Impact Assessment (PIA) for:

Processing Activity:
{processing_activity}

Purpose: {purpose}
{"Data subjects: " + ', '.join(data_subjects) if data_subjects else ""}

Assess:
1. Necessity and proportionality
2. Risks to data subjects
3. Safeguards and mitigations
4. Legal basis for processing
5. Data subject rights
6. Data retention

Provide PIA report with risk rating and recommendations."""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "pia_report": response.content,
                "type": "privacy_assessment",
            },
            usage=usage,
            output_messages=["Privacy assessment completed"],
        )

    async def _risk_assessment(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Perform risk assessment."""
        params = step.params
        subject = params.get("subject", "")
        threats = params.get("threats", [])
        assets = params.get("assets", [])

        prompt = f"""Perform a risk assessment for:

Subject:
{subject}

{"Known threats: " + json.dumps(threats) if threats else ""}
{"Assets: " + json.dumps(assets) if assets else ""}

Assess:
1. Threat identification
2. Vulnerability analysis
3. Impact assessment
4. Likelihood assessment
5. Risk rating (Low/Medium/High/Critical)
6. Risk treatment options

Provide risk register with mitigation recommendations."""

        messages = [
            SystemMessage(content=COMPLIANCE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "risk_assessment": response.content,
                "type": "risk_assessment",
            },
            usage=usage,
            output_messages=["Risk assessment completed"],
        )

    def _extract_usage(self, response) -> TokenUsage:
        """Extract token usage from LLM response."""
        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
            usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return usage
