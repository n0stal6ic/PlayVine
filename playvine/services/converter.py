"""
PlayVine service script converter.

Converts old service scripts from other DRM downloaders into PlayVine-native
folder-based services.

Usage:
    python playvine/services/converter.py [SOURCE] [--from FLAVOR] [--to NAME]

If you omit SOURCE or --from, the script drops into an interactive prompt
flow.

Supported source flavors (v1):
    vt, vt-pr        single-file vinetrimmer / vt-pr scripts

Coming later (v2):
    unshackle, devine    folder-style scripts; their Track and Title shapes
                         diverge from PlayVine enough that we want to add
                         them carefully rather than ship a converter that
                         silently produces broken code.

The converter is deliberately conservative. If it sees an import it knows
it cannot satisfy (Netflix's MSL module, Disney+'s BamSDK vendor, Hulu's
pyhulu, etc.), it refuses to convert and tells you why instead of writing
broken output. You then port that script manually.

Output:
    A new folder under playvine/services/<NAME>/ containing the converted
    script and a stub config.yaml. The original source file is left where
    it is.

This file is not a service - the service loader ignores files that live
directly in playvine/services/ (it only walks subfolders).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Optional


SUPPORTED_FLAVORS = {"vt", "vt-pr", "vinetrimmer"}
UNSUPPORTED_FLAVORS = {"unshackle", "devine"}


# VT / VT-PR import path mapping. Order matters: more specific prefixes
# must come before more general ones, because the rewriter takes the
# first prefix that matches.
VT_IMPORT_MAP: list[tuple[str, str]] = [
    ("vinetrimmer.services.BaseService", "playvine.services.BaseService"),
    ("vinetrimmer.objects",              "playvine.objects"),
    ("vinetrimmer.utils.collections",    "playvine.utils.collections"),
    ("vinetrimmer.utils.io",             "playvine.utils.io"),
    ("vinetrimmer.utils.xml",            "playvine.utils.xml"),
    ("vinetrimmer.utils.subprocess",     "playvine.utils.subprocess"),
    ("vinetrimmer.utils.widevine",       "playvine.utils.widevine"),
    ("vinetrimmer.utils",                "playvine.utils"),
    ("vinetrimmer.vendor.pymp4.parser",  "playvine.vendor.pymp4.parser"),
    ("vinetrimmer.vendor.pymp4",         "playvine.vendor.pymp4"),
    ("vinetrimmer.config",               "playvine.config"),
    ("vinetrimmer.constants",            "playvine.constants"),
]


# Imports that we know we cannot safely satisfy on the PlayVine side
# (modules that PlayVine does not ship, or that ship but crash on
# import, and that the user would have to port across by hand).
# Hitting any of these aborts the conversion.
#
# Matched case-insensitively against the dotted module path.
VT_REJECT_IMPORTS: list[tuple[str, str]] = [
    ("vinetrimmer.utils.MSL",
     "Netflix MSL (Media Session Layer) protocol is not ported to PlayVine"),
    ("vinetrimmer.utils.gen_esn",
     "Netflix ESN generator helper is not ported to PlayVine"),
    ("vinetrimmer.utils.widevine.device",
     "LocalDevice depends on the widevine protobuf module which is incompatible with the active protobuf runtime in PlayVine. "
     "Use BaseService._is_playready() for PR vs WV checks instead, and remove direct LocalDevice usage by hand"),
    ("vinetrimmer.utils.widevine.protos",
     "widevine protobuf module is incompatible with the active protobuf runtime in PlayVine"),
    ("vinetrimmer.vendor.BamSDK",
     "Disney+ BamSDK vendor is not ported to PlayVine"),
    ("vinetrimmer.vendor.pyhulu",
     "Hulu pyhulu vendor is not ported to PlayVine"),
    ("vinetrimmer.vendor.h2",
     "vendored h2 is not ported to PlayVine"),
    ("vinetrimmer.vendor.hyper",
     "vendored hyper is not ported to PlayVine"),
]


class ConversionRejected(Exception):
    """Raised when a script cannot be safely auto-converted."""


# Detection

def detect_flavor(source_text: str) -> Optional[str]:
    """Guess the source flavor from imports present in the file."""
    if "from vinetrimmer" in source_text or "import vinetrimmer" in source_text:
        return "vt"
    if "from unshackle" in source_text or "import unshackle" in source_text:
        return "unshackle"
    if "from devine" in source_text or "import devine" in source_text:
        return "devine"
    return None


# Safety check

def find_unsafe_imports(tree: ast.AST, flavor: str) -> list[str]:
    """Return human-readable reasons the script cannot be converted, or []."""
    reasons: list[str] = []
    if flavor in ("vt", "vt-pr", "vinetrimmer"):
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
            elif isinstance(node, ast.Import):
                mods.extend(n.name for n in node.names)
            for mod in mods:
                mod_lower = mod.lower()
                for bad_prefix, why in VT_REJECT_IMPORTS:
                    bad_lower = bad_prefix.lower()
                    if mod_lower == bad_lower or mod_lower.startswith(bad_lower + "."):
                        reasons.append(f"{mod}: {why}")
                        break
    return reasons


def _rewrite_module_path(path: str, mapping: list[tuple[str, str]]) -> Optional[str]:
    """
    Apply the prefix mapping to a dotted module path.

    Case-insensitive: real-world VT scripts sometimes import as
    `vinetrimmer.utils.Widevine` (capital W) and sometimes as
    `vinetrimmer.utils.widevine`. We match either way and emit the
    canonical lowercase target from the map, preserving the original
    tail's case so things like `.parser` stay as written.
    """
    lower = path.lower()
    for old, new in mapping:
        old_lower = old.lower()
        if lower == old_lower:
            return new
        if lower.startswith(old_lower + "."):
            return new + path[len(old):]
    return None


# Import rewrite

def rewrite_imports(tree: ast.AST, flavor: str) -> None:
    """Rewrite import nodes in place using the per-flavor mapping."""
    if flavor in ("vt", "vt-pr", "vinetrimmer"):
        mapping = VT_IMPORT_MAP
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                rewritten = _rewrite_module_path(node.module, mapping)
                if rewritten is not None:
                    node.module = rewritten
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    rewritten = _rewrite_module_path(alias.name, mapping)
                    if rewritten is not None:
                        alias.name = rewritten


# Main convert function

def convert(source_path: Path, out_folder: Path, flavor: Optional[str]) -> dict:
    """
    Run the full conversion pipeline. Returns a report dict on success,
    raises ConversionRejected if the script cannot be safely auto-converted.
    """
    if source_path.is_dir():
        raise ConversionRejected(
            "folder-style sources are not yet supported (unshackle, devine). "
            "Pass a single .py vinetrimmer / vt-pr file instead."
        )
    if not source_path.is_file():
        raise ConversionRejected(f"not a file: {source_path}")

    source_text = source_path.read_text(encoding="utf-8")

    if flavor is None:
        flavor = detect_flavor(source_text)
    if flavor is None:
        raise ConversionRejected(
            "could not detect source flavor, please pass --from vt or --from vt-pr"
        )
    flavor = flavor.lower()
    if flavor in UNSUPPORTED_FLAVORS:
        raise ConversionRejected(
            f"flavor '{flavor}' is not supported by the v1 converter. "
            f"Group B (unshackle, devine) will be added in a later version."
        )
    if flavor not in SUPPORTED_FLAVORS:
        raise ConversionRejected(f"unknown source flavor: {flavor!r}")

    try:
        tree = ast.parse(source_text, filename=str(source_path))
    except SyntaxError as e:
        raise ConversionRejected(f"source file has a Python syntax error: {e}")

    unsafe = find_unsafe_imports(tree, flavor)
    if unsafe:
        raise ConversionRejected(
            "script uses modules the converter cannot translate:\n  * "
            + "\n  * ".join(unsafe)
            + "\n\nThis script needs to be ported by hand."
        )

    rewrite_imports(tree, flavor)
    converted = ast.unparse(tree)

    # Preserve the source comment header by walking back from line 1
    # of the original until we hit a non-comment/non-blank line, and
    # prepending those lines (ast loses pure comments).
    header_lines: list[str] = []
    for raw in source_text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#") or stripped == "":
            header_lines.append(raw)
            continue
        break
    if header_lines:
        converted = "\n".join(header_lines).rstrip() + "\n\n" + converted

    # Write output
    out_folder.mkdir(parents=True, exist_ok=True)
    script_name = source_path.stem.lower() + ".py"
    out_script = out_folder / script_name
    out_script.write_text(converted + "\n", encoding="utf-8")

    cfg_path = out_folder / "config.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(
            "# Per-service config for "
            + source_path.stem
            + ".\n"
            "# Reachable as self.config inside the service class at runtime.\n"
            "#\n"
            "# This was generated by the PlayVine converter from a "
            + flavor
            + " script.\n"
            "# Fill in any keys your service code reads (endpoints, region maps, etc).\n"
            "# Credentials should go in playvine/playvine.yml, not here.\n",
            encoding="utf-8",
        )

    return {
        "source": str(source_path),
        "flavor": flavor,
        "out_script": str(out_script),
        "out_config": str(cfg_path),
        "imports_rewritten": _count_rewritten_imports(source_text, converted),
    }


def _count_rewritten_imports(before: str, after: str) -> int:
    """Rough count of how many lines changed for the user's report."""
    before_lines = {line for line in before.splitlines() if "vinetrimmer" in line}
    after_lines = {line for line in after.splitlines() if "playvine" in line and "import" in line}
    return len(before_lines)


# Entry point

def _prompt(label: str, default: Optional[str] = None) -> str:
    """Tiny prompt helper that accepts a default value."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw or (default or "")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="converter.py",
        description="Convert old service scripts (VT, VT-PR) to PlayVine format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", nargs="?", help="Path to a source .py script.")
    parser.add_argument(
        "--from", dest="flavor",
        choices=["vt", "vt-pr", "vinetrimmer", "unshackle", "devine"],
        help="Source flavor. Auto-detected from imports if omitted.",
    )
    parser.add_argument(
        "--to", dest="out_name",
        help="Output folder name under playvine/services/. Defaults to the source filename without extension.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite the output folder if it already exists.",
    )
    args = parser.parse_args(argv)

    # Source path: arg or prompt
    source = args.source or _prompt("Path to source script")
    if not source:
        print("no source provided, aborting", file=sys.stderr)
        return 2
    source_path = Path(source).expanduser().resolve()

    # Flavor: arg or detect or prompt
    flavor = args.flavor
    if not flavor and source_path.is_file():
        guess = detect_flavor(source_path.read_text(encoding="utf-8"))
        if guess:
            ans = _prompt(f"Detected flavor '{guess}', use it? (Y/n)", "Y").lower()
            if ans in ("", "y", "yes"):
                flavor = guess
    if not flavor:
        flavor = _prompt("Source flavor (vt, vt-pr, unshackle, devine)").lower() or None

    # Output name: arg or prompt
    default_name = source_path.stem.lower() if source_path.is_file() else "newservice"
    out_name = args.out_name or _prompt("Output folder name under services/", default_name)

    services_root = Path(__file__).resolve().parent
    out_folder = services_root / out_name

    # Refuse to clobber an existing populated folder unless --force
    if out_folder.exists() and any(out_folder.iterdir()) and not args.force:
        ans = _prompt(f"Folder '{out_folder.name}' exists and isn't empty. Overwrite? (y/N)", "N").lower()
        if ans not in ("y", "yes"):
            print("aborted by user", file=sys.stderr)
            return 1

    try:
        report = convert(source_path, out_folder, flavor)
    except ConversionRejected as e:
        print()
        print(f"REJECTED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"INTERNAL ERROR: {e}", file=sys.stderr)
        return 2

    print()
    print("conversion succeeded")
    print(f"  source       : {report['source']}")
    print(f"  flavor       : {report['flavor']}")
    print(f"  script out   : {report['out_script']}")
    print(f"  config stub  : {report['out_config']}")
    print(f"  imports seen : {report['imports_rewritten']}")
    print()
    print("Next steps:")
    print("  * open the converted script and confirm the import lines look right")
    print("  * fill in config.yaml with anything the script reads via self.config")
    print("  * test with: uv run pv dl <ALIAS> <URL> --list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
