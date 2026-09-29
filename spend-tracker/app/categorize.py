"""Transaction categorization. Precedence: manual > user rules > built-in keywords > Plaid > Other."""

CATEGORIES = [
    "Groceries", "Dining", "Transport", "Shopping", "Bills & Utilities", "Housing",
    "Health", "Entertainment", "Travel", "Subscriptions", "Fees", "Education",
    "Income", "Transfers", "Other",
]
NON_SPEND = ("Income", "Transfers")

# Built-in keyword rules (first match wins, so order specific -> general).
KEYWORDS = [
    ("Subscriptions", ["netflix", "spotify", "hulu", "disney+", "apple.com/bill", "youtube premium",
                       "icloud", "adobe", "dropbox", "chatgpt", "openai", "patreon", "audible"]),
    ("Groceries", ["whole foods", "trader joe", "safeway", "kroger", "costco", "aldi", "walmart grocery",
                   "loblaws", "sobeys", "metro ", "no frills", "instacart", "publix", "h-e-b", "wegmans"]),
    ("Dining", ["starbucks", "mcdonald", "chipotle", "doordash", "uber eats", "ubereats", "grubhub",
                "skip the dishes", "tim hortons", "subway", "domino", "pizza", "restaurant", "cafe",
                "coffee", "dunkin", "taco bell", "chick-fil-a", "panera"]),
    ("Transport", ["uber", "lyft", "shell", "chevron", "exxon", "bp ", "petro", "esso", "transit",
                   "presto", "mta", "bart", "parking", "toll", "metro card"]),
    ("Travel", ["airlines", "airbnb", "expedia", "booking.com", "delta", "united air", "air canada",
                "westjet", "marriott", "hilton", "hotel", "hertz", "avis"]),
    ("Bills & Utilities", ["comcast", "xfinity", "verizon", "at&t", "t-mobile", "rogers", "bell ", "telus",
                           "con edison", "pg&e", "hydro", "electric", "water bill", "internet", "insurance",
                           "geico", "state farm"]),
    ("Housing", ["rent", "mortgage", "property tax", "hoa "]),
    ("Health", ["pharmacy", "cvs", "walgreens", "rite aid", "shoppers drug", "clinic", "dental",
                "hospital", "gym", "fitness", "doctor"]),
    ("Entertainment", ["cinema", "amc ", "cineplex", "ticketmaster", "steam", "playstation", "xbox",
                       "nintendo", "concert"]),
    ("Shopping", ["amazon", "target", "best buy", "ikea", "home depot", "etsy", "ebay", "nike", "zara",
                  "h&m", "apple store", "walmart"]),
    ("Fees", ["overdraft", "service fee", "monthly fee", "atm fee", "interest charge", "late fee"]),
    ("Education", ["tuition", "coursera", "udemy", "university", "college"]),
    ("Income", ["payroll", "direct dep", "salary", "paycheck"]),
    ("Transfers", ["transfer", "e-transfer", "zelle", "venmo", "cash app", "payment thank you", "autopay"]),
]

PLAID_PRIMARY = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfers",
    "TRANSFER_OUT": "Transfers",
    "LOAN_PAYMENTS": "Bills & Utilities",
    "BANK_FEES": "Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Housing",
    "MEDICAL": "Health",
    "PERSONAL_CARE": "Health",
    "GENERAL_SERVICES": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
    "TRANSPORTATION": "Transport",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Bills & Utilities",
}


def categorize(name: str, merchant: str | None, plaid_primary: str | None,
               plaid_detailed: str | None, rules: list[tuple[str, str]]) -> tuple[str, str]:
    """Return (category, source). `rules` is a list of (pattern, category) user rules."""
    text = f"{merchant or ''} {name or ''}".lower()

    for pattern, category in rules:
        if pattern.lower() in text:
            return category, "rule"

    for category, words in KEYWORDS:
        if any(w in text for w in words):
            return category, "rule"

    if plaid_detailed == "FOOD_AND_DRINK_GROCERIES":
        return "Groceries", "plaid"
    if plaid_primary in PLAID_PRIMARY:
        return PLAID_PRIMARY[plaid_primary], "plaid"

    return "Other", "default"
