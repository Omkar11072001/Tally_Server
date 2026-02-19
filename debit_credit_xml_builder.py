"""Build Tally-compatible XML for Debit Note and Credit Note voucher creation.

Reuses the same voucher XML structure as purchase/sales vouchers since
Tally treats Debit/Credit Notes identically — only VOUCHERTYPENAME differs.
"""

import xml.etree.ElementTree as ET

from debit_credit_models import CreateCreditNotePayload, CreateDebitNotePayload
from purchase_xml_builder import _build_voucher_element


def _build_envelope(company_name: str, username: str | None, password: str | None, vouchers) -> str:
    """Build complete Tally XML envelope for debit/credit note vouchers."""
    envelope = ET.Element("ENVELOPE")

    header = ET.SubElement(envelope, "HEADER")
    req = ET.SubElement(header, "TALLYREQUEST")
    req.text = "Import Data"

    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")

    request_desc = ET.SubElement(import_data, "REQUESTDESC")
    report_name = ET.SubElement(request_desc, "REPORTNAME")
    report_name.text = "Vouchers"
    static_vars = ET.SubElement(request_desc, "STATICVARIABLES")
    company = ET.SubElement(static_vars, "SVCURRENTCOMPANY")
    company.text = company_name
    if username:
        uname = ET.SubElement(static_vars, "SVOWNERNAME")
        uname.text = username
    if password:
        pwd = ET.SubElement(static_vars, "SVOWNERPASSWORD")
        pwd.text = password

    request_data = ET.SubElement(import_data, "REQUESTDATA")

    for voucher in vouchers:
        tally_msg = ET.SubElement(request_data, "TALLYMESSAGE")
        tally_msg.set("xmlns:UDF", "TallyUDF")
        vch_el = _build_voucher_element(voucher)
        tally_msg.append(vch_el)

    ET.indent(envelope, space="  ")
    xml_str = ET.tostring(envelope, encoding="unicode", xml_declaration=False)
    xml_str = xml_str.replace("&amp;#4;", "&#4;")
    return xml_str


def build_debit_note_xml(payload: CreateDebitNotePayload) -> str:
    """Build complete Tally XML envelope for debit note vouchers."""
    return _build_envelope(
        payload.company_name,
        payload.username,
        payload.password,
        payload.vouchers,
    )


def build_credit_note_xml(payload: CreateCreditNotePayload) -> str:
    """Build complete Tally XML envelope for credit note vouchers."""
    return _build_envelope(
        payload.company_name,
        payload.username,
        payload.password,
        payload.vouchers,
    )
