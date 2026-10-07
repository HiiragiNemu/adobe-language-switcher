"""Transform string values only; preserve keys, ordering, BOM and line endings."""
import json
import re
from collections import Counter


class SwitchError(RuntimeError):
    pass


LOCALE = re.compile(r"^[a-z]{2}_[A-Z]{2}$")
PREF = re.compile(r"^(ApplicationLanguage\t)([^\t\r\n]+)(\t[^\r\n]+)$")
TOKENS = re.compile(r"@\d+|\{[A-Za-z_0-9]+\}|%(?:\d+\$)?[sdif]")


def locale(value):
    if not LOCALE.fullmatch(value):
        raise SwitchError(f"Invalid locale: {value!r}")
    return value


def decode(data):
    try:
        return data.decode("utf-8-sig"), data.startswith(b"\xef\xbb\xbf")
    except UnicodeError as exc:
        raise SwitchError("Expected a UTF-8 text resource") from exc


def encode(text, bom):
    return text.encode("utf-8-sig" if bom else "utf-8")


def preference(data, wanted=None):
    text, bom = decode(data)
    lines = text.splitlines(keepends=True)
    found = [(i, PREF.fullmatch(line.rstrip('\r\n'))) for i, line in enumerate(lines)]
    found = [(i, match) for i, match in found if match is not None]
    if len(found) != 1:
        raise SwitchError("Expected exactly one ApplicationLanguage preference; launch the app once first")
    index, match = found[0]
    old = locale(match.group(2))
    if wanted is None:
        return old
    locale(wanted)
    lines[index] = match[1] + wanted + match[3] + lines[index][match.end():]
    return encode(''.join(lines), bom)


def placeholders(value):
    return Counter(TOKENS.findall(value))


def map_dictionary(target, source):
    original, bom = decode(target)
    translated, _ = decode(source)
    def entries(text):
        result = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            if not (line.startswith('"$$$') and line.endswith('"') and '=' in line):
                raise SwitchError("Unknown dictionary format; resource preserved")
            key, value = line[1:-1].split('=', 1)
            if key in result:
                raise SwitchError(f"Duplicate dictionary key: {key}")
            result[key] = value
        return result
    before, after = entries(original), entries(translated)
    if not before or not before.keys() & after.keys():
        raise SwitchError("Dictionaries have no shared keys")
    stats = {"keys": len(before), "changed": 0, "missing": 0, "placeholder_mismatch": 0}
    def replace(line):
        body = line.rstrip('\r\n')
        ending = line[len(body):]
        if not body.strip():
            return line
        key, value = body[1:-1].split('=', 1)
        if key not in after:
            stats['missing'] += 1
            return line
        new = after[key]
        if placeholders(value) != placeholders(new):
            stats['placeholder_mismatch'] += 1
            return line
        stats['changed'] += value != new
        return f'"{key}={new}"' + ending
    output = ''.join(replace(line) for line in original.splitlines(keepends=True))
    return encode(output, bom), stats


def map_json(target, source):
    a, bom = decode(target)
    b, _ = decode(source)
    def unique(pairs):
        d = {}
        for key, value in pairs:
            if key in d:
                raise SwitchError(f"Duplicate JSON key: {key}")
            d[key] = value
        return d
    try:
        old, new = (json.loads(x, object_pairs_hook=unique) for x in (a, b))
    except (ValueError, TypeError) as exc:
        raise SwitchError("Invalid JSON language resource") from exc
    stats = {"keys": 0, "changed": 0, "missing": 0, "placeholder_mismatch": 0}
    def merge(x, y):
        if isinstance(x, dict):
            if not isinstance(y, dict):
                raise SwitchError("JSON structure mismatch")
            out = {}
            for key, value in x.items():
                if key not in y:
                    stats['missing'] += 1
                    out[key] = value
                else:
                    out[key] = merge(value, y[key])
            return out
        if isinstance(x, list):
            if not isinstance(y, list) or len(x) != len(y):
                raise SwitchError("JSON array structure mismatch")
            return [merge(v, w) for v, w in zip(x, y)]
        if type(x) is not type(y):
            raise SwitchError("JSON value type mismatch")
        if isinstance(x, str):
            stats['keys'] += 1
            if placeholders(x) != placeholders(y):
                stats['placeholder_mismatch'] += 1
                return x
            stats['changed'] += x != y
            return y
        return x
    merged = merge(old, new)
    if merged == old:
        return target, stats
    ending = '\r\n' if '\r\n' in a else '\n'
    text = json.dumps(merged, ensure_ascii=False, indent=2).replace('\n', ending)
    if a.endswith('\n'):
        text += ending
    return encode(text, bom), stats
