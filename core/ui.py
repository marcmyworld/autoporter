#!/usr/bin/env python3
"""
Autoporter UI Engine: ANSI Styling, Banners, Spinners, Progress Bars & Menus
"""

import sys
import time
import shutil
import random
import threading
from typing import List, Optional, Any, Callable


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    BG_BLUE = "\033[44m"
    BG_CYAN = "\033[46m"
    BG_MAGENTA = "\033[45m"


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def banner():
    art = f"""{Colors.BRIGHT_CYAN}{Colors.BOLD}
  █████╗ ██╗   ██╗████████╗ ██████╗ ██████╗  ██████╗ ██████╗ ████████╗███████╗██████╗ 
 ██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗
 ███████║██║   ██║   ██║   ██║   ██║██████╔╝██║   ██║██████╔╝   ██║   █████╗  ██████╔╝
 ██╔══██║██║   ██║   ██║   ██║   ██║██╔═══╝ ██║   ██║██╔══██╗   ██║   ██╔══╝  ██╔══██╗
 ██║  ██║╚██████╔╝   ██║   ╚██████╔╝██║     ╚██████╔╝██║  ██║   ██║   ███████╗██║  ██║
 ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝      ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝{Colors.RESET}
   {Colors.BRIGHT_MAGENTA}◈ Android ROM Kitchen & Partition Transmutation Engine ◈ Version 1.0.0{Colors.RESET}
   {Colors.DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.RESET}
"""
    print(art)


MOTD_THOUGHTS = [
    "Every bootloop is just an invitation to inspect logcat.",
    "Great ROMs aren't built in a day, but clean partitions help.",
    "SELinux in enforcing mode is your shield — respect the contexts!",
    "Patience, precision, and good backups make the master chef.",
    "May your dynamic partitions always fit within the super image size.",
    "Stock is just a canvas; you're the artist.",
    "Clean cauldron, sharp tools, and smooth boots.",
    "Fastboot never lies; flash with care, port with flare.",
    "Turning stock into magic, one partition at a time.",
    "Simplicity is the soul of efficiency. Happy porting!",
]


def print_motd():
    thought = random.choice(MOTD_THOUGHTS)
    print(f"  {Colors.BRIGHT_YELLOW}💡 MOTD:{Colors.RESET} {Colors.ITALIC}\"{thought}\"{Colors.RESET}\n")


def print_info(message: str):
    print(f" {Colors.BRIGHT_BLUE}{Colors.BOLD}[ℹ INFO]{Colors.RESET} {message}")


def print_success(message: str):
    print(f" {Colors.BRIGHT_GREEN}{Colors.BOLD}[✓ SUCCESS]{Colors.RESET} {Colors.BOLD}{message}{Colors.RESET}")


def print_warning(message: str):
    print(f" {Colors.BRIGHT_YELLOW}{Colors.BOLD}[⚠ WARNING]{Colors.RESET} {message}")


def print_error(message: str):
    print(f" {Colors.BRIGHT_RED}{Colors.BOLD}[✗ ERROR]{Colors.RESET} {message}")


def print_section(title: str):
    term_width = shutil.get_terminal_size((80, 20)).columns
    divider = "─" * min(term_width - 4, 76)
    print(f"\n{Colors.BRIGHT_CYAN}{Colors.BOLD}▶ {title}{Colors.RESET}")
    print(f"{Colors.DIM}  {divider}{Colors.RESET}")


class Spinner:
    """Animated CLI spinner for background operations."""

    def __init__(self, message: str = "Processing..."):
        self.message = message
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.stop_event = threading.Event()
        self.thread = None
        self.start_time = None

    def _spin(self):
        idx = 0
        while not self.stop_event.is_set():
            elapsed = time.time() - self.start_time
            frame = self.frames[idx % len(self.frames)]
            msg = f"\r {Colors.BRIGHT_CYAN}{frame}{Colors.RESET} {self.message} {Colors.DIM}({elapsed:.1f}s){Colors.RESET}"
            sys.stdout.write(msg)
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

    def __enter__(self):
        self.start_time = time.time()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def update_message(self, new_message: str):
        self.message = new_message

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        elapsed = time.time() - self.start_time
        # Clear line
        sys.stdout.write("\r" + " " * (len(self.message) + 30) + "\r")
        sys.stdout.flush()
        if exc_type is None:
            print(f" {Colors.BRIGHT_GREEN}✓{Colors.RESET} {self.message} {Colors.DIM}(Done in {elapsed:.2f}s){Colors.RESET}")
        else:
            print(f" {Colors.BRIGHT_RED}✗{Colors.RESET} {self.message} {Colors.RED}[Failed]{Colors.RESET}")


def progress_bar(iteration: int, total: int, prefix: str = "", suffix: str = "", length: int = 40):
    """Prints a styled terminal progress bar."""
    if total <= 0:
        total = 1
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_len = int(length * iteration // total)
    bar = f"{Colors.BRIGHT_GREEN}{'█' * filled_len}{Colors.DIM}{'░' * (length - filled_len)}{Colors.RESET}"
    sys.stdout.write(f"\r {Colors.BOLD}{prefix}{Colors.RESET} [{bar}] {Colors.BRIGHT_YELLOW}{percent}%{Colors.RESET} {suffix}")
    sys.stdout.flush()
    if iteration >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def print_table(headers: List[str], rows: List[List[Any]]):
    """Renders an aligned, styled text table."""
    if not rows:
        print(f"  {Colors.DIM}(empty table){Colors.RESET}")
        return

    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            str_val = str(val)
            # ignore ansi codes in length calculation
            clean_len = len(str_val.replace(Colors.BOLD, "").replace(Colors.RESET, "").replace(Colors.GREEN, "").replace(Colors.YELLOW, "").replace(Colors.RED, "").replace(Colors.CYAN, ""))
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], clean_len)

    # Format header
    header_str = " │ ".join(f"{Colors.BOLD}{h.ljust(col_widths[i])}{Colors.RESET}" for i, h in enumerate(headers))
    sep_str = "─┼─".join("─" * col_widths[i] for i in range(len(headers)))

    print(f"  ┌─{'─┬─'.join('─' * col_widths[i] for i in range(len(headers)))}─┐")
    print(f"  │ {header_str} │")
    print(f"  ├─{sep_str}─┤")
    for row in rows:
        cells = []
        for i, val in enumerate(row):
            str_val = str(val)
            clean_len = len(str_val.replace(Colors.BOLD, "").replace(Colors.RESET, "").replace(Colors.GREEN, "").replace(Colors.YELLOW, "").replace(Colors.RED, "").replace(Colors.CYAN, ""))
            pad = " " * (col_widths[i] - clean_len)
            cells.append(f"{str_val}{pad}")
        print(f"  │ {' │ '.join(cells)} │")
    print(f"  └─{'─┴─'.join('─' * col_widths[i] for i in range(len(headers)))}─┘")


def ask_choice(prompt: str, options: List[str], default_idx: int = 0) -> int:
    """Presents a list of options and returns the chosen 0-based index."""
    print(f"\n{Colors.BOLD}{prompt}{Colors.RESET}")
    for i, opt in enumerate(options):
        is_def = f" {Colors.DIM}(default){Colors.RESET}" if i == default_idx else ""
        print(f"  {Colors.BRIGHT_CYAN}[{i + 1}]{Colors.RESET} {opt}{is_def}")

    while True:
        try:
            choice = input(f"\n {Colors.BRIGHT_YELLOW}Choice [1-{len(options)}]{Colors.RESET} (default: {default_idx + 1}): ").strip()
            if not choice:
                return default_idx
            val = int(choice) - 1
            if 0 <= val < len(options):
                return val
            print_warning(f"Please enter a number between 1 and {len(options)}")
        except (ValueError, EOFError):
            print_warning("Invalid input, please try again.")


def ask_text(prompt: str, default: str = "") -> str:
    """Prompts for text input with an optional default."""
    def_hint = f" [{Colors.DIM}{default}{Colors.RESET}]" if default else ""
    try:
        res = input(f" {Colors.BOLD}{prompt}{Colors.RESET}{def_hint}: ").strip()
        return res if res else default
    except (EOFError, KeyboardInterrupt):
        return default


def ask_confirm(prompt: str, default: bool = True) -> bool:
    """Asks a yes/no confirmation question."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        res = input(f" {Colors.BOLD}{prompt}{Colors.RESET} {Colors.BRIGHT_YELLOW}{suffix}{Colors.RESET}: ").strip().lower()
        if not res:
            return default
        return res in ["y", "yes", "true", "1"]
    except (EOFError, KeyboardInterrupt):
        return default


def parse_range_selection(
    user_input: str,
    total_count: int,
    names: Optional[List[str]] = None,
) -> List[int]:
    """
    Parses complex selection inputs like '1-15, 18-20', '1, 3, 5-8', 'boot, vendor', or 'all'.
    Returns a list of unique 0-based valid indices in original order.

    Examples:
      - '1-15, 18-20' -> indices 0..14 and 17..19
      - '1, 3, 5-8'   -> indices 0, 2, 4, 5, 6, 7
      - 'all' or '*'  -> all indices 0..total_count-1
      - 'boot, super' -> matched against names list
    """
    selected_indices: List[int] = []

    def add_index(idx: int):
        if 0 <= idx < total_count and idx not in selected_indices:
            selected_indices.append(idx)

    tokens = [t.strip() for t in user_input.split(",") if t.strip()]

    for token in tokens:
        # Wildcard 'all' or '*'
        if token.lower() in ["all", "*"]:
            for i in range(total_count):
                add_index(i)
            continue

        # Range format: '1-15' or '1 - 15'
        if "-" in token:
            parts = token.split("-")
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                start = int(parts[0].strip())
                end = int(parts[1].strip())
                if start > end:
                    start, end = end, start
                for num in range(start, end + 1):
                    add_index(num - 1)
                continue

        # Single integer: '5'
        if token.isdigit():
            add_index(int(token) - 1)
            continue

        # Name matching against names list
        if names:
            clean_token = token.lower().replace(".img", "").strip()
            matched = False
            for i, name in enumerate(names):
                clean_name = str(name).lower().replace(".img", "").strip()
                if clean_name == clean_token:
                    add_index(i)
                    matched = True
            # Also allow prefix / partial match if exact didn't match
            if not matched:
                for i, name in enumerate(names):
                    clean_name = str(name).lower().replace(".img", "").strip()
                    if clean_name.startswith(clean_token) or clean_token.startswith(clean_name):
                        add_index(i)

    return selected_indices

