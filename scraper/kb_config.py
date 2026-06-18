# scraper/kb_config.py
from pathlib import Path
from scraper.config import STATE_DIR, LIBRARY_BASE

KB_SPACES: list[dict] = [
    # TradeDesk KB
    {"space_key": "SA",                 "display_name": "System Administration",       "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "system_administration"},
    {"space_key": "parameters",         "display_name": "Parameters",                  "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "parameters"},
    {"space_key": "Finance",            "display_name": "Finance",                     "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "finance"},
    {"space_key": "Dealing",            "display_name": "Dealing",                     "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "dealing"},
    {"space_key": "compliance",         "display_name": "Compliance",                  "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "compliance"},
    {"space_key": "Reports",            "display_name": "Reports",                     "product": "tradedesk",    "product_label": "TradeDesk KB",    "lib_folder": "reports"},
    {"space_key": "DistributionLayer",  "display_name": "FIX Protocol/Distribution Layer", "product": "tradedesk", "product_label": "TradeDesk KB",  "lib_folder": "fix_distribution_layer"},
    # Web 2.5 KB
    {"space_key": "administration", "display_name": "Administration",   "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "administration"},
    {"space_key": "beneficiaries",  "display_name": "Beneficiaries",    "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "beneficiaries"},
    {"space_key": "BookingDeals",   "display_name": "Booking Deals",    "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "booking_deals"},
    {"space_key": "dealinghistory", "display_name": "Dealing History",  "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "dealing_history"},
    {"space_key": "documents",      "display_name": "Documents",        "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "documents"},
    {"space_key": "GettingStarted", "display_name": "Getting Started",  "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "getting_started"},
    {"space_key": "howto",          "display_name": "How To's",         "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "how_to"},
    {"space_key": "MyAccount",      "display_name": "My Account",       "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "my_account"},
    {"space_key": "payments",       "display_name": "Payments",         "product": "web2", "product_label": "Web 2.5 KB", "lib_folder": "payments"},
    # Web 4.0 KB
    {"space_key": "BookingDealsWeb4",   "display_name": "Booking Deals",   "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "booking_deals"},
    {"space_key": "DealingHistoryWeb4", "display_name": "Dealing History", "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "dealing_history"},
    {"space_key": "MyAccountWeb4",      "display_name": "My Account",      "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "my_account"},
    {"space_key": "PaymentsWeb4",       "display_name": "Payments",        "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "payments"},
    {"space_key": "RecipientsWeb4",     "display_name": "Recipients",      "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "recipients"},
    # API KB
    {"space_key": "Functions",           "display_name": "API Functions",          "product": "api", "product_label": "API KB", "lib_folder": "functions"},
    {"space_key": "GS",                  "display_name": "Getting Started",        "product": "api", "product_label": "API KB", "lib_folder": "getting_started"},
    {"space_key": "API25ReleaseNotes",   "display_name": "API 2.5 Release Notes",  "product": "api", "product_label": "API KB", "lib_folder": "api_25_release_notes"},
    {"space_key": "apireleasenotes",     "display_name": "Release Notes",          "product": "api", "product_label": "API KB", "lib_folder": "release_notes"},
    {"space_key": "RestAPIReleaseNotes", "display_name": "REST API Release Notes", "product": "api", "product_label": "API KB", "lib_folder": "rest_api_release_notes"},
    # SalesHub KB
    {"space_key": "SHGettingStarted",  "display_name": "Getting Started",          "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "getting_started"},
    {"space_key": "SHBeneficiaries",   "display_name": "Beneficiaries",            "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "beneficiaries"},
    {"space_key": "SHAccounts",        "display_name": "Accounts",                 "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "accounts"},
    {"space_key": "SHAdministration",  "display_name": "Administration",           "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "administration"},
    {"space_key": "SHBookingDeals",    "display_name": "Booking Deals",            "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "booking_deals"},
    {"space_key": "SHDocuments",       "display_name": "Documents",                "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "documents"},
    {"space_key": "SHPayments",        "display_name": "Payments",                 "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "payments"},
    {"space_key": "SHHowTo",           "display_name": "How To's",                 "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "how_to"},
    {"space_key": "SHDealingHistory",  "display_name": "Dealing History",          "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "dealing_history"},
    {"space_key": "SHAPIReleaseNotes", "display_name": "SalesHub API Release Notes","product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "sh_api_release_notes"},
    # FormFlow KB
    {"space_key": "SFFormManagement",    "display_name": "Form Management",    "product": "formflow", "product_label": "FormFlow KB", "lib_folder": "form_management"},
    {"space_key": "SFHowTo",             "display_name": "How To's",           "product": "formflow", "product_label": "FormFlow KB", "lib_folder": "how_to"},
    {"space_key": "SFOpenForms",         "display_name": "Open Forms",         "product": "formflow", "product_label": "FormFlow KB", "lib_folder": "open_forms"},
    {"space_key": "SFUserAccessControl", "display_name": "User Access Control","product": "formflow", "product_label": "FormFlow KB", "lib_folder": "user_access_control"},
    {"space_key": "SFReleaseNotes",      "display_name": "Release Notes",      "product": "formflow", "product_label": "FormFlow KB", "lib_folder": "release_notes"},
    {"space_key": "FBD",                 "display_name": "Form Builder Docs",  "product": "formflow", "product_label": "FormFlow KB", "lib_folder": "form_builder_docs"},
    # Other
    {"space_key": "WebReleaseNotes", "display_name": "Web Release Notes", "product": "other", "product_label": "Other", "lib_folder": "web_release_notes"},
]

KB_SPACES_BY_KEY: dict[str, dict] = {s["space_key"]: s for s in KB_SPACES}

KB_PRODUCT_GROUPS: dict[str, list[dict]] = {}
for _s in KB_SPACES:
    KB_PRODUCT_GROUPS.setdefault(_s["product_label"], []).append(_s)

KB_ARTICLES_STATE_FILE: Path = STATE_DIR / "scraped_articles.json"
KB_LIBRARY_BASE: Path = LIBRARY_BASE / "kb"
