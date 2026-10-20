#!/usr/bin/env python3
"""Incremental, review-first localization for a project-owned String Catalog."""

import argparse
import copy
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.request
from urllib.parse import urlsplit


PLACEHOLDER = re.compile(r"%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?(?:lld|ld|d|i|u|o|x|X|f|F|e|E|g|G|c|s|p|@|%)")
APPROVED_MODELS = {"translategemma-27b-it", "translategemma-27b-it-4bit"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("Service redirects are blocked; configure the intended local endpoint directly")


def read_json(path, default=None):
    if not path.exists():
        if default is not None:
            return copy.deepcopy(default)
        raise ValueError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response key")
        result[key] = value
    return result


def load_project(config_path):
    config_path = config_path.resolve()
    config = read_json(config_path)
    required = {"source", "catalog", "cache", "sourceLocale", "locales", "localeNames", "model"}
    if required - config.keys():
        raise ValueError(f"Missing configuration fields: {sorted(required - config.keys())}")
    if config["model"] not in APPROVED_MODELS:
        raise ValueError("This TranslateGemma profile accepts only an approved 27B identifier")
    locales = config["locales"]
    if not isinstance(locales, list) or not all(isinstance(x, str) and x for x in locales) or len(locales) != len(set(locales)) or "en" not in locales:
        raise ValueError("locales must be unique and include en")
    if config["sourceLocale"] != "en" and config["sourceLocale"] in locales:
        raise ValueError("Keep the original source locale separate from target locales")
    if set(locales) - set(config["localeNames"]):
        raise ValueError("Each target locale needs a human-readable name")
    terms = config.get("protectedTerms", [])
    if not isinstance(terms, list) or not all(isinstance(term, str) and term for term in terms):
        raise ValueError("protectedTerms must be a list of nonempty strings")
    base = config_path.parent
    paths = {key: (base / config[key]).resolve() for key in ("source", "catalog", "cache")}
    if len(set(paths.values())) != 3:
        raise ValueError("Source, catalog, and cache must use separate files")
    sources = read_json(paths["source"])
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Source registry must contain stable keys")
    for key, item in sources.items():
        if not isinstance(item, dict) or not isinstance(item.get("source"), str) or not item["source"]:
            raise ValueError(f"Missing source text: {key}")
        if not isinstance(item.get("context"), str) or not item["context"].strip():
            raise ValueError(f"Missing translator context: {key}")
    return config, paths, sources


def refresh_cache(cache, sources, model, protected_terms=(), source_locale="zh-Hans"):
    if cache.get("model", model) != model:
        raise ValueError("Cache model differs from project model; use a separate cache")
    cache["model"] = model
    entries = cache.setdefault("entries", {})
    policy_hash = fingerprint(json.dumps(sorted(protected_terms), ensure_ascii=False))
    for key, item in sources.items():
        source_hash = fingerprint(item["source"])
        context_hash = fingerprint(item["context"])
        old = entries.get(key, {})
        if (old.get("sourceHash"), old.get("contextHash"), old.get("policyHash")) != (source_hash, context_hash, policy_hash):
            entries[key] = {"sourceHash": source_hash, "contextHash": context_hash,
                            "policyHash": policy_hash, "translations": {},
                            "exportedValues": old.get("exportedValues", {})}
        if source_locale == "en":
            entries[key]["translations"]["en"] = {"value": item["source"], "provenance": "original source"}
    return cache


def pending_pairs(config, sources, cache):
    pairs = []
    for key in sources:
        translations = cache["entries"][key]["translations"]
        if "en" not in translations:
            pairs.append((key, "en"))
        for locale in config["locales"]:
            if locale != "en" and locale not in translations:
                pairs.append((key, locale))
    return pairs


def placeholders_match(source, target):
    return PLACEHOLDER.findall(source) == PLACEHOLDER.findall(target)


def request_translation(config, key, source, context, source_name, locale, endpoint, api_key):
    target_name = config["localeNames"][locale]
    terms = config.get("protectedTerms", [])
    prompt = (
        "<start_of_turn>user\n"
        f"Translate this app-interface string from {source_name} to {target_name}. "
        "The context explains where it appears; do not translate the context. "
        "Return only one JSON object with exactly the same key. Preserve format placeholders "
        "such as %@, %1$@, and %% exactly and in order. "
        f"Keep these terms unchanged: {json.dumps(terms, ensure_ascii=False)}. "
        f"Context: {context}\n"
        f"Input: {json.dumps({key: source}, ensure_ascii=False)}"
        "<end_of_turn>\n<start_of_turn>model\n"
    )
    payload = json.dumps({
        "model": config["model"], "prompt": prompt,
        "temperature": 0.1, "max_tokens": 512, "stop": ["<end_of_turn>"],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint.rstrip("/") + "/v1/completions", payload, headers)
    # Local services should not be silently redirected through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=120) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("model") != config["model"]:
        raise ValueError("Service response model does not match the configured 27B model")
    choices = result.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("Service response must contain one completion")
    if choices[0].get("finish_reason") == "length":
        raise ValueError("Service truncated the translation; no result was accepted")
    raw = choices[0].get("text")
    if not isinstance(raw, str):
        raise ValueError("Service completion text is missing")
    raw = raw.strip()
    translated = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(translated, dict) or set(translated) != {key}:
        raise ValueError("Response identifiers do not match the requested key")
    value = translated[key]
    if not isinstance(value, str) or not value.strip() or not placeholders_match(source, value):
        raise ValueError("Empty translation or format placeholder mismatch")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError("Control character in translation")
    if any(value.count(term) != source.count(term) for term in terms if term in source):
        raise ValueError("A protected term changed")
    language_text = PLACEHOLDER.sub("", source)
    for term in terms:
        language_text = language_text.replace(term, "")
    if value == source and any(ch.isalpha() for ch in language_text):
        raise ValueError("Target language copied the source")
    if any(mark in value.lower() for mark in ("<start_of_turn>", "<end_of_turn>", "as a language model")):
        raise ValueError("Model artifact in translation")
    return value


def command_plan(config, sources, cache):
    pending = pending_pairs(config, sources, cache)
    print(json.dumps({"keys": len(sources), "targetLocales": len(config["locales"]),
                      "pending": len(pending), "pairs": [{"key": k, "locale": l} for k, l in pending]},
                     ensure_ascii=False, indent=2))


def command_translate(config, paths, sources, cache, limit):
    endpoint = os.environ.get("LOCALIZE_BASE_URL", "")
    api_key = os.environ.get("LOCALIZE_API_KEY", "")
    if not endpoint:
        raise ValueError("Set LOCALIZE_BASE_URL for your local 27B service")
    parsed = urlsplit(endpoint)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        local_host = address.is_private or address.is_loopback
    except ValueError:
        local_host = parsed.hostname in {"localhost", "localhost.localdomain"}
    if parsed.scheme not in {"http", "https"} or not local_host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LOCALIZE_BASE_URL must be a local/private IP or localhost HTTP(S) endpoint without URL credentials")
    if os.environ.get("LOCALIZE_MODEL_ID", config["model"]) != config["model"]:
        raise ValueError("LOCALIZE_MODEL_ID must exactly match the configured model")
    lock_path = paths["cache"].with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cache = refresh_cache(read_json(paths["cache"], {"model": config["model"], "entries": {}}), sources, config["model"], config.get("protectedTerms", []), config["sourceLocale"])
        write_json(paths["cache"], cache)
        done = 0
        # English must exist before any other target is requested.
        for locale in ["en"] + [code for code in config["locales"] if code != "en"]:
            if locale != "en" and any("en" not in cache["entries"][k]["translations"] for k in sources):
                break
            for key, item in sources.items():
                entry = cache["entries"][key]
                if locale in entry["translations"]:
                    continue
                source = item["source"] if locale == "en" else entry["translations"]["en"]["value"]
                source_name = config.get("sourceLanguageName", config["sourceLocale"]) if locale == "en" else "English"
                value = request_translation(config, key, source, item["context"], source_name,
                                            locale, endpoint, api_key)
                entry["translations"][locale] = {"value": value, "model": config["model"]}
                write_json(paths["cache"], cache)
                done += 1
                print(f"Saved {key} / {locale}", flush=True)
                if limit and done >= limit:
                    print(f"Stopped at requested limit: {done}")
                    return
        print(f"Saved {done} translations; {len(pending_pairs(config, sources, cache))} pairs remain")


def command_export(config, paths, sources, cache):
    catalog = read_json(paths["catalog"], {"sourceLanguage": "en", "strings": {}, "version": "1.0"})
    if catalog.get("sourceLanguage") != "en":
        raise ValueError("This profile requires an English-source String Catalog")
    errors = []
    for key, item in sources.items():
        cached_entry = cache["entries"][key]
        translated = cached_entry["translations"]
        if "en" not in translated:
            errors.append(f"{key}: English source is pending")
            continue
        entry = catalog.setdefault("strings", {}).setdefault(key, {"extractionState": "manual"})
        locs = entry.setdefault("localizations", {})
        values = {config["sourceLocale"]: item["source"]}
        values.update({locale: data["value"] for locale, data in translated.items()})
        for locale, value in values.items():
            old = locs.get(locale, {})
            if "variations" in old or "substitutions" in old:
                errors.append(f"{key}/{locale}: plural or substitution data needs manual handling")
                continue
            old_unit = old.get("stringUnit", {})
            previous_value = cached_entry.get("exportedValues", {}).get(locale)
            if old_unit.get("value") not in (None, value, previous_value):
                errors.append(f"{key}/{locale}: existing catalog value differs; preserved")
                continue
            unchanged_reviewed = old_unit.get("value") == value and old_unit.get("state") == "translated"
            state = "translated" if locale == config["sourceLocale"] or unchanged_reviewed else "needs_review"
            locs[locale] = {**old, "stringUnit": {**old_unit, "value": value, "state": state}}
            cached_entry.setdefault("exportedValues", {})[locale] = value
    if errors:
        raise ValueError("Catalog not written:\n" + "\n".join(errors))
    write_json(paths["catalog"], catalog)
    write_json(paths["cache"], cache)
    print(f"Exported {len(sources)} source keys to {paths['catalog']}")


def command_verify(config, paths, sources, cache):
    catalog = read_json(paths["catalog"])
    errors, review = [], 0
    for key, item in sources.items():
        entry = cache["entries"].get(key, {})
        if entry.get("sourceHash") != fingerprint(item["source"]):
            errors.append(f"{key}: stale source fingerprint")
        locs = catalog.get("strings", {}).get(key, {}).get("localizations", {})
        expected = set(config["locales"]) | {config["sourceLocale"]}
        if expected - set(locs):
            errors.append(f"{key}: missing catalog locales {sorted(expected - set(locs))}")
        english = locs.get("en", {}).get("stringUnit", {}).get("value")
        if locs.get(config["sourceLocale"], {}).get("stringUnit", {}).get("value") != item["source"]:
            errors.append(f"{key}/{config['sourceLocale']}: catalog/source mismatch")
        if not english:
            errors.append(f"{key}: missing English source")
            continue
        if not placeholders_match(item["source"], english):
            errors.append(f"{key}/en: placeholder mismatch")
        for locale in expected:
            unit_ = locs.get(locale, {}).get("stringUnit", {})
            value = unit_.get("value")
            if not value:
                continue
            if not placeholders_match(english, value):
                errors.append(f"{key}/{locale}: placeholder mismatch")
            if unit_.get("state") == "needs_review":
                review += 1
            elif unit_.get("state") != "translated":
                errors.append(f"{key}/{locale}: unknown review state")
            if locale != config["sourceLocale"]:
                cached = entry.get("translations", {}).get(locale, {})
                if cached.get("value") != value or cached.get("model") != config["model"]:
                    errors.append(f"{key}/{locale}: catalog/cache/model mismatch")
    if errors:
        raise ValueError("\n".join(errors))
    print(f"Verified {len(sources)} keys; {review} locale values still need review")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("project.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="List only missing or changed key-locale pairs")
    translate = sub.add_parser("translate", help="Call the configured local 27B service")
    translate.add_argument("--limit", type=int, default=0, help="Stop after this many accepted rows")
    sub.add_parser("export", help="Merge accepted values into an .xcstrings catalog")
    sub.add_parser("verify", help="Check catalog, cache, and review states")
    for command_parser in sub.choices.values():
        command_parser.add_argument("--keys", nargs="+", help="Limit work to these stable keys")
    args = parser.parse_args()
    try:
        config, paths, sources = load_project(args.config)
        if args.keys:
            unknown = set(args.keys) - sources.keys()
            if unknown:
                raise ValueError(f"Unknown source keys: {sorted(unknown)}")
            sources = {key: value for key, value in sources.items() if key in args.keys}
        cache = refresh_cache(read_json(paths["cache"], {"model": config["model"], "entries": {}}), sources, config["model"], config.get("protectedTerms", []), config["sourceLocale"])
        if args.command == "plan":
            command_plan(config, sources, cache)
        elif args.command == "translate":
            if args.limit < 0:
                raise ValueError("--limit cannot be negative")
            command_translate(config, paths, sources, cache, args.limit)
        elif args.command == "export":
            paths["cache"].parent.mkdir(parents=True, exist_ok=True)
            with paths["cache"].with_suffix(".lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                cache = refresh_cache(read_json(paths["cache"], {"model": config["model"], "entries": {}}), sources, config["model"], config.get("protectedTerms", []), config["sourceLocale"])
                command_export(config, paths, sources, cache)
        elif args.command == "verify":
            command_verify(config, paths, sources, cache)
    except (ValueError, KeyError, OSError, fcntl.error, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
