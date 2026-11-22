# -*- coding: utf-8 -*-
"""MOCK training data for the scam classifier (all invented, no real messages).

Each template is one wording. Placeholders: {phone} {amount} {fee} {link} {case} {ref}.
The train script holds some templates OUT of training and tests on them, so the reported
numbers measure 'wording the model never saw', not memorised sentences.
"""
import random

URDU_SCAM = [
    "آپ کی امدادی رقم روک دی گئی ہے۔ اسے جاری کرنے کے لیے فوراً اپنا شناختی کارڈ نمبر اور پن کوڈ اس نمبر پر بھیجیں {phone}",
    "مبارک ہو! آپ نے {amount} روپے کا انعام جیت لیا ہے۔ رقم حاصل کرنے کے لیے اس لنک پر کلک کریں {link}",
    "آپ کا بینظیر انکم سپورٹ کا اکاؤنٹ بلاک ہو جائے گا۔ ابھی اپنا او ٹی پی کوڈ بتائیں",
    "فوری اطلاع: رقم وصول کرنے کے لیے پہلے {fee} روپے ایزی پیسہ کریں {phone}",
    "آپ کا شناختی کارڈ منسوخ ہونے والا ہے۔ تصدیق کے لیے اس لنک پر اپنی تفصیلات درج کریں {link}",
    "میں بینک سے بول رہا ہوں، آپ کے اکاؤنٹ میں مسئلہ ہے، اپنا پاس ورڈ اور او ٹی پی بھیجیں",
    "احساس پروگرام کی طرف سے {amount} روپے منظور ہو گئے ہیں۔ رجسٹریشن فیس {fee} روپے جاز کیش پر بھیجیں",
    "آج ہی آخری موقع! اپنی رقم لینے کے لیے ابھی کال کریں {phone} ورنہ آپ کا نام فہرست سے نکال دیا جائے گا",
    "آپ کا کیس منظور ہو گیا ہے، رقم نکلوانے کے لیے اپنا کارڈ نمبر اور خفیہ نمبر ہمیں بتا دیں",
    "حکومت کی طرف سے خصوصی امداد۔ اپنا اکاؤنٹ نمبر اور پن بھیجیں تاکہ رقم منتقل ہو سکے",
    "آپ کی سم بلاک ہو رہی ہے، فوراً اس نمبر پر رابطہ کریں {phone} اور اپنا شناختی کارڈ نمبر بتائیں",
    "لاٹری جیتنے پر مبارک! انعام {amount} روپے۔ ٹیکس کی ادائیگی کے لیے {fee} روپے بھیجیں",
    "آپ کے اکاؤنٹ سے مشکوک لین دین ہوا ہے۔ اکاؤنٹ بچانے کے لیے ابھی اپنا پن بھیجیں",
    "رقم کی وصولی کے لیے اس نمبر پر واٹس ایپ کریں {phone} اور اپنے شناختی کارڈ کی تصویر بھیجیں",
    "آپ کو سرکاری وظیفہ ملا ہے! رقم حاصل کرنے کے لیے یہاں کلک کریں {link} اور اپنا اکاؤنٹ نمبر لکھیں",
    "ابھی {fee} روپے بھیج دیں ورنہ آپ کی امداد ہمیشہ کے لیے بند ہو جائے گی {phone}",
]
URDU_OK = [
    "آپ کی درخواست نمبر {case} موصول ہو گئی ہے۔ ہم جلد آپ کو آگاہ کریں گے۔",
    "آپ کی امدادی رقم {amount} روپے منظور ہو گئی ہے۔ رقم آپ کے رجسٹرڈ اکاؤنٹ میں منتقل کر دی جائے گی۔ کسی کو اپنا پن یا او ٹی پی نہ بتائیں۔",
    "آپ کا کیس افسر کے پاس جائزے کے لیے بھیج دیا گیا ہے۔ برائے مہربانی انتظار کریں۔",
    "برائے مہربانی اپنا شناختی کارڈ دفتر آتے وقت ساتھ لائیں۔ دفتر کا وقت صبح نو بجے سے شام پانچ بجے تک ہے۔",
    "یاد دہانی: کل صبح دس بجے آپ کی ملاقات ضلعی دفتر میں ہے۔",
    "آپ کی ادائیگی کامیابی سے ہو گئی ہے۔ حوالہ نمبر {ref}۔",
    "خبردار: سرکاری ادارہ آپ سے کبھی پن، پاس ورڈ یا او ٹی پی نہیں مانگتا۔ ایسے پیغامات سے ہوشیار رہیں۔",
    "آپ کے کاغذات میں تصویر واضح نہیں ہے۔ برائے مہربانی دوبارہ صاف تصویر بھیجیں۔",
    "آپ کی رقم کی ادائیگی کی حالت: زیر جائزہ۔ مزید معلومات کے لیے دفتر سے رابطہ کریں۔",
    "آپ کا کیس بند کر دیا گیا ہے کیونکہ ادائیگی مکمل ہو چکی ہے۔",
    "ہمیں آپ کے نام کی تصدیق کے لیے مزید دستاویز درکار ہے۔ برائے مہربانی دفتر میں افسر سے ملیں۔",
    "آپ کی درخواست پر افسر نے نظرثانی کی ہے اور آپ کو دفتر بلایا گیا ہے۔",
    "آپ کے کیس کی حیثیت: زیر کارروائی۔ کوئی رقم ادا کرنے کی ضرورت نہیں۔",
    "سرکاری رقم ہمیشہ آپ کے اپنے بینک اکاؤنٹ میں آتی ہے۔ کسی کو فیس نہ دیں۔",
    "آپ کی ملاقات کا وقت تبدیل کر دیا گیا ہے۔ نیا وقت کل دوپہر دو بجے ہے۔",
    "شکریہ، آپ کی دستاویزات کامیابی سے جمع ہو گئی ہیں۔ کیس نمبر {case}۔",
]
ROMAN_SCAM = [
    "aapki imdadi raqam rok di gayi hai. isay release karne ke liye foran apna CNIC number aur PIN is number par bhejein {phone}",
    "mubarak ho! aap ne {amount} rupay ka inaam jeet liya hai. raqam hasil karne ke liye is link par click karein {link}",
    "aapka BISP account block hone wala hai. abhi apna OTP code bataein",
    "raqam wasool karne ke liye pehle {fee} rupay easypaisa karein {phone}",
    "aapka shanakhti card mansookh hone wala hai. tasdeeq ke liye is link par details darj karein {link}",
    "main bank se bol raha hoon, aapke account mein masla hai, apna password aur OTP bhejein",
    "Ehsaas program ki taraf se {amount} rupay manzoor ho gaye hain. registration fee {fee} rupay jazzcash par bhejein",
    "aaj hi aakhri moqa! apni raqam lene ke liye abhi call karein {phone} warna aapka naam list se nikal diya jaye ga",
    "aapka case manzoor ho gaya hai, raqam nikalwane ke liye apna card number aur secret PIN humein bata dein",
    "sarkar ki taraf se khaas imdad. apna account number aur PIN bhejein taake raqam transfer ho sake",
    "aapki SIM block ho rahi hai, foran is number par rabta karein {phone} aur apna CNIC number batayen",
    "lottery jeetne par mubarak! inaam {amount} rupay. tax ada karne ke liye {fee} rupay bhejein",
]
ROMAN_OK = [
    "aapki darkhwast number {case} mosool ho gayi hai. hum jald aapko ittila denge.",
    "aapki imdadi raqam {amount} rupay manzoor ho gayi hai. raqam aapke registered account mein muntaqil kar di jayegi. kisi ko apna PIN ya OTP na batayen.",
    "aapka case officer ke paas jaiza ke liye bhej diya gaya hai. barae meherbani intezar karein.",
    "barae meherbani apna shanakhti card daftar aate waqt saath layen. daftar ka waqt subah 9 se shaam 5 baje tak hai.",
    "yaad dehani: kal subah 10 baje aapki mulaqat zilai daftar mein hai.",
    "aapki adaigi kamyabi se ho gayi hai. hawala number {ref}.",
    "khabardar: sarkari idara aap se kabhi PIN, password ya OTP nahi mangta. aise paighamat se hoshiyar rahein.",
    "aapke kaghazat mein tasveer wazeh nahi hai. barae meherbani dobara saaf tasveer bhejein.",
    "aapki raqam ki adaigi ki halat: zer-e-jaiza. mazeed maloomat ke liye daftar se rabta karein.",
    "aapka case band kar diya gaya hai kyunke adaigi mukammal ho chuki hai.",
    "humein aapke naam ki tasdeeq ke liye mazeed dastaweez darkar hai. barae meherbani daftar mein officer se milein.",
    "aapki darkhwast par officer ne nazar-e-sani ki hai aur aapko daftar bulaya gaya hai.",
]

# Fresh sentences written separately from the templates, never used for training.
HANDWRITTEN_TEST = [
    ("پیارے صارف آپ کا ایزی پیسہ اکاؤنٹ بند ہونے والا ہے، اپنا پن بھیجیں", 1),
    ("آپ کے نام پر 25000 کی رقم آئی ہے، وصول کرنے کے لیے کارڈ نمبر بتائیں", 1),
    ("بی آئی ایس پی کی جانب سے رقم کے لیے 500 روپے جاز کیش کریں", 1),
    ("آپ کا انعامی کوپن نکل آیا ہے، دعویٰ کرنے کے لیے لنک کھولیں http://bit.ly/x9k2", 1),
    ("aap ka inaami coupon nikal aaya hai, claim karne ke liye link kholein", 1),
    ("aapka easypaisa account band ho jayega, abhi apna PIN is number par bhejein 03001234567", 1),
    ("آپ کا کیس منظور ہو گیا، رقم دو دن میں آپ کے اکاؤنٹ میں آ جائے گی", 0),
    ("کل دفتر آتے وقت اصل شناختی کارڈ ساتھ لائیں", 0),
    ("آپ کی درخواست کا جائزہ لیا جا رہا ہے، شکریہ", 0),
    ("کسی کو اپنا او ٹی پی نہ دیں، ہمارا عملہ کبھی نہیں مانگتا", 0),
    ("aapka form jama ho gaya hai, shukriya", 0),
    ("kisi ko apna OTP na dein, hamara staff kabhi nahi mangta", 0),
    ("kal subah daftar aayein, officer aap se milna chahte hain", 0),
]

_PREFIX = {"ur": ["", "", "السلام علیکم! ", "اطلاع: ", "🔔 "], "ro": ["", "", "salam, ", "alert: ", "IMPORTANT: "]}
_SUFFIX = ["", "", " شکریہ", " 🙏"]


def _fill(tpl: str, rng: random.Random) -> str:
    vals = {
        "phone": rng.choice([f"03{rng.randint(0, 4)}{rng.randint(0, 9)}-{rng.randint(1000000, 9999999)}",
                             f"03{rng.randint(0, 4)}{rng.randint(0, 9)}{rng.randint(1000000, 9999999)}"]),
        "amount": str(rng.choice([5000, 10000, 12000, 20000, 25000, 50000, 100000])),
        "fee": str(rng.choice([200, 300, 500, 1000, 1500])),
        "link": rng.choice([f"http://bit.ly/{rng.randint(10000, 99999)}", "https://bisp-claim.xyz/get",
                            "http://relief-pay.top/x", "www.ehsaas-help.cc"]),
        "case": f"LM-{rng.randint(1000, 9999)}",
        "ref": f"TX{rng.randint(100000, 999999)}",
    }
    return tpl.format(**vals)


def build(variants_per_template: int = 12, seed: int = 7):
    """Returns list of (text, label, template_id). label 1 = scam, 0 = genuine."""
    rng = random.Random(seed)
    rows = []
    groups = [(URDU_SCAM, 1, "ur"), (URDU_OK, 0, "ur"), (ROMAN_SCAM, 1, "ro"), (ROMAN_OK, 0, "ro")]
    for templates, label, lang in groups:
        for i, tpl in enumerate(templates):
            for _ in range(variants_per_template):
                text = rng.choice(_PREFIX[lang]) + _fill(tpl, rng)
                if lang == "ur":
                    text += rng.choice(_SUFFIX)
                else:
                    text = text.upper() if rng.random() < 0.1 else text
                rows.append((text, label, f"{lang}-{label}-{i}"))
    return rows


def is_test_template(template_id: str) -> bool:
    """Every 4th template (per language and class) is held out for testing."""
    return int(template_id.rsplit("-", 1)[1]) % 4 == 3