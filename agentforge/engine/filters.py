"""Custom Jinja2 filters available in all templates."""
import re

def snake_case(value: str) -> str:
    """SQLAgent → sql_agent"""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    return re.sub(r"[^a-z0-9_]", "_", s)

def pascal_case(value: str) -> str:
    """sql_agent → SqlAgent"""
    return "".join(w.capitalize() for w in value.split("_"))

def upper_snake(value: str) -> str:
    """sql_agent → SQL_AGENT"""
    return snake_case(value).upper()