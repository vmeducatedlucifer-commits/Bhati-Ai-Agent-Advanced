"""Real-time security guidance and vulnerability scanner matching Anthropic security-guidance plugin."""

from __future__ import annotations

import re
from typing import NamedTuple


class SecurityFinding(NamedTuple):
    rule: str
    severity: str
    message: str
    line: int | None = None


SECRET_PATTERNS = [
    (r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}", "GitHub Token"),
    (r"sk-[a-zA-Z0-9]{20,T3BlbkFJ[a-zA-Z0-9]{20,}", "OpenAI Secret Key"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private Key block"),
    (r"xox[baprs]-[0-9a-zA-Z]{10,48}", "Slack Token"),
    (r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{30,}", "Hardcoded Bearer Token"),
]

CODE_VULNERABILITY_PATTERNS = [
    (r"(?<!safe_)load\s*\([^)]*Loader\s*=\s*(?:yaml\.)?(?:UnsafeLoader|Loader)", "CRITICAL", "Unsafe YAML deserialization: allows arbitrary code execution. Use `yaml.safe_load()` instead."),
    (r"pickle\s*\.\s*loads?\s*\(", "CRITICAL", "Unsafe Pickle deserialization: allows arbitrary code execution. Use JSON or schema validation (pydantic) instead."),
    (r"torch\s*\.\s*load\s*\([^)]*weights_only\s*=\s*False", "HIGH", "torch.load with weights_only=False unpickles arbitrary code. Set `weights_only=True`."),
    (r"child_process\s*\.\s*exec\s*\(", "HIGH", "child_process.exec() passes strings to shell. Use `child_process.execFile()` with an arguments array to avoid shell injection."),
    (r"new\s+Function\s*\([^)]*[\$\+]", "CRITICAL", "new Function() with string interpolation is a code injection vulnerability."),
    (r"eval\s*\([^)]*[\$\+]", "CRITICAL", "eval() with concatenated user input allows arbitrary JavaScript/Python execution."),
    (r"except\s*:\s*pass\b|catch\s*\([^)]*\)\s*\{\s*\}", "HIGH", "Silent failure: empty catch / except: pass swallows fatal errors. Log error or handle explicitly."),
]


def scan_diff_for_security_issues(filename: str, content: str) -> list[SecurityFinding]:
    """Scan newly written or edited file content for security vulnerabilities."""
    findings: list[SecurityFinding] = []

    # Check for hardcoded secrets
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, content):
            findings.append(
                SecurityFinding(
                    rule="hardcoded_secret",
                    severity="CRITICAL",
                    message=f"Possible hardcoded {label} detected in {filename}. Never commit plaintext credentials!",
                )
            )

    # Check for code vulnerability patterns
    lines = content.splitlines()
    for pattern, severity, msg in CODE_VULNERABILITY_PATTERNS:
        for idx, line in enumerate(lines, 1):
            if re.search(pattern, line):
                findings.append(
                    SecurityFinding(
                        rule="code_vulnerability",
                        severity=severity,
                        message=f"{msg} (Found in {filename}:{idx})",
                        line=idx,
                    )
                )

    return findings
