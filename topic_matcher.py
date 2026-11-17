"""topic_matcher.py
Owner: Dominique
Purpose: Hierarchical topic validation and matching with * and # wildcards.

Topics are dot-separated levels (see docs/PROTOCOL.md):

    brgy.<barangay>.<purok>.<category>     incident
    brgy.<barangay>.advisory               advisory
    report.<report_id>.status              status update
    city.iloilo.escalated.<barangay>       escalation

Wildcards (patterns only, never in published topics):
    *   matches exactly one level
    #   matches zero or more levels; must be the last level
"""

import re

import config

SEPARATOR = "."
SINGLE = "*"
MULTI = "#"

# One topic level: lowercase letters, digits, hyphen, underscore.
# Matches the frontend's topicLevel() normalizer, which emits [a-z0-9-].
_LEVEL_RE = re.compile(r"^[a-z0-9_-]+$")
_NORMALIZE_SPACES = re.compile(r"\s+")
_NORMALIZE_STRIP = re.compile(r"[^a-z0-9_-]")


# ---------------------------------------------------------------- helpers

def split(topic):
    """Split a topic or pattern into its levels."""
    return topic.split(SEPARATOR)


def normalize_level(text):
    """Turn free text like 'Purok 3' into a valid level like 'purok-3'."""
    text = _NORMALIZE_SPACES.sub("-", str(text).strip().lower())
    return _NORMALIZE_STRIP.sub("", text)


def normalize(topic):
    """Lowercase a topic or pattern; wildcards and dots are kept."""
    return topic.strip().lower()


def is_valid_level(level):
    return bool(_LEVEL_RE.match(level))


# ---------------------------------------------------------------- validation

def is_valid_pattern(pattern):
    """True if pattern is a legal SUB/UNSUB pattern.

    Every level is a plain level, '*', or '#'; '#' may only be last.
    """
    if not isinstance(pattern, str) or not pattern:
        return False
    levels = split(pattern)
    for i, level in enumerate(levels):
        if level == MULTI:
            if i != len(levels) - 1:
                return False
        elif level != SINGLE and not is_valid_level(level):
            return False
    return True


def parse_topic(topic):
    """Classify a concrete topic.

    Returns a dict with a 'kind' key ('incident', 'advisory', 'status',
    'escalation') plus the fields named in the topic, or None if the topic
    is not one of the four shapes in docs/PROTOCOL.md.
    """
    if not isinstance(topic, str) or not topic:
        return None
    levels = split(topic)
    if not all(is_valid_level(level) for level in levels):
        return None

    if levels[0] == "brgy":
        if len(levels) == 4 and levels[3] in config.CATEGORIES:
            return {"kind": "incident", "barangay": levels[1],
                    "purok": levels[2], "category": levels[3]}
        if len(levels) == 3 and levels[2] == "advisory":
            return {"kind": "advisory", "barangay": levels[1]}
    elif levels[0] == "report":
        if len(levels) == 3 and levels[2] == "status":
            return {"kind": "status", "report_id": levels[1]}
    elif levels[0] == "city":
        if len(levels) == 4 and levels[1] == "iloilo" and levels[2] == "escalated":
            return {"kind": "escalation", "barangay": levels[3]}
    return None


def is_valid_topic(topic):
    """True if topic is a concrete (wildcard-free) topic of a known shape."""
    return parse_topic(topic) is not None


def is_incident_topic(topic):
    """True if topic is brgy.<barangay>.<purok>.<category> with a known category.

    This is the only topic a resident may REPORT to.
    """
    parsed = parse_topic(topic)
    return parsed is not None and parsed["kind"] == "incident"


# ---------------------------------------------------------------- builders

def incident_topic(barangay, purok, category):
    return SEPARATOR.join(("brgy", barangay, purok, category))


def advisory_topic(barangay):
    return SEPARATOR.join(("brgy", barangay, "advisory"))


def status_topic(report_id):
    return SEPARATOR.join(("report", report_id, "status"))


def escalation_topic(barangay):
    return SEPARATOR.join(("city", "iloilo", "escalated", barangay))


def priority_for(category):
    """URGENT for fire, fight, flood; NORMAL otherwise."""
    return "URGENT" if category in config.URGENT_CATEGORIES else "NORMAL"


# ---------------------------------------------------------------- matching

def matches(pattern, topic):
    """True if a subscription pattern matches a concrete topic.

    >>> matches("brgy.jaro.*.fire", "brgy.jaro.purok-1.fire")
    True
    >>> matches("brgy.jaro.#", "brgy.jaro")
    True
    >>> matches("brgy.*", "brgy.jaro.purok-1.fire")
    False
    """
    p_levels = split(pattern)
    t_levels = split(topic)
    for i, p in enumerate(p_levels):
        if p == MULTI:
            # '#' must be last; it swallows the rest (including nothing).
            return i == len(p_levels) - 1
        if i >= len(t_levels):
            return False
        if p != SINGLE and p != t_levels[i]:
            return False
    return len(p_levels) == len(t_levels)


def any_match(patterns, topic):
    """True if any pattern in an iterable matches topic."""
    return any(matches(p, topic) for p in patterns)
