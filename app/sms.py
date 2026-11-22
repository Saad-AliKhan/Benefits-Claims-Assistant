# -*- coding: utf-8 -*-
"""SMS updates (mock gateway: messages go to the sms_messages table; a real SMS / WhatsApp sender plugs in
here later). Every message ends with the same safety line, because these women get scam calls."""
from sqlalchemy.orm import Session

from app import audit
from app.models import SmsMessage, User

SAFETY = ("ہم کبھی پن، او ٹی پی یا پیسے نہیں مانگتے۔", "We never ask for a PIN, OTP or money.")

TEXTS = {
    "received": ("آپ کی درخواست نمبر {case} مل گئی ہے۔", "Your claim number {case} has been received."),
    "asked_for_proof": ("درخواست {case}: ہمیں ایک اور کاغذ چاہیے۔ ایپ کھولیں یا اس نمبر پر جواب دیں۔",
                        "Claim {case}: we need one more document. Open the app or reply to this number."),
    "with_officer": ("درخواست {case}: ایک افسر آپ کا کیس دیکھ رہا ہے۔ آپ کو کچھ نہیں کرنا۔",
                     "Claim {case}: an officer is checking your case. You do not need to do anything."),
    "paid": ("درخواست {case} منظور۔ {amount} روپے آپ کے اکاؤنٹ میں بھیج دیے گئے ہیں، {days} دن میں پہنچ جائیں گے۔ حوالہ {ref}۔",
             "Claim {case} approved. PKR {amount} has been sent to your account and will arrive within {days} days. Ref {ref}."),
    "payment_problem": ("درخواست {case} منظور ہے لیکن رقم نہیں بھیجی جا سکی۔ ایک افسر آپ سے رابطہ کرے گا۔",
                        "Claim {case} is approved but the money could not be sent. An officer will contact you."),
    "rejected": ("درخواست {case} منظور نہیں ہوئی۔ وجہ جاننے یا اپیل کے لیے افسر سے بات کریں۔",
                 "Claim {case} was not approved. Talk to an officer to know why or to appeal."),
    "officer_callback": ("درخواست {case}: ایک افسر جلد آپ کو فون کرے گا۔", "Claim {case}: an officer will call you soon."),
    "helper_visit": ("درخواست {case}: ایک مددگار آپ سے ملنے آئے گی۔", "Claim {case}: a helper will visit you."),
    "urgent": ("ہم نے آپ کی بات فوری طور پر افسر کو بھیج دی ہے۔ ہنگامی صورت میں 15 یا 1122 پر کال کریں۔",
               "We sent your message to an officer urgently. In an emergency call 15 or 1122."),
}


def send(db: Session, user: User | None, kind: str, case_id: int | None = None, **values) -> SmsMessage | None:
    if user is None:
        return None
    ur, en = TEXTS[kind]
    v = {"case": case_id or "", **values}
    msg = SmsMessage(user_id=user.id, case_id=case_id, phone=user.phone, kind=kind,
                     text_ur="آسرا: " + ur.format(**v) + " " + SAFETY[0],
                     text_en="Aasra: " + en.format(**v) + " " + SAFETY[1])
    db.add(msg)
    db.flush()
    audit.record(db, "sms.sent", actor_role=audit.ACTOR_SYSTEM, case_id=case_id,
                 details={"sms_id": msg.id, "kind": kind, "to_user": user.id})  # the text is not logged
    return msg
