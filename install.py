#!/usr/bin/env python3
"""One-command installer for the video generation skills.

Downloads the skills, validates an API key against the gateway, discovers which
models the key's group actually exposes, and registers the MCP servers with every
supported host found on this machine.

Usage:
    python3 install.py
    python3 install.py --key sk-...            # skip the interactive prompt
    python3 install.py --host claude           # only configure one host
    python3 install.py --uninstall             # remove what was registered

Standard library only, so it runs on a fresh machine with nothing installed.
"""

from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = "fore4stwOw2/naoshengyun-video-skills"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/heads/main.tar.gz"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.py"
DEFAULT_GATEWAY = "https://token.naoshengyun.com"
SKILLS = ("seedance-video", "wan-video")
ENV_VAR = {"seedance-video": "SEEDANCE_API_KEY", "wan-video": "WAN_API_KEY"}
SERVER_NAME = {"seedance-video": "seedance", "wan-video": "wan"}
MIN_PYTHON = (3, 9)


# ----------------------------------------------------------------- presentation

class Style:
    """ANSI styling, disabled when stdout is not a terminal."""

    enabled = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"

    @classmethod
    def _wrap(cls, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if cls.enabled else text

    @classmethod
    def bold(cls, text: str) -> str:
        return cls._wrap("1", text)

    @classmethod
    def dim(cls, text: str) -> str:
        return cls._wrap("2", text)

    @classmethod
    def green(cls, text: str) -> str:
        return cls._wrap("32", text)

    @classmethod
    def yellow(cls, text: str) -> str:
        return cls._wrap("33", text)

    @classmethod
    def red(cls, text: str) -> str:
        return cls._wrap("31", text)


def step(number: int, total: int, title: str) -> None:
    print(f"\n{Style.bold(f'[{number}/{total}]')} {Style.bold(title)}")


def ok(message: str) -> None:
    print(f"  {Style.green('✓')} {message}")


def warn(message: str) -> None:
    print(f"  {Style.yellow('!')} {message}")


def fail(message: str) -> None:
    print(f"  {Style.red('✗')} {message}")


def die(message: str, hint: str = "") -> "NoReturn":  # type: ignore[valid-type]
    fail(message)
    if hint:
        print(f"\n    {hint}")
    sys.exit(1)


def redact(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text or "")


# ------------------------------------------------------------------------- tls

def build_ssl_context() -> ssl.SSLContext:
    """Verifying context that survives python.org builds with an empty trust store."""
    context = ssl.create_default_context()
    probe = ssl.get_default_verify_paths()
    if (probe.cafile and os.path.exists(probe.cafile)) or (
        probe.capath and os.path.isdir(probe.capath)
    ):
        return context
    candidates: List[str] = []
    try:
        import certifi

        candidates.append(certifi.where())
    except Exception:
        pass
    candidates += [
        "/etc/ssl/cert.pem",
        "/usr/local/etc/openssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/certs/ca-certificates.crt",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                context.load_verify_locations(cafile=path)
                return context
            except Exception:
                continue
    return context


SSL_CONTEXT = build_ssl_context()


# ------------------------------------------------------------------ environment

def check_python() -> None:
    version = sys.version_info
    if version < MIN_PYTHON:
        die(
            f"Python {version.major}.{version.minor} is too old (need 3.9+).",
            "Install a newer Python from https://www.python.org/downloads/ and re-run.",
        )
    ok(f"Python {version.major}.{version.minor}.{version.micro}")


def interpreter_path() -> str:
    """Absolute interpreter path. GUI hosts cannot resolve a bare 'python3'."""
    return os.path.realpath(sys.executable)


# --------------------------------------------------------------------- download

def proxy_hint() -> str:
    """Point at a broken proxy, the usual cause of a refused connection."""
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(name)
        if value:
            return (
                f"A proxy is set ({name}={value}) but did not accept the connection.\n"
                "    Start the proxy, or unset it for this run:\n"
                f"        unset {name}\n"
                "    "
            )
    return "Check the network connection.\n    "


def locate_or_download(target: Path) -> Path:
    """Use the checkout we are running from, otherwise fetch the archive."""
    script = globals().get("__file__") or ""
    # When piped into python, __file__ is "<stdin>" and says nothing about where
    # the skills live, so only trust it when it is a real path on disk.
    if script and Path(script).is_file():
        here = Path(script).resolve().parent
        if all((here / name / "scripts").is_dir() for name in SKILLS):
            ok(f"using the local copy at {here}")
            return here

    target.mkdir(parents=True, exist_ok=True)
    archive = target / "skills.tar.gz"
    print(f"  downloading from github.com/{REPO} ...")
    try:
        request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "skill-installer"})
        with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response, open(
            archive, "wb"
        ) as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        die(
            f"download failed: {exc.reason}",
            proxy_hint() + "Otherwise clone the repository manually:\n"
            f"    git clone https://github.com/{REPO}.git",
        )

    import tarfile

    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if ".." not in m.name and not m.name.startswith("/")]
        tar.extractall(target, members=members)
    archive.unlink()

    roots = [p for p in target.iterdir() if p.is_dir() and (p / "wan-video").is_dir()]
    if not roots:
        die("the downloaded archive does not contain the expected layout.")
    ok(f"downloaded to {roots[0]}")
    return roots[0]


def install_skills(source: Path, dest_root: Path) -> Dict[str, Path]:
    """Copy each skill into place, replacing an existing copy."""
    dest_root.mkdir(parents=True, exist_ok=True)
    installed: Dict[str, Path] = {}
    for name in SKILLS:
        src = source / name
        if not (src / "scripts" / "mcp_server.py").is_file():
            warn(f"{name} is missing from the source; skipping")
            continue
        dst = dest_root / name
        if dst.resolve() == src.resolve():
            installed[name] = dst
            ok(f"{name} already in place")
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        installed[name] = dst
        ok(f"{name} -> {dst}")
    if not installed:
        die("no skills could be installed.")
    return installed


# ------------------------------------------------------------------- credential

def gateway_request(url: str, api_key: str) -> Tuple[int, str]:
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace") if exc.fp else ""
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def validate_key(api_key: str, gateway: str) -> List[str]:
    """Confirm the key works and return the model IDs its group exposes."""
    status, body = gateway_request(f"{gateway.rstrip('/')}/v1/models", api_key)
    if status == 0:
        die(
            f"cannot reach {gateway}: {redact(body)}",
            proxy_hint() + "Then re-run this installer.",
        )
    if status == 401 or "Invalid" in body or "INVALID_API_KEY" in body:
        die(
            "the gateway rejected this API key.",
            "Confirm the key was copied in full and still has quota.\n"
            "    Keys are managed on the gateway platform, not here.",
        )
    if not 200 <= status < 300:
        die(f"unexpected gateway response (HTTP {status}): {redact(body[:200])}")

    try:
        data = json.loads(body).get("data", [])
    except json.JSONDecodeError:
        die("the gateway returned a response this installer could not parse.")
    models = [m.get("id", "") for m in data if isinstance(m, dict) and m.get("id")]
    if not models:
        die(
            "this key's group exposes no models at all.",
            "Ask the gateway platform to attach a video model to this key's group.",
        )
    return models


def skills_for_models(models: List[str]) -> Dict[str, List[str]]:
    """Map available models onto the skills that can serve them."""
    seedance = [m for m in models if m.startswith("doubao-seedance")]
    wan = [m for m in models if m.startswith(("wan3", "wan2", "wanx"))]
    usable: Dict[str, List[str]] = {}
    if seedance:
        usable["seedance-video"] = seedance
    if wan:
        usable["wan-video"] = wan
    return usable


PIPED_HINT = (
    "This installer was piped into python, so its stdin is the script itself\n"
    "    and cannot also carry your answer. Supply the key up front instead:\n"
    "        curl -fsSL {url} -o install.py && python3 install.py\n"
    "    or pass it inline:\n"
    "        curl -fsSL {url} | python3 - --key sk-..."
).format(url=RAW_URL)


def read_key_interactively() -> str:
    """Prompt without echo. Uses /dev/tty so a piped stdin is not in the way."""
    if sys.stdin.isatty():
        return getpass.getpass("\n  API key: ").strip()

    # stdin is the piped script, so talk to the terminal directly instead.
    # Open in binary and wrap it: text mode on /dev/tty raises "not seekable".
    raw = None
    try:
        raw = open("/dev/tty", "r+b", buffering=0)
        tty = io.TextIOWrapper(raw, write_through=True)
        return getpass.getpass("\n  API key: ", stream=tty).strip()
    except (OSError, ValueError, io.UnsupportedOperation):
        die("cannot prompt for the API key: no terminal is attached.", PIPED_HINT)
    finally:
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass


def prompt_for_key() -> str:
    print("  Paste your API key. It will not be echoed, and is written only to")
    print("  the host configuration files listed at the end.")
    print(Style.dim("  (Get one from the gateway platform; this installer cannot create keys.)"))
    try:
        key = read_key_interactively()
    except (EOFError, KeyboardInterrupt):
        print()
        die("no key provided.", "Re-run with --key sk-... to supply it non-interactively.")
    if not key:
        die("no key provided.", PIPED_HINT if not sys.stdin.isatty() else "")
    if not key.startswith("sk-"):
        warn("that does not look like an 'sk-' key; continuing anyway")
    return key


# ----------------------------------------------------------------------- hosts

class Host:
    """A host whose configuration this installer can safely amend."""

    key = ""
    label = ""

    def detected(self) -> bool:
        raise NotImplementedError

    def configure(self, servers: Dict[str, Dict[str, Any]]) -> str:
        raise NotImplementedError

    def unconfigure(self) -> str:
        raise NotImplementedError

    @staticmethod
    def backup(path: Path) -> Optional[Path]:
        """Never modify a config without leaving a restorable copy."""
        if not path.is_file():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_suffix(path.suffix + f".backup-{stamp}")
        shutil.copy2(path, backup)
        return backup


class ClaudeDesktop(Host):
    key = "claude"
    label = "Claude Desktop"

    def config_path(self) -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", "")) / "Claude/claude_desktop_config.json"
        return Path.home() / ".config/Claude/claude_desktop_config.json"

    def detected(self) -> bool:
        return self.config_path().parent.is_dir()

    def configure(self, servers: Dict[str, Dict[str, Any]]) -> str:
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve every existing key; this file holds unrelated settings.
        config: Dict[str, Any] = {}
        if path.is_file():
            try:
                config = json.loads(path.read_text() or "{}")
            except json.JSONDecodeError:
                backup = self.backup(path)
                warn(f"existing config was not valid JSON; kept a copy at {backup}")
                config = {}
        backup = self.backup(path)

        entries = config.setdefault("mcpServers", {})
        for name, spec in servers.items():
            entries[name] = spec
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        detail = f" (backup: {backup.name})" if backup else ""
        return f"{path}{detail}\n      restart Claude Desktop to load the tools"

    def unconfigure(self) -> str:
        path = self.config_path()
        if not path.is_file():
            return "not configured"
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            return "config unreadable; left untouched"
        entries = config.get("mcpServers", {})
        removed = [n for n in SERVER_NAME.values() if entries.pop(n, None) is not None]
        if not removed:
            return "nothing to remove"
        self.backup(path)
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        return f"removed {', '.join(removed)} from {path}"


class CodexCLI(Host):
    key = "codex"
    label = "Codex CLI"

    def config_path(self) -> Path:
        home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
        return Path(home) / "config.toml"

    def detected(self) -> bool:
        return self.config_path().parent.is_dir()

    def configure(self, servers: Dict[str, Dict[str, Any]]) -> str:
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.is_file() else ""
        backup = self.backup(path)

        # Rewrite only our own blocks, line by line, so unrelated TOML survives.
        lines = existing.splitlines()
        for name in servers:
            header = f"[mcp_servers.{name}]"
            start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
            if start is None:
                continue
            end = start + 1
            while end < len(lines) and not lines[end].lstrip().startswith("["):
                end += 1
            del lines[start:end]

        blocks = []
        for name, spec in servers.items():
            args = ", ".join(json.dumps(a) for a in spec["args"])
            env = ", ".join(f"{k} = {json.dumps(v)}" for k, v in spec.get("env", {}).items())
            blocks.append(
                f"[mcp_servers.{name}]\n"
                f"command = {json.dumps(spec['command'])}\n"
                f"args = [{args}]\n"
                f"env = {{ {env} }}\n"
            )

        body = "\n".join(lines).rstrip()
        content = (body + "\n\n" if body else "") + "\n".join(blocks)
        path.write_text(content)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        detail = f" (backup: {backup.name})" if backup else ""
        return f"{path}{detail}"

    def unconfigure(self) -> str:
        path = self.config_path()
        if not path.is_file():
            return "not configured"
        lines = path.read_text().splitlines()
        removed = []
        for name in SERVER_NAME.values():
            header = f"[mcp_servers.{name}]"
            start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
            if start is None:
                continue
            end = start + 1
            while end < len(lines) and not lines[end].lstrip().startswith("["):
                end += 1
            del lines[start:end]
            removed.append(name)
        if not removed:
            return "nothing to remove"
        self.backup(path)
        path.write_text("\n".join(lines).rstrip() + "\n")
        return f"removed {', '.join(removed)} from {path}"


class WorkBuddy(Host):
    """WorkBuddy registers connectors through its UI, so emit a ready-to-paste spec."""

    key = "workbuddy"
    label = "Tencent WorkBuddy"

    def support_dir(self) -> Optional[Path]:
        for name in (".workbuddy", ".codebuddy"):
            candidate = Path.home() / name
            if candidate.is_dir():
                return candidate
        return None

    def detected(self) -> bool:
        return self.support_dir() is not None

    def configure(self, servers: Dict[str, Dict[str, Any]]) -> str:
        target = (self.support_dir() or Path.home()) / "video-skills-connector.json"
        target.write_text(json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False) + "\n")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return (
            f"{target}\n"
            "      WorkBuddy adds connectors through its interface, so this file is a\n"
            "      reference rather than a live config. In WorkBuddy open Connectors ->\n"
            "      Custom connector and copy the command, args and env from it.\n"
            "      Do not use Settings -> Models; that dialog only accepts chat models."
        )

    def unconfigure(self) -> str:
        target = (self.support_dir() or Path.home()) / "video-skills-connector.json"
        if target.is_file():
            target.unlink()
            return f"removed {target}"
        return "nothing to remove"


HOSTS: List[Host] = [ClaudeDesktop(), CodexCLI(), WorkBuddy()]


# ------------------------------------------------------------------------- main

def build_server_specs(
    installed: Dict[str, Path], usable: Dict[str, List[str]], api_key: str, gateway: str
) -> Dict[str, Dict[str, Any]]:
    specs: Dict[str, Dict[str, Any]] = {}
    for skill in usable:
        path = installed.get(skill)
        if path is None:
            continue
        env = {ENV_VAR[skill]: api_key}
        if gateway.rstrip("/") != DEFAULT_GATEWAY:
            env[ENV_VAR[skill].replace("_API_KEY", "_BASE_URL")] = gateway
        specs[SERVER_NAME[skill]] = {
            "command": interpreter_path(),
            "args": [str(path / "scripts" / "mcp_server.py")],
            "env": env,
        }
    return specs


def run_install(args: argparse.Namespace) -> int:
    total = 5
    print(Style.bold("\nVideo generation skills — installer"))
    print(Style.dim("Seedance and Wan video models, for Claude Desktop, Codex and WorkBuddy"))

    step(1, total, "Checking Python")
    check_python()

    step(2, total, "Getting the skills")
    source = locate_or_download(Path.home() / ".cache" / "video-skills")

    step(3, total, "Verifying the API key")
    api_key = (args.key or "").strip() or os.environ.get("VIDEO_SKILLS_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_key()
    gateway = args.gateway.rstrip("/")
    models = validate_key(api_key, gateway)
    ok(f"key accepted; {len(models)} model(s) available to it")

    usable = skills_for_models(models)
    if not usable:
        die(
            "this key has no video models: " + ", ".join(models[:8]),
            "Video generation needs a doubao-seedance-* or wan* model.\n"
            "    Ask the gateway platform to attach one to this key's group.",
        )
    for skill, available in usable.items():
        ok(f"{skill}: {', '.join(available[:4])}")
    skipped = set(SKILLS) - set(usable)
    for skill in sorted(skipped):
        warn(f"{skill}: no matching model for this key, not configured")

    step(4, total, "Installing")
    dest_root = Path(args.dir).expanduser() if args.dir else Path.home() / ".codex" / "skills"
    installed = install_skills(source, dest_root)
    installed = {k: v for k, v in installed.items() if k in usable}

    step(5, total, "Configuring hosts")
    specs = build_server_specs(installed, usable, api_key, gateway)
    selected = [h for h in HOSTS if args.host in (None, h.key)]
    configured = 0
    for host in selected:
        if not host.detected():
            print(f"  {Style.dim('-')} {host.label}: not found on this machine")
            continue
        try:
            detail = host.configure(specs)
        except Exception as exc:  # noqa: BLE001
            fail(f"{host.label}: {redact(str(exc))}")
            continue
        ok(f"{host.label}: {detail}")
        configured += 1

    if not configured:
        warn("no supported host was detected")
        print("\n    Register this manually in any MCP host:")
        for name, spec in specs.items():
            print(f"      {name}: {spec['command']} {spec['args'][0]}")
            print(f"        env {ENV_VAR[[k for k, v in SERVER_NAME.items() if v == name][0]]}=<your key>")
        return 1

    print(Style.bold(Style.green("\n  Done.")))
    print("\n  Restart your AI app, then just ask for a video:")
    print(Style.dim('    "生成一个 5 秒视频:橘猫在阳光下的窗台上伸懒腰,电影感"'))
    print(Style.dim('    "Make a 5s clip of a golden retriever running on the beach at sunset"'))
    print("\n  Renders take 1-5 minutes and are billed per render.")
    print("  Start at 720p and 5s while you refine the prompt.")
    print(Style.dim(f"\n  Your key was written only to the host config files listed above."))
    return 0


def run_uninstall(args: argparse.Namespace) -> int:
    print(Style.bold("\nRemoving the video generation skills"))
    for host in HOSTS:
        if args.host not in (None, host.key):
            continue
        try:
            print(f"  {host.label}: {host.unconfigure()}")
        except Exception as exc:  # noqa: BLE001
            fail(f"{host.label}: {redact(str(exc))}")

    dest_root = Path(args.dir).expanduser() if args.dir else Path.home() / ".codex" / "skills"
    for name in SKILLS:
        path = dest_root / name
        if path.is_dir():
            shutil.rmtree(path)
            print(f"  removed {path}")
    print("\n  Done. Restart your AI app.")
    print(Style.dim("  Downloaded videos and API keys held elsewhere were left untouched."))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Seedance and Wan video generation skills.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--key", help="API key; prompts interactively when omitted")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY, help="gateway base URL")
    parser.add_argument("--dir", help="where to install the skills")
    parser.add_argument(
        "--host",
        choices=[h.key for h in HOSTS],
        help="configure only this host (default: every host detected)",
    )
    parser.add_argument("--uninstall", action="store_true", help="undo the installation")
    args = parser.parse_args()

    try:
        return run_uninstall(args) if args.uninstall else run_install(args)
    except KeyboardInterrupt:
        print("\n\n  Cancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
