"""
Command Whitelist Management Module

Responsible for loading and managing command whitelist, checking if commands are allowed to execute
"""

import importlib.resources
import logging
import os
import re
from typing import List, Set, Tuple

# Configure logging
logger = logging.getLogger(__name__)

# Whitelist configuration file path
WHITELIST_FILE_PATH = os.path.join(os.path.expanduser("~"), ".castrel", "whitelist.conf")

# Cache default whitelist (read from package data file, won't change, can be cached)
_default_whitelist_cache: List[str] = []
_default_whitelist_loaded: bool = False


def _load_default_whitelist() -> List[str]:
    """
    Load default whitelist command list from package data file

    Returns:
        List[str]: Default whitelist command list
    """
    global _default_whitelist_cache, _default_whitelist_loaded

    if _default_whitelist_loaded:
        return _default_whitelist_cache

    commands = []

    try:
        # Use importlib.resources to read package data file
        # Python 3.9+ recommends using files() API
        data_files = importlib.resources.files("castrel_proxy.data")
        whitelist_file = data_files.joinpath("default_whitelist.txt")

        content = whitelist_file.read_text(encoding="utf-8")

        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comment lines
            if not line or line.startswith("#"):
                continue
            commands.append(line)

        logger.debug(f"[WHITELIST] Loaded {len(commands)} default commands from package data")

    except Exception as e:
        logger.error(f"[WHITELIST] Failed to load default whitelist from package: {e}")
        # If loading fails, return basic command list as fallback
        commands = [
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "pwd",
            "cd",
            "mkdir",
            "echo",
            "git",
            "python",
            "python3",
            "pip",
            "pip3",
            "node",
            "npm",
        ]

    _default_whitelist_cache = commands
    _default_whitelist_loaded = True

    return commands


def get_default_whitelist() -> List[str]:
    """
    Get default whitelist command list

    Returns:
        List[str]: Default whitelist command list
    """
    return _load_default_whitelist()


def _ensure_whitelist_file_exists() -> None:
    """
    Ensure whitelist configuration file exists, copy default config from package data file if not exists
    """
    if os.path.exists(WHITELIST_FILE_PATH):
        return

    # Ensure directory exists
    whitelist_dir = os.path.dirname(WHITELIST_FILE_PATH)
    os.makedirs(whitelist_dir, exist_ok=True)

    try:
        # Read default config from package data file
        data_files = importlib.resources.files("castrel_proxy.data")
        whitelist_file = data_files.joinpath("default_whitelist.txt")
        content = whitelist_file.read_text(encoding="utf-8")

        # Write to user configuration file
        with open(WHITELIST_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[WHITELIST] Created default whitelist file from package data: {WHITELIST_FILE_PATH}")

    except Exception as e:
        logger.error(f"[WHITELIST] Failed to copy default whitelist from package: {e}")
        # If reading from package fails, create using basic command list
        basic_commands = get_default_whitelist()
        content = "# Castrel Command Whitelist Configuration File\n"
        content += "# One command name per line, lines starting with # are comments\n\n"
        content += "\n".join(basic_commands) + "\n"

        with open(WHITELIST_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[WHITELIST] Created basic whitelist file: {WHITELIST_FILE_PATH}")


def load_whitelist() -> Set[str]:
    """
    Load whitelist configuration (re-read file on each call, supports dynamic modification)

    Returns:
        Set[str]: Whitelist command set
    """
    # Ensure configuration file exists
    _ensure_whitelist_file_exists()

    whitelist: Set[str] = set()

    try:
        with open(WHITELIST_FILE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                # Remove leading and trailing whitespace
                line = line.strip()

                # Skip empty lines and comment lines
                if not line or line.startswith("#"):
                    continue

                # Add to whitelist
                whitelist.add(line)

        logger.debug(f"[WHITELIST] Loaded {len(whitelist)} commands from whitelist: {WHITELIST_FILE_PATH}")

    except Exception as e:
        logger.error(f"[WHITELIST] Failed to load whitelist file: {e}")
        # If loading fails, use default whitelist
        whitelist = set(get_default_whitelist())
        logger.warning(f"[WHITELIST] Using default whitelist with {len(whitelist)} commands")

    return whitelist


def _get_base_command(command: str) -> str:
    """
    Extract base command name from a single command

    Args:
        command: Single command string

    Returns:
        str: Base command name
    """
    if not command or not command.strip():
        return ""

    # Remove leading and trailing whitespace
    command = command.strip()

    # Skip environment variable assignment prefix (e.g., VAR=value cmd)
    while "=" in command.split()[0] if command.split() else False:
        parts = command.split(None, 1)
        if len(parts) > 1:
            command = parts[1]
        else:
            return ""

    # Extract first word of command
    parts = command.split()
    if not parts:
        return ""

    base_command = parts[0]

    # Handle path-style commands (e.g., /usr/bin/ls -> ls)
    base_command = os.path.basename(base_command)

    return base_command


def _remove_quoted_strings(command: str) -> str:
    """
    Remove quoted content from command to avoid operators inside quotes being split

    Args:
        command: Command string

    Returns:
        str: Command with quoted content removed
    """
    result = []
    i = 0
    in_single_quote = False
    in_double_quote = False
    escape_next = False

    while i < len(command):
        char = command[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if char == "\\":
            escape_next = True
            i += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
            continue

        if not in_single_quote and not in_double_quote:
            result.append(char)

        i += 1

    return "".join(result)


def _extract_command_substitutions(command: str) -> List[str]:
    """
    Extract commands from command substitutions: $(...) and `...`

    Args:
        command: Command string

    Returns:
        List[str]: List of commands from command substitutions
    """
    substitutions = []

    # Match $(...) - need to handle nested parentheses
    # Simplified handling: use regex to match non-nested cases
    dollar_paren_pattern = r"\$\(([^()]*)\)"
    for match in re.finditer(dollar_paren_pattern, command):
        inner_cmd = match.group(1).strip()
        if inner_cmd:
            substitutions.append(inner_cmd)

    # Match `...` backticks
    backtick_pattern = r"`([^`]*)`"
    for match in re.finditer(backtick_pattern, command):
        inner_cmd = match.group(1).strip()
        if inner_cmd:
            substitutions.append(inner_cmd)

    return substitutions


def _extract_commands(full_command: str) -> List[str]:
    """
    Extract all subcommands from compound command

    Handled operators:
    - Command separators: &&, ||, ;, & (background execution)
    - Pipes: |, |&
    - Command substitutions: $(...), `...`

    Args:
        full_command: Complete command string

    Returns:
        List[str]: List of all subcommands
    """
    if not full_command or not full_command.strip():
        return []

    commands = []

    # First extract commands from command substitutions
    substitutions = _extract_command_substitutions(full_command)
    for sub in substitutions:
        # Recursively extract subcommands from command substitutions
        commands.extend(_extract_commands(sub))

    # Remove quoted content to avoid operators inside quotes being split
    cleaned_command = _remove_quoted_strings(full_command)

    # Use regex to split commands
    # Match: &&, ||, |&, |, ;, & (but not single characters in && or |&)
    # Note order: match longer operators first
    split_pattern = r"\s*(?:&&|\|\||;\s*|\|&|\||\s+&\s+|&\s*$)\s*"

    # Split commands
    parts = re.split(split_pattern, cleaned_command)

    for part in parts:
        part = part.strip()
        if part:
            # Remove redirection parts (but keep the command itself)
            # Match: >, >>, <, <<, 2>, 2>>, &>, >&, etc.
            # Only remove redirection symbols and following file paths
            redirect_pattern = r"\s*(?:\d*>>?|<<?|&>|>&)\s*\S+"
            part_no_redirect = re.sub(redirect_pattern, "", part).strip()

            if part_no_redirect:
                commands.append(part_no_redirect)

    return commands


def is_command_allowed(full_command: str) -> Tuple[bool, List[str]]:
    """
    Check if command is in whitelist

    Parse all subcommands in compound command, ensure each subcommand is in whitelist.

    Args:
        full_command: Complete command string

    Returns:
        Tuple[bool, List[str]]: (Whether execution is allowed, List of commands not in whitelist)
    """
    if not full_command or not full_command.strip():
        return False, ["(empty command)"]

    # Extract all subcommands
    commands = _extract_commands(full_command)

    if not commands:
        # If no commands extracted, try to get base command directly
        base_cmd = _get_base_command(full_command)
        if base_cmd:
            commands = [full_command]
        else:
            return False, ["(empty command)"]

    # Load whitelist
    whitelist = load_whitelist()

    # Check each subcommand
    blocked_commands = []
    for cmd in commands:
        base_cmd = _get_base_command(cmd)
        if not base_cmd:
            continue

        if base_cmd not in whitelist:
            blocked_commands.append(base_cmd)

    is_allowed = len(blocked_commands) == 0

    if not is_allowed:
        logger.warning(
            f"[WHITELIST] Commands not in whitelist: blocked={blocked_commands}, full_command={full_command[:200]}"
        )

    return is_allowed, blocked_commands


def get_whitelist_file_path() -> str:
    """
    Get whitelist configuration file path

    Returns:
        str: Full path to whitelist configuration file
    """
    return WHITELIST_FILE_PATH


def init_whitelist_file() -> str:
    """
    Initialize whitelist configuration file

    If file does not exist, copy default config from package data file to user directory.
    If file already exists, do nothing.

    Returns:
        str: Whitelist configuration file path
    """
    _ensure_whitelist_file_exists()
    return WHITELIST_FILE_PATH
