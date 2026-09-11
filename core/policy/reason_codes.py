"""DE-003 §7: the policy-authored reason-code namespace. Every Gate and
Rule reason code a policy author writes must be a `POLICY:` code matching
this format -- validated at policy-activation time, never at evaluation
time, so a malformed or colliding code can never reach a live decision.
"""

import re

from core.decision.enums import EngineReasonCode

POLICY_REASON_CODE_PATTERN = re.compile(r"^POLICY:[A-Z][A-Z0-9_]{1,62}$")

_ENGINE_CODE_VALUES = frozenset(code.value for code in EngineReasonCode)


def is_valid_policy_reason_code(code: str) -> bool:
    """True iff `code` matches the POLICY: format and does not collide with
    any ENGINE: value (DE-003 §7's two required checks)."""
    if code in _ENGINE_CODE_VALUES:
        return False
    return bool(POLICY_REASON_CODE_PATTERN.match(code))
