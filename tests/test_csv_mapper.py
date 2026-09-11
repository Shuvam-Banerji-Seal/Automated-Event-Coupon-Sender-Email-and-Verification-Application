"""Tests for CSV inspection and column-role detection."""

import pytest

from src import csv_mapper


GOOGLE_FORM = b"""Timestamp,Email Address,Your Name ,Veg / Non-Veg?,Roll Number
2026-01-01 10:00,ada@iiserkol.ac.in,Ada Lovelace,Veg,21MS001
2026-01-01 10:01,grace@iiserkol.ac.in,Grace Hopper,Non-Veg,21MS002
2026-01-01 10:02,alan@iiserkol.ac.in,Alan Turing,veg,21MS003
"""


class TestReading:
    def test_headers_and_rows(self):
        headers, rows, delim = csv_mapper.read_csv_bytes(GOOGLE_FORM)
        assert headers == [
            "Timestamp", "Email Address", "Your Name", "Veg / Non-Veg?", "Roll Number"
        ]
        assert len(rows) == 3
        assert delim == ","

    def test_semicolon_delimited(self):
        raw = b"email;name\na@x.com;Ada\nb@x.com;Bob\n"
        headers, rows, delim = csv_mapper.read_csv_bytes(raw)
        assert delim == ";"
        assert headers == ["email", "name"]
        assert len(rows) == 2

    def test_tab_delimited(self):
        raw = b"email\tname\na@x.com\tAda\nb@x.com\tBob\n"
        _, rows, delim = csv_mapper.read_csv_bytes(raw)
        assert delim == "\t"
        assert len(rows) == 2

    def test_utf8_bom_is_stripped(self):
        """Excel writes a BOM; without stripping it the first header is unusable."""
        raw = "﻿email,name\na@x.com,Adá\n".encode("utf-8")
        headers, rows, _ = csv_mapper.read_csv_bytes(raw)
        assert headers[0] == "email"
        assert rows[0]["name"] == "Adá"

    def test_undecodable_bytes_do_not_raise(self):
        raw = b"email,name\na@x.com,\xff\xfe bad bytes\n"
        headers, rows, _ = csv_mapper.read_csv_bytes(raw)
        assert headers == ["email", "name"]
        assert len(rows) == 1

    def test_blank_headers_get_names(self):
        raw = b"email,,name\na@x.com,x,Ada\n"
        headers, _, _ = csv_mapper.read_csv_bytes(raw)
        assert headers == ["email", "column_2", "name"]

    def test_duplicate_headers_are_disambiguated(self):
        raw = b"email,email,name\na@x.com,b@x.com,Ada\n"
        headers, rows, _ = csv_mapper.read_csv_bytes(raw)
        assert headers == ["email", "email_1", "name"]
        assert rows[0]["email_1"] == "b@x.com"

    def test_fully_blank_rows_are_dropped(self):
        raw = b"email,name\na@x.com,Ada\n,\n\nb@x.com,Bob\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        assert len(rows) == 2


class TestDetection:
    def test_detects_all_four_roles_from_a_form_export(self):
        result = csv_mapper.inspect(GOOGLE_FORM)
        mapping = result["suggested_mapping"]
        assert mapping["email"] == "Email Address"
        assert mapping["name"] == "Your Name"
        assert mapping["food_preference"] == "Veg / Non-Veg?"

    def test_email_detected_from_values_when_header_is_unhelpful(self):
        """Header text lies more often than data does."""
        raw = b"contact,person\nada@x.com,Ada Lovelace\nbob@x.com,Bob Smith\n"
        mapping = csv_mapper.inspect(raw)["suggested_mapping"]
        assert mapping["email"] == "contact"

    def test_name_column_not_confused_with_email(self):
        raw = b"a,b\nada@x.com,Ada Lovelace\nbob@x.com,Bob Smith\n"
        mapping = csv_mapper.inspect(raw)["suggested_mapping"]
        assert mapping["email"] == "a"
        assert mapping["name"] == "b"

    def test_timestamp_is_never_mapped(self):
        result = csv_mapper.inspect(GOOGLE_FORM)
        assert "Timestamp" not in result["suggested_mapping"].values()

    def test_no_column_is_assigned_to_two_roles(self):
        mapping = csv_mapper.inspect(GOOGLE_FORM)["suggested_mapping"]
        assigned = [c for c in mapping.values() if c]
        assert len(assigned) == len(set(assigned))

    def test_free_text_mentioning_veg_does_not_win_food_role(self):
        """A comments column that happens to say "veg" must not be mistaken."""
        raw = (
            b"email,comments\n"
            b"a@x.com,I would prefer veg food if possible please\n"
            b"b@x.com,No strong opinion about the veg situation honestly\n"
            b"c@x.com,Anything is fine really whatever you serve\n"
        )
        mapping = csv_mapper.inspect(raw)["suggested_mapping"]
        assert mapping["food_preference"] != "comments"

    def test_missing_optional_roles_are_none(self):
        raw = b"email\na@x.com\nb@x.com\n"
        mapping = csv_mapper.inspect(raw)["suggested_mapping"]
        assert mapping["email"] == "email"
        assert mapping["name"] is None


class TestValidation:
    def test_counts_invalid_and_duplicate_emails(self):
        raw = (
            b"email,name\n"
            b"ada@x.com,Ada\n"
            b"not-an-email,Bob\n"
            b"ada@x.com,Ada Again\n"
            b",Nobody\n"
        )
        validation = csv_mapper.inspect(raw)["validation"]
        assert validation["valid_emails"] == 1
        assert validation["invalid_count"] == 2      # malformed + empty
        assert validation["duplicate_count"] == 1

    def test_preview_is_capped(self):
        raw = b"email\n" + b"".join(f"u{i}@x.com\n".encode() for i in range(100))
        assert len(csv_mapper.inspect(raw)["preview"]) == 25
        assert csv_mapper.inspect(raw)["row_count"] == 100


class TestBuildRecipients:
    def test_applies_mapping(self):
        _, rows, _ = csv_mapper.read_csv_bytes(GOOGLE_FORM)
        mapping = csv_mapper.inspect(GOOGLE_FORM)["suggested_mapping"]
        accepted, rejected = csv_mapper.build_recipients(rows, mapping)
        assert len(accepted) == 3
        assert not rejected
        assert accepted[0]["email"] == "ada@iiserkol.ac.in"
        assert accepted[0]["name"] == "Ada Lovelace"
        assert accepted[1]["food_preference"] == "Non-Vegetarian"

    def test_unmapped_columns_are_kept_as_template_variables(self):
        _, rows, _ = csv_mapper.read_csv_bytes(GOOGLE_FORM)
        mapping = csv_mapper.inspect(GOOGLE_FORM)["suggested_mapping"]
        accepted, _ = csv_mapper.build_recipients(rows, mapping)
        assert accepted[0]["extra"]["roll_number"] == "21MS001"

    def test_extra_keys_are_valid_identifiers(self):
        """Keys become Jinja variables, so they cannot contain punctuation."""
        raw = b"email,Roll No. (2026)\na@x.com,21MS001\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        accepted, _ = csv_mapper.build_recipients(rows, {"email": "email"})
        assert list(accepted[0]["extra"]) == ["roll_no_2026"]

    def test_extras_cannot_override_the_email_field(self):
        """A stray column must not redirect where an invitation is addressed."""
        raw = b"Email Address,email\nreal@x.com,attacker@evil.com\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        accepted, _ = csv_mapper.build_recipients(rows, {"email": "Email Address"})
        assert accepted[0]["email"] == "real@x.com"
        assert "email" not in accepted[0]["extra"]

    def test_rejects_malformed_and_duplicate(self):
        raw = b"email\nada@x.com\nbad\nada@x.com\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        accepted, rejected = csv_mapper.build_recipients(rows, {"email": "email"})
        assert len(accepted) == 1
        assert {r["reason"] for r in rejected} == {"malformed email", "duplicate in file"}

    def test_rejection_rows_are_1_indexed_with_header(self):
        """Row numbers must match what the operator sees in a spreadsheet."""
        raw = b"email\nada@x.com\nbad\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        _, rejected = csv_mapper.build_recipients(rows, {"email": "email"})
        assert rejected[0]["row"] == 3

    def test_missing_food_column_defaults_to_vegetarian(self):
        raw = b"email\na@x.com\n"
        _, rows, _ = csv_mapper.read_csv_bytes(raw)
        accepted, _ = csv_mapper.build_recipients(rows, {"email": "email"})
        assert accepted[0]["food_preference"] == "Vegetarian"
        assert accepted[0]["include_qr"] is True
