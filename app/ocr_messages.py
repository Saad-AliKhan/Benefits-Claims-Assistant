"""Citizen-facing 'please retake' messages for each BadImage reason, in English and Urdu.
The backend can show these directly or use the reason code to pick its own wording."""

RETAKE_MESSAGES = {
    "not_an_image": ("This file is not a photo. Please upload a JPG or PNG picture.",
                     "یہ فائل تصویر نہیں ہے۔ براہ کرم JPG یا PNG تصویر اپ لوڈ کریں۔"),
    "too_small": ("The photo is too small. Please take it closer to the document.",
                  "تصویر بہت چھوٹی ہے۔ براہ کرم دستاویز کے قریب سے تصویر لیں۔"),
    "blurry": ("The photo is blurry. Hold the phone still and try again.",
               "تصویر دھندلی ہے۔ فون کو ساکت رکھ کر دوبارہ تصویر لیں۔"),
    "glare": ("Light is reflecting on the document. Move away from the lamp or window and try again.",
              "دستاویز پر روشنی کی چمک ہے۔ لیمپ یا کھڑکی سے ہٹ کر دوبارہ تصویر لیں۔"),
    "no_text_found": ("No writing could be found. Make sure the document fills the photo.",
                      "تصویر میں کوئی تحریر نہیں ملی۔ دستاویز کو پوری تصویر میں رکھیں۔"),
    "not_a_death_certificate": ("This does not look like a death certificate. Please photograph the whole page.",
                                "یہ وفات سرٹیفکیٹ نہیں لگتا۔ براہ کرم پورے صفحے کی تصویر لیں۔"),
    "cut_off": ("Part of the page is cut off. Make sure the whole page, with all four edges, is in the photo.",
                "صفحے کا کچھ حصہ تصویر سے باہر ہے۔ پورا صفحہ چاروں کناروں سمیت تصویر میں لائیں۔"),
    "unreadable": ("The writing on the document could not be read. Take the photo again in good light, closer and straight.",
                   "دستاویز کی تحریر پڑھی نہیں جا سکی۔ اچھی روشنی میں، قریب سے اور سیدھی تصویر دوبارہ لیں۔"),
    "cnic_back_side": ("This is the back of the CNIC. Please photograph the front, the side with your photo.",
                       "یہ شناختی کارڈ کی پچھلی طرف ہے۔ براہ کرم سامنے والی طرف کی تصویر لیں، جس پر آپ کی تصویر ہے۔"),
    "cnic_front_not_found": ("The front of the CNIC could not be read. Photograph the side with your photo and "
                             "date of birth, flat and in good light.",
                             "شناختی کارڈ کا سامنے والا حصہ پڑھا نہیں جا سکا۔ تصویر اور تاریخ پیدائش والی طرف کی "
                             "سیدھی اور اچھی روشنی میں تصویر لیں۔"),
    "cnic_number_not_found": ("The CNIC number could not be found. Photograph the front of the card.",
                              "شناختی کارڈ نمبر نہیں ملا۔ کارڈ کے سامنے والے حصے کی تصویر لیں۔"),
    "cnic_number_unreadable": ("The CNIC number is not clear. Take the photo closer, in good light.",
                               "شناختی کارڈ نمبر واضح نہیں۔ اچھی روشنی میں قریب سے تصویر لیں۔"),
}
DEFAULT = ("The photo could not be read. Please take it again.",
           "تصویر پڑھی نہیں جا سکی۔ براہ کرم دوبارہ تصویر لیں۔")


def retake(reason: str, detail: str = "") -> dict:
    en, ur = RETAKE_MESSAGES.get(reason, DEFAULT)
    return {"code": "retake", "reason": reason, "message_en": en, "message_ur": ur, "detail": detail}
