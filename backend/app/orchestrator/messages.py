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
    "quote_sent": {
        "en": "Your quotation {number} is ready. Total: {total} (including GST). Valid until {valid}.",
        "hi": "आपका कोटेशन {number} तैयार है। कुल: {total} (GST सहित)। {valid} तक मान्य।",
        "gu": "તમારું ક્વોટેશન {number} તૈયાર છે. કુલ: {total} (GST સહિત). {valid} સુધી માન્ય.",
        "hinglish": "Aapka quotation {number} ready hai. Total: {total} (GST ke saath). {valid} tak valid.",
        "gujlish": "Tamaru quotation {number} ready chhe. Total: {total} (GST sathe). {valid} sudhi valid.",
    },
    "off_topic": {
        "en": "Sorry, I can only help with questions about our products and services.",
        "hi": "माफ़ कीजिए, मैं सिर्फ़ हमारे प्रोडक्ट्स और सेवाओं के बारे में सवालों में मदद कर सकता हूँ।",
        "gu": "માફ કરશો, હું ફક્ત અમારી પ્રોડક્ટ્સ અને સેવાઓ વિશેના પ્રશ્નોમાં મદદ કરી શકું છું.",
        "hinglish": "Sorry, main sirf hamare products aur services ke baare mein sawaalon mein madad kar sakta hoon.",
        "gujlish": "Maaf karjo, hu fakt amara products ane services vishe na sawalo ma madad kari shaku chhu.",
    },
    "followup": {
        "en": "Hello! Just checking in on quotation {number}. Happy to answer any questions or make changes.",
        "hi": "नमस्ते! कोटेशन {number} के बारे में पूछ रहे थे। कोई सवाल हो या बदलाव चाहिए तो बताइए।",
        "gu": "નમસ્તે! ક્વોટેશન {number} વિશે પૂછી રહ્યા હતા. કોઈ પ્રશ્ન હોય કે ફેરફાર જોઈએ તો જણાવો.",
        "hinglish": "Namaste! Quotation {number} ke baare mein pooch rahe the. Koi sawaal ho ya change chahiye to bataiye.",
        "gujlish": "Namaste! Quotation {number} vishe puchhi rahya hata. Koi sawal hoy ke fer-far joiye to janavjo.",
    },
    "unsupported": {
        "en": "Sorry, I can only read text messages and voice notes. Please type your question.",
        "hi": "माफ़ कीजिए, मैं सिर्फ़ टेक्स्ट मैसेज और वॉइस नोट समझ सकता हूँ। कृपया अपना सवाल लिखें।",
        "gu": "માફ કરશો, હું ફક્ત ટેક્સ્ટ મેસેજ અને વૉઇસ નોટ સમજી શકું છું. કૃપા કરી તમારો પ્રશ્ન લખો.",
        "hinglish": "Sorry, main sirf text message aur voice note samajh sakta hoon. Please apna sawaal type karein.",
        "gujlish": "Maaf karjo, hu fakt text message ane voice note samji shaku chhu. Krupa kari tamaro sawal lakho.",
    },
    "voice_failed": {
        "en": "Sorry, I could not understand that voice note. Could you type your message?",
        "hi": "माफ़ कीजिए, मैं यह वॉइस नोट समझ नहीं पाया। क्या आप अपना मैसेज लिख सकते हैं?",
        "gu": "માફ કરશો, હું આ વૉઇસ નોટ સમજી શક્યો નહીં. શું તમે તમારો સંદેશ લખી શકો?",
        "hinglish": "Sorry, main yeh voice note samajh nahi paaya. Kya aap apna message type kar sakte hain?",
        "gujlish": "Maaf karjo, hu aa voice note samji shakyo nahi. Shu tame tamaro message lakhi shako?",
    },
    "voice_confirm": {
        "en": 'I heard: "{heard}". Is that right? Reply yes, or type your message.',
        "hi": 'मैंने सुना: "{heard}"। क्या यह सही है? हाँ लिखें, या अपना मैसेज टाइप करें।',
        "gu": 'મેં સાંભળ્યું: "{heard}". શું આ સાચું છે? હા લખો, અથવા તમારો સંદેશ ટાઇપ કરો.',
        "hinglish": 'Maine suna: "{heard}". Kya yeh sahi hai? Haan likhein, ya apna message type karein.',
        "gujlish": 'Me sambhalyu: "{heard}". Shu aa sachu chhe? Ha lakho, athva tamaro message type karo.',
    },
}


def canned(key: str, language: str) -> str:
    """The fixed message for `key` in the customer's language (English for anything else)."""
    return _CANNED[key].get(language, _CANNED[key]["en"])


def quote_sent_message(language: str, number: str, total: str, valid: str) -> str:
    """The message that delivers an approved quotation. Every figure is passed in by code."""
    return canned("quote_sent", language).format(number=number, total=total, valid=valid)


def voice_confirm_message(language: str, heard: str) -> str:
    """Echo what a voice note sounded like so the customer can confirm it. The words are theirs."""
    return canned("voice_confirm", language).format(heard=heard)
