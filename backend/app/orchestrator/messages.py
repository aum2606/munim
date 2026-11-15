"""Fixed replies for the cases where no model output should reach a customer: no grounded answer,
handoff, off-topic. Written per language so they are always on-brand and never hallucinated."""

_CANNED: dict[str, dict[str, str]] = {
    "confirm": {
        "en": "Thanks for asking! Let me confirm this with the team and get back to you shortly.",
        "hi": "आपके सवाल के लिए धन्यवाद! टीम से पूछकर आपको जल्दी ही बताया जाएगा।",
        "gu": "તમારા પ્રશ્ન બદલ આભાર! ટીમ સાથે ખાતરી કરીને તમને ટૂંક સમયમાં જણાવવામાં આવશે.",
        "hinglish": "Aapke sawaal ke liye thanks! Team se confirm karke aapko jaldi hi bataya jayega.",
        "gujlish": "Tamara sawal mate aabhar! Team sathe confirm kari ne tamne jaldi janavva ma avshe.",
    },
    "handoff": {
        "en": "I'm connecting you with our team. Someone will reply as soon as possible.",
        "hi": "मैं आपको हमारी टीम से जोड़ रहा हूँ। कोई जल्द से जल्द आपको जवाब देगा।",
        "gu": "હું તમને અમારી ટીમ સાથે જોડું છું. કોઈ શક્ય તેટલી વહેલી તકે જવાબ આપશે.",
        "hinglish": "Main aapko hamari team se connect kar raha hoon. Koi jaldi se jaldi reply karega.",
        "gujlish": "Hu tamne amari team sathe connect kari rahyo chhu. Koi jaldi thi jaldi reply karshe.",
    },
    "quote_pending": {
        "en": "Thanks! I've noted your requirements and the team will share an exact quotation shortly.",
        "hi": "धन्यवाद! आपकी ज़रूरतें नोट कर ली गई हैं, टीम जल्द ही सटीक कोटेशन भेजेगी।",
        "gu": "આભાર! તમારી જરૂરિયાતો નોંધી લીધી છે, ટીમ ટૂંક સમયમાં ચોક્કસ ક્વોટેશન મોકલશે.",
        "hinglish": "Thanks! Aapki requirements note kar li hain, team jaldi hi exact quotation bhejegi.",
        "gujlish": "Aabhar! Tamari requirements note kari lidhi chhe, team jaldi j exact quotation mokalshe.",
    },
    "off_topic": {
        "en": "Sorry, I can only help with questions about our products and services.",
        "hi": "माफ़ कीजिए, मैं सिर्फ़ हमारे प्रोडक्ट्स और सेवाओं के बारे में सवालों में मदद कर सकता हूँ।",
        "gu": "માફ કરશો, હું ફક્ત અમારી પ્રોડક્ટ્સ અને સેવાઓ વિશેના પ્રશ્નોમાં મદદ કરી શકું છું.",
        "hinglish": "Sorry, main sirf hamare products aur services ke baare mein sawaalon mein madad kar sakta hoon.",
        "gujlish": "Maaf karjo, hu fakt amara products ane services vishe na sawalo ma madad kari shaku chhu.",
    },
}


def canned(key: str, language: str) -> str:
    """The fixed message for `key` in the customer's language (English for anything else)."""
    return _CANNED[key].get(language, _CANNED[key]["en"])
