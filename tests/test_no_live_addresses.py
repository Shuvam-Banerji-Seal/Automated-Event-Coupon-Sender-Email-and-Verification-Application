"""Example addresses must not name the institute, and must not look like values.

This exists because a placeholder on the Send page listed two addresses on the
institute's own live domain. It is wrong twice over: grey placeholder text
inside an empty address box looks exactly like a list of people about to be
mailed, and the operator reasonably believed the system was about to write to
them — and had either address ever been treated as a value rather than a hint,
the mail would have gone to a real mailbox at the institute.

Two narrow rules, rather than a blanket ban on every fixture address:

* Nothing anywhere may put an address on the institute's domain. That is the
  one domain where a mistake reaches a colleague.
* Nothing the operator *sees* may carry an address on a domain that accepts
  mail. RFC 2606 reserves example.com and friends exactly for this.

Deep unit fixtures on throwaway domains are left alone: they never leave a
mocked mailer, and rewriting forty of them would buy nothing.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Written in pieces so this file does not itself contain the address it forbids.
INSTITUTE = "iiserkol" + "." + "ac" + "." + "in"

ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RESERVED = re.compile(
    r"@(?:[\w-]+\.)*(?:example\.(?:com|net|org)|test|invalid|localhost)$", re.I)

# Rendered to the operator, so an address here can be mistaken for a recipient.
SEEN_BY_OPERATOR = ("templates", "static")
SKIP_DIRS = {"__pycache__", "vendor", "seed"}
TEXT_SUFFIXES = {".py", ".html", ".js", ".json", ".txt", ".md", ".csv", ".css"}

# The operator's own SMTP account is configuration, not an example recipient.
ALLOWED_PREFIXES = ("your-email@", "you@", "noreply@")


def _files(folders):
    for folder in folders:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES \
                    and not set(path.parts) & SKIP_DIRS:
                yield path


def _addresses(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    for line_no, line in enumerate(text.splitlines(), 1):
        for address in ADDRESS.findall(line):
            yield line_no, address


def test_nothing_names_an_address_at_the_institute():
    """One mistake on this domain reaches a real colleague."""
    offenders = [
        f"{path.relative_to(ROOT)}:{n}  {a}"
        for path in _files(("templates", "src", "tests", "static", "scripts"))
        for n, a in _addresses(path)
        if a.lower().endswith("@" + INSTITUTE)
    ]
    assert not offenders, (
        "Addresses on the institute's live domain:\n  " + "\n  ".join(offenders)
        + "\nUse example.com — it is reserved and cannot be delivered to."
    )


def test_addresses_shown_to_the_operator_are_undeliverable():
    offenders = [
        f"{path.relative_to(ROOT)}:{n}  {a}"
        for path in _files(SEEN_BY_OPERATOR)
        for n, a in _addresses(path)
        if not RESERVED.search(a) and not a.lower().startswith(ALLOWED_PREFIXES)
    ]
    assert not offenders, (
        "The operator can see these, so they can be mistaken for recipients:\n  "
        + "\n  ".join(offenders)
    )


def test_no_multi_address_box_has_an_address_in_its_placeholder():
    """A list-shaped box with addresses greyed into it reads as a recipient list.

    A single-address input is different: "you@example.com" in a send-a-test
    field is a helpful hint about the shape of one value, and nobody reads it as
    a list of people. The box that caused this was a textarea taking one
    address per line, where greyed-in addresses look exactly like the addresses
    that are about to be mailed.
    """
    offenders = []
    for path in _files(("templates",)):
        text = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<textarea\b[^>]*>", text, re.S):
            for placeholder in re.findall(r'placeholder="([^"]*)"', tag):
                if ADDRESS.search(placeholder):
                    offenders.append(f"{path.relative_to(ROOT)}  {placeholder!r}")
    assert not offenders, (
        "These multi-line boxes look pre-filled with recipients:\n  "
        + "\n  ".join(offenders)
    )
