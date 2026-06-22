#!/usr/bin/env python3
"""Small in-memory contact book example.

Run it with no arguments to see a few sample contacts printed as a table.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    name: str
    email: str
    phone: str


def format_contacts(contacts):
    """Return contacts as a simple fixed-width table."""
    name_width = max(len("Name"), *(len(contact.name) for contact in contacts))
    email_width = max(len("Email"), *(len(contact.email) for contact in contacts))
    header = f"{'Name':<{name_width}}  {'Email':<{email_width}}  Phone"
    divider = "-" * len(header)
    rows = [header, divider]
    for contact in contacts:
        rows.append(f"{contact.name:<{name_width}}  {contact.email:<{email_width}}  {contact.phone}")
    return "\n".join(rows)


def main():
    contacts = [
        Contact("Ada Lovelace", "ada@example.com", "555-0101"),
        Contact("Grace Hopper", "grace@example.com", "555-0102"),
        Contact("Katherine Johnson", "katherine@example.com", "555-0103"),
    ]
    print(format_contacts(contacts))


if __name__ == "__main__":
    main()
