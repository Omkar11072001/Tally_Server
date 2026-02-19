from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from purchase_models import PurchaseVoucher

# Debit Note and Credit Note share the same XML structure as purchase/sales vouchers.
# The key difference is in the data: VOUCHERTYPENAME="Debit Note" / "Credit Note".
DebitNoteVoucher = PurchaseVoucher
CreditNoteVoucher = PurchaseVoucher


class CreateDebitNotePayload(BaseModel):
    company_name: str
    username: Optional[str] = None
    password: Optional[str] = None
    vouchers: list[DebitNoteVoucher]


class CreateCreditNotePayload(BaseModel):
    company_name: str
    username: Optional[str] = None
    password: Optional[str] = None
    vouchers: list[CreditNoteVoucher]
