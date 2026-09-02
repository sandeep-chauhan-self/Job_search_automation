import os
import yaml

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")

def _load_yaml(filename: str):
    filepath = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def load_config() -> dict:
    return _load_yaml("config.yaml")

def load_secrets() -> dict:
    return _load_yaml("secrets.yaml")

def load_profile() -> dict:
    return _load_yaml("profile.yaml")

def load_search_filters() -> dict:
    return _load_yaml("search_filters.yaml")

def load_answers() -> list:
    """Returns a list of dictionaries from answers.yaml"""
    res = _load_yaml("answers.yaml")
    if isinstance(res, dict) and not res:
        return []
    return res
