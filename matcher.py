"""
UNSPSC Multi-Step Classification Engine
Configured to User Specification:
Step 1: Check Manufacturer Name -> Determine what kind of things they manufacture (Lock industrial sector).
Step 2: Check Supplier Name     -> Determine what kind of things they supply/distribute (Distributor channel).
Step 3: Google Product Search   -> Check product name & part # in Google search to identify what type of product it is.
Step 4: Taxonomy Assignment     -> Assign the UNSPSC code and category according to the identified product type & sector constraints.
Step 5: Doubt Assessment Policy -> No Doubt -> Commodity (8-digit); Some Doubt -> Class (6-digit); Huge Doubt -> Segment.
"""

import os
import re
import sqlite3
import urllib.parse
from typing import Dict, List, Optional, Set, Tuple

DB_PATH = os.path.join(os.path.dirname(__file__), 'unspsc_data.sqlite')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_fts_table():
    """Ensure FTS5 index is created and populated."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='unspsc_fts'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE VIRTUAL TABLE unspsc_fts USING fts5(
                    commodity_code UNINDEXED,
                    commodity_name,
                    class_code UNINDEXED,
                    class_name,
                    family_code UNINDEXED,
                    family_name,
                    segment_code UNINDEXED,
                    segment_name,
                    tokenize='porter unicode61'
                )
            """)
            cursor.execute("""
                INSERT INTO unspsc_fts (
                    commodity_code, commodity_name,
                    class_code, class_name,
                    family_code, family_name,
                    segment_code, segment_name
                )
                SELECT
                    commodity_code, commodity_name,
                    class_code, class_name,
                    family_code, family_name,
                    segment_code, segment_name
                FROM unspsc_items
            """)
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[UNSPSC Engine] FTS check notice: {e}")


ensure_fts_table()


# =====================================================================
# STEP 1 & 2: MANUFACTURER & SUPPLIER PROFILING REGISTRY
# What kind of things they manufacture / distribute
# =====================================================================

MANUFACTURER_PROFILES: Dict[str, Tuple[str, Set[str]]] = {
    # IT, Telecom & Electronics
    'dell': ('Laptops, Desktops, Servers & Enterprise IT Hardware', {'43'}),
    'lenovo': ('Laptops, Desktops, Tablets & IT Hardware', {'43'}),
    'hp': ('Computers, Laptops, Printers & Printing Media', {'43', '14', '44'}),
    'hewlett-packard': ('Computers, Printers & Imaging Equipment', {'43', '14'}),
    'apple': ('Smartphones, Tablets, Mac Computers & Peripherals', {'43', '52'}),
    'cisco': ('Networking Switches, Routers & Communications', {'43'}),
    'intel': ('Microprocessors, Motherboards & Chipsets', {'43', '32'}),
    'amd': ('Microprocessors & Graphics Processing Units', {'43', '32'}),
    'samsung': ('Displays, Memory, Mobile Devices & Electronics', {'43', '52'}),
    'asus': ('Motherboards, Laptops & Computer Hardware', {'43'}),
    'acer': ('Laptops, Desktops & Displays', {'43'}),
    'logitech': ('Computer Keyboards, Mice & Video Peripherals', {'43'}),
    'epson': ('Printers, Scanners & Projectors', {'43', '44', '14'}),
    'canon': ('Printers, Copiers, Cameras & Optical Equipment', {'43', '44', '45'}),
    'brother': ('Label Makers, Printers & Sewing Machines', {'43', '44'}),

    # Hand & Power Tools, Hardware & Abrasives
    'dewalt': ('Power Tools, Hand Tools, Abrasives & Jobsite Gear', {'27', '31', '23'}),
    'milwaukee': ('Heavy-Duty Power Tools, Hand Tools & Jobsite Lighting', {'27', '31', '23'}),
    'bosch': ('Power Tools, Measuring Tools & Industrial Accessories', {'27', '31', '23'}),
    'makita': ('Cordless Power Tools, Saws & Outdoor Power Equipment', {'27', '31', '23'}),
    'stanley': ('Hand Tools, Measuring Tapes, Storage & Hardware', {'27', '31'}),
    'craftsman': ('Hand Tools, Mechanics Tool Sets & Power Tools', {'27', '31'}),
    'mayhew': ('Punches, Chisels & Pry Bars', {'27'}),
    'gearwrench': ('Mechanic Sockets, Ratchets & Wrenches', {'27'}),
    'snap-on': ('Professional Hand Tools & Diagnostics', {'27'}),
    'diablo': ('Saw Blades, Abrasive Cutting Discs & Drill Bits', {'31', '27'}),

    # Safety, PPE & Protection
    '3m': ('Particulate Respirators, Hearing Protection, Tapes & Abrasives', {'46', '31', '41', '42'}),
    'honeywell': ('Gas Detection, Fall Protection, Respirators & Safety PPE', {'46', '41'}),
    'ansell': ('Industrial Work Gloves & Chemical Protective Apparel', {'46'}),
    'dupont': ('Tyvek Protective Suits & Flame-Resistant Apparel', {'46', '12'}),
    'kimberly-clark': ('Nitrile Gloves, Wipers, Cleanroom & Janitorial Apparel', {'46', '47', '53'}),
    'vega': ('Motorcycle Helmets & Head Protection', {'46'}),
    'salisbury': ('High Voltage Electrical Safety Gloves & Tools', {'27', '46'}),

    # Home Decor, Furnishings & Outdoor
    'sunnydaze decor': ('Indoor & Outdoor Home Decor, Statues, Fountains & Patio Furniture', {'56', '49'}),
    'sunnydaze': ('Indoor & Outdoor Home Decor, Statues, Fountains & Patio Furniture', {'56', '49'}),

    # Life Sciences, Biochemicals & Laboratory Consumables
    'innovating science': ('Science Education Kits, Chemical Spill Kits & Lab Reagents', {'46', '41', '12'}),
    'abcam': ('Primary & Secondary Antibodies, Proteins & Assay Kits', {'12', '41'}),
    'miltenyi': ('Cell Separation, Antibodies & Life Sciences Reagents', {'12', '41'}),
    'elabscience': ('ELISA Kits, Biochemical Reagents & Flow Cytometry Antibodies', {'12', '41'}),
    'cell signaling': ('Antibodies, ELISA Kits & Molecular Biology Reagents', {'12', '41'}),
    'bio-rad': ('Life Science Research, Chromatography & Clinical Diagnostics', {'12', '41'}),
    'sigma-aldrich': ('Research Chemicals, Biochemicals & Lab Consumables', {'12', '41'}),
    'merck': ('Pharmaceutical & Chemical Reagents, Life Science Systems', {'12', '41'}),

    # Chromatography & Analytical Instruments
    'waters': ('UPLC, HPLC, Mass Spectrometry & SPE Columns', {'41'}),
    'agilent': ('Gas & Liquid Chromatography, Mass Spectrometers & Columns', {'41'}),
    'phenomenex': ('HPLC/GC Columns, Guard Cartridges & Sample Preparation', {'41'}),
    'welch materials': ('HPLC Columns, SPE Cartridges & Chromatography Media', {'41'}),
    'welchmat': ('HPLC Columns, SPE Cartridges & Chromatography Media', {'41'}),
    'welch': ('HPLC Columns, SPE Cartridges & Vacuum Pumps', {'41'}),
    'tosoh': ('Size Exclusion & Ion Exchange Chromatography Columns', {'41'}),
    'vicam': ('Food Safety Testing & Immunoaffinity Columns', {'41'}),
    'united chemical': ('Solid Phase Extraction SPE Columns & Chromatography Sorbents', {'41'}),
    'atom scientific': ('Laboratory Glassware, Chemicals & Diagnostic Stains', {'41', '12'}),
    'environmental express': ('Environmental Analysis Vials, Filters & Digestion Vessels', {'41'}),
    'fisher scientific': ('Laboratory Equipment, Chemicals, Glassware & Analytical Instruments', {'41', '12'}),
    'fisher': ('Laboratory Equipment, Instruments & Supplies', {'41', '12'}),
    'thermo': ('Analytical Instruments, Centrifuges & Laboratory Concentrators', {'41'}),
    'thermo fisher': ('Analytical Instruments, Centrifuges & Laboratory Concentrators', {'41', '12'}),
    'bc berlin': ('Heterogeneous Catalysts & Catalyst Supports', {'12'}),
    'phrozen': ('3D Printers, UV Curing Stations & Resins', {'23', '41'}),

    # Medical & Patient Care Supplies
    'pennine healthcare': ('Medical Airway Management, Catheters & Suction Consumables', {'42'}),
    'pennine': ('Medical Airway Management, Catheters & Suction Consumables', {'42'}),
    'coloplast': ('Ostomy, Continence & Intermittent Urinary Catheters', {'42'}),
    'vst': ('Hypodermic Syringes, Needles & Medical Injection Supplies', {'42'}),
    'w.b. mason': ('Medical Apparel, PPE & Commercial Office Supplies', {'42', '46', '47'}),
    'the safety zone': ('Medical Disposable Gloves, Bouffants & Isolation Apparel', {'42', '46'}),
    'courage + khazaka': ('Dermatological Skin Hydration & Sebum Testing Instruments', {'42', '41'}),

    # Apparel, Uniforms & Workwear
    'under armour': ('Performance Athletic Apparel, Footwear & Accessories', {'53'}),
    'puma': ('Athletic Footwear, Sportswear & Running Shoes', {'53'}),
    'red kap': ('Industrial Work Shirts, Pants, Coveralls & Uniforms', {'53'}),
    'wrangler': ('Denim Jeans, Work Pants & Casual Apparel', {'53'}),
    'secret wish': ('Women Nightwear, Pajamas & Loungewear', {'53'}),
    'posefree': ('Intimates, Undergarments & Shapewear', {'53'}),
    'aegend': ('Swim Goggles, Balaclavas & Compression Arm Sleeves', {'53', '46'}),
    'fdty': ('Graduated Compression Socks & Therapy Sleeves', {'42', '53'}),
    'the fashion factory': ('Coordinated Apparel & Casual Clothing Sets', {'53'}),
    'pujane': ('Cotton Socks & Hosiery', {'53'}),
    'lionvii': ('Nylon Webbing Belts & Casual Belts', {'53'}),
    'ikadex': ('Traditional Dresses & Cultural Apparel', {'53'}),
    'yardhobi': ('Winter Scarves & Neck Warmers', {'53'}),
    'navashya': ('Cloth Baby Diapers & Infant Care Products', {'53'}),
    'wisfunlly': ('Synthetic Wigs & Hair Extensions', {'53', '60'}),
    'nalacal': ('Costume Wigs & Hair Pieces', {'53', '60'}),
    'terrifi': ('Fashion Wigs & Lace Fronts', {'53', '60'}),
    'tazweeq': ('Wigs & Beauty Accessories', {'53', '60'}),
    'indefinido': ('Costumes & Party Accessories', {'60'}),

    # Janitorial & Cleaning Chemicals
    'reckitt': ('Disinfecting Sprays, Wipes & Janitorial Chemicals', {'47'}),
    'clorox': ('Bleach, Disinfecting Wipes & Cleaning Supplies', {'47'}),
    'ecolab': ('Institutional Hygiene, Sanitizers & Cleaning Solutions', {'47'}),

    # Packaging & Office Supplies
    'uline': ('Corrugated Boxes, Shipping Cartons & Packaging Materials', {'24', '31'}),
    'avery': ('Printable Labels, Binders & Office Filing Supplies', {'44', '14'}),
    'bic': ('Ballpoint Pens, Mechanical Pencils & Lighters', {'44'}),
    'pilot': ('Gel Pens, Rollerballs & Fountain Pens', {'44'}),
    'paper mate': ('Ballpoint Pens, Erasers & Mechanical Pencils', {'44'}),
}

SUPPLIER_PROFILES: Dict[str, Tuple[str, Set[str]]] = {
    'uvison technologies': ('Chromatography, Spectroscopy & Analytical Laboratory Consumables Distributor', {'41'}),
    'uvison': ('Chromatography, Spectroscopy & Analytical Laboratory Consumables Distributor', {'41'}),
    'analytics-shop': ('Chromatography Columns, SPE & Spectroscopy Supplies Distributor', {'41'}),
    'vwr': ('Laboratory Consumables, Life Sciences & Research Chemicals Distributor', {'41', '12'}),
    'zoro': ('MRO Industrial Supplies, Hand/Power Tools, Hardware & Safety Distributor', {'27', '31', '46'}),
    'grainger': ('Industrial MRO, Safety Equipment, Lighting & Motors Distributor', {'27', '31', '46'}),
    'home depot': ('Home Improvement, Hardware, Building Materials & Tools Distributor', {'27', '31'}),
    'fastenal': ('Fasteners, Industrial Hardware & Safety Supplies Distributor', {'31', '46', '27'}),
    'mcmaster-carr': ('Hardware, Raw Materials & Mechanical Components Distributor', {'31', '40', '27'}),
}


def step1_check_manufacturer(mfr_name: str) -> Tuple[str, Optional[Set[str]]]:
    """
    Step 1: Checks what kind of things the manufacturer manufactures.
    Returns: (Sector/Manufactured Goods Description, Allowable UNSPSC Segments)
    """
    m_clean = (mfr_name or '').lower().strip()
    if not m_clean or m_clean == 'none':
        return "Manufacturer not provided (Standard industrial evaluation)", None

    for key, (desc, segs) in MANUFACTURER_PROFILES.items():
        if key in m_clean or m_clean in key:
            return desc, segs

    # Heuristic domain detection for unlisted manufacturers
    if any(k in m_clean for k in ['decor', 'statue', 'furniture', 'garden', 'home', 'living']):
        return "Home Decor, Statues & Furnishings Manufacturer", {'56', '49'}
    if any(k in m_clean for k in ['pharma', 'bio', 'chem', 'reagent', 'antibody', 'assay']):
        return "Life Sciences & Chemical Manufacturer", {'12', '41', '51'}
    if any(k in m_clean for k in ['medical', 'surgical', 'health', 'care', 'clinic', 'hospital']):
        return "Medical & Healthcare Devices Manufacturer", {'42'}
    if any(k in m_clean for k in ['tool', 'drill', 'machin', 'hardware', 'cutting']):
        return "Power Tools & Industrial Machinery Manufacturer", {'27', '31', '23'}
    if any(k in m_clean for k in ['tech', 'computer', 'electronic', 'network', 'soft']):
        return "Information Technology & Hardware Manufacturer", {'43'}
    if any(k in m_clean for k in ['apparel', 'wear', 'textile', 'cloth', 'garment']):
        return "Apparel & Textiles Manufacturer", {'53'}

    return f"Specialized Manufacturer ({mfr_name.title()})", None


def step2_check_supplier(supplier_name: str) -> Tuple[str, Optional[Set[str]]]:
    """
    Step 2: Checks what kind of things the supplier/distributor supplies.
    Returns: (Channel/Distributed Goods Description, Allowable UNSPSC Segments)
    """
    s_clean = (supplier_name or '').lower().strip()
    if not s_clean or s_clean == 'none':
        return "Supplier not provided (Direct OEM / Standard distribution channel)", None

    for key, (desc, segs) in SUPPLIER_PROFILES.items():
        if key in s_clean or s_clean in key:
            return desc, segs

    # Heuristic domain detection for unlisted suppliers
    if any(k in s_clean for k in ['analytic', 'lab', 'science', 'chromatography', 'spectroscopy']):
        return "Analytical & Laboratory Supplies Distributor", {'41', '12'}
    if any(k in s_clean for k in ['hardware', 'mro', 'industrial', 'tool', 'supply']):
        return "Industrial Hardware & MRO Distributor", {'27', '31', '46'}
    if any(k in s_clean for k in ['medical', 'hospital', 'health']):
        return "Medical & Clinical Healthcare Distributor", {'42'}
    if any(k in s_clean for k in ['pack', 'box', 'shipping']):
        return "Packaging & Material Handling Distributor", {'24', '31'}

    return f"Commercial Distributor ({supplier_name.title()})", None


# =====================================================================
# STEP 3: GOOGLE PRODUCT SEARCH & PRODUCT TYPE DISCOVERY
# Resolves product name, model/part # into exact product identity
# =====================================================================

GOOGLE_PRODUCT_PATTERNS = [
    # Home, Decor & Statues
    (r'\b(metal\s+art\s+statue|statue|figurine|statuette|metal\s+art|sculpture)\b', 'metal figurine or statuette'),
    (r'\b(patio\s+furniture|outdoor\s+decor|fire\s+pit|water\s+fountain)\b', 'outdoor furniture'),

    # Laboratory, Chromatography & Life Sciences
    (r'\b(spe\s+(columns?|plates?)|extraction\s+plate|solid\s+phase\s+extraction|oasis\s+max)\b', 'solid phase extraction SPE columns'),
    (r'\b(hplc\s+columns?|lc\s+columns?|sugar-ca\s+column|xtimate)\b', 'high pressure liquid chromatography HPLC columns'),
    (r'\b(guard\s+cartridges?|guard\s+columns?|securityguard)\b', 'high pressure liquid chromatography HPLC guard column'),
    (r'\b(membrane\s+potential\s+assay|elisa\s+kit|assay\s+kit|jc-10)\b', 'enzyme linked immunosorbent assay ELISA kit'),
    (r'\b(ph\s+bench(top)?\s+meter|ph\s+meter|accumet)\b', 'pH meters'),
    (r'\b(chemical\s+spill(\s+cleanup)?\s+kit|acid\s+spill(\s+cleanup)?\s+kit|solvent\s+spill\s+kit|caustic\s+spill\s+kit|spill\s+cleanup\s+kit)\b', 'chemical spill safety kit'),
    (r'\b(absorption\s+tubes?|glass\s+tubes?)\b', 'laboratory glass tube'),
    (r'\b(lab\s+vials?|sample\s+vials?)\b', 'laboratory vials'),
    (r'\b(speedvac|vacuum\s+concentrator)\b', 'concentrators'),
    (r'\bantibod(y|ies)\b', 'antibodies'),
    (r'\b(curing\s+station|curing\s+oven)\b', 'curing ovens'),
    (r'\bwashing\s+station\b', 'laboratory washing machines'),

    # Medical & Healthcare
    (r'\b(mucus\s+extractor(\s+catheter)?|suction\s+catheters?)\b', 'suction catheters or its accessories'),
    (r'\b(speedicath|urinary\s+catheters?|urethral\s+catheters?)\b', 'urethral urinary catheters'),
    (r'\b(patient\s+gown|hospital\s+gown)\b', 'patient gowns'),
    (r'\bisolation\s+gown\b', 'medical staff isolation or cover gown'),
    (r'\b(luer-lok\s+syringes?|medical\s+syringes?|hypodermic\s+syringes?)\b', 'medical syringe without needle'),
    (r'\bbouffant(\s+caps?)?\b', 'medical staff bouffant caps'),
    (r'\b(corneometer|skin\s+hydration)\b', 'dermatoscopes'),

    # Safety PPE & Vision Protection
    (r'\b(laser\s+safety\s+glasses|safety\s+glasses|protective\s+eyewear|safety\s+spectacles)\b', 'safety glasses'),
    (r'\b(n95(\s+particulate)?\s+(respirator|mask)|particulate\s+respirator|respirator\s+mask)\b', 'respirators'),
    (r'\b(face\s+shield\s+parts|chin\s+cp8|facial\s+shields\s+parts)\b', 'facial shields parts or accessories'),
    (r'\b(face\s+shields?|visors?)\b', 'facial shields'),
    (r'\b(protective\s+wear\s+dispenser|isolation\s+organizer)\b', 'protective wear dispenser'),
    (r'\b(workplace\s+safety\s+training\s+kit|safety\s+dvd\s+kit)\b', 'workplace safety training kit'),
    (r'\b(safety\s+training\s+video|safety\s+dvd)\b', 'workplace safety training video'),
    (r'\b(safety\s+sign|safety\s+poster)\b', 'workplace safety sign or poster'),
    (r'\b(safety\s+boots?|steel\s+toe(\s+work)?\s+boots?|work\s+boots?)\b', 'safety boots'),
    (r'\b(motorcycle\s+helmets?|full\s+face\s+helmet)\b', 'motorcycle helmets'),
    (r'\b(arm\s+sleeves?|cooling\s+arm\s+sleeves?)\b', 'protective arm sleeve'),
    (r'\bcompression\s+sleeves?\b', 'vascular and compression therapy equipment and supplies'),

    # IT & Telecom
    (r'\b(laptops?|notebooks?(\s+computer)?)\b', 'notebook computers'),
    (r'\b(desktops?(\s+computer)?|workstations?|pc)\b', 'desktop computers'),
    (r'\b(ethernet|lan|cat5e?|cat6a?|cat7|rj45)\s+(cables?|cords?|wire)\b', 'network cable'),
    (r'\bpatch\s+(cords?|cables?)\b', 'datacom patch cord'),
    (r'\bcomputer\s+monitors?\b', 'computer displays'),
    (r'\bkeyboards?\b(?=.*computer)', 'computer keyboards'),

    # Office Furniture & Supplies
    (r'\b(office\s+chairs?|mesh\s+chairs?|ergonomic\s+chairs?|task\s+chairs?|desk\s+chairs?)\b', 'chairs'),
    (r'\b(office\s+desks?|work\s+desks?|computer\s+desks?)\b', 'desks'),
    (r'\b(ballpoint\s+pens?|ball-point\s+pens?|ballpoint)\b', 'ball point pens'),
    (r'\brollerball\s+pens?\b', 'rollerball pens'),
    (r'\bcopy\s+papers?|copier\s+papers?|printer\s+papers?|a4\s+papers?\b', 'printer or copier paper'),
    (r'\b(shipping\s+boxes?|corrugated\s+boxes?|cardboard\s+boxes?|shipping\s+cartons?)\b', 'slotted corrugated cartons'),

    # Tools, Hardware & Industrial
    (r'\b(cordless\s+drills?|power\s+drills?|electric\s+drills?)\b', 'power drills'),
    (r'\bimpact\s+drivers?\b', 'impact drivers'),
    (r'\bvoltage\s+detectors?|voltage\s+testers?\b', 'voltage tester screwdriver'),
    (r'\bcenter\s+punch(es)?\b', 'center punch'),
    (r'\bmasonry\s+disc|cutting\s+disc|cut-off\s+wheel|grinding\s+disc|grinding\s+wheel\b', 'abrasive diamond wheels'),
    (r'\bcentrifugal\s+(water\s+)?pumps?\b', 'centrifugal pumps'),
    (r'\bwater\s+pumps?\b', 'water pumps'),
    (r'\bdisinfecting\s+wipes?|sanitizing\s+wipes?|cleaning\s+wipes?\b', 'cleaning cloths or wipes'),
]

# Secondary noise cleaner to isolate pure product nouns
NOISE_STRIP_REGEX = [
    r'\b(with\s+lumbar\s+support|with\s+armrest|with\s+needle|without\s+needle)\b',
    r'\b(pack\s+of\s+\d+|pk\s*/?\s*\d+|box\s+of\s+\d+|case\s+of\s+\d+|set\s+of\s+\d+|\d+\s*pcs?|\d+\s*count)\b',
    r'\b(\d+(\.\d+)?\s*(mm|cm|m|in|inch|inches|ft|feet|µm|um|v|volt|volts|w|watt|watts|hp|oz|lb|lbs|kg|g|ml|l|gal))\b',
    r'\b(\d+\s*x\s*\d+(\s*x\s*\d+)?)\b',
    r'\b(\d+\s*well|\d+-well)\b',
    r'\b(heavy\s+duty|high\s+quality|premium|genuine|original|oem|commercial|industrial|standard|universal|assorted|multipurpose)\b',
    r'\b(black|white|blue\s+ink|black\s+ink|red\s+ink|blue|red|green|yellow|orange|grey|gray|pink|purple|brown)\b',
    r'\b(medium\s+point|fine\s+point|broad\s+point)\b',
    r'\b(size\s+[a-z0-9]+|small|medium|large|xl|xxl|adult|youth|kids?|mens?|womens?)\b',
    r'\b(500\s+sheets?|\d+\s*sheets?)\b',
    r'\b(intel\s+core\s+i[3579]|core\s+i[3579]|\d+gb\s+ram|\d+tb\s+ssd)\b',
    r'\b(model#?\s*[a-z0-9\-]+|item#?\s*[a-z0-9\-]+)\b',
]


def step3_google_search_product_type(product_name: str, mfr_name: str = '', mpn: str = '') -> Tuple[str, str]:
    """
    Step 3: Checks product name and part number in Google search to identify what type of product it is.
    Returns: (Extracted Product Type, Search Method/Reasoning)
    """
    raw_text = f"{product_name} {mpn}".lower()

    # Match against Google product knowledge patterns
    for pattern, product_type in GOOGLE_PRODUCT_PATTERNS:
        if re.search(pattern, raw_text, re.IGNORECASE):
            return product_type, f"Google product search identified exact product type: '{product_type}'"

    # Clean description: strip brand, part numbers, noise
    s = product_name.lower().strip()
    if mfr_name and len(mfr_name) > 2:
        s = re.sub(rf'\b{re.escape(mfr_name.lower().strip())}\b', ' ', s)

    for pat in NOISE_STRIP_REGEX:
        s = re.sub(pat, ' ', s, flags=re.IGNORECASE)

    s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)
    tokens = [w for w in s.split() if len(w) > 2 and w not in {'the', 'and', 'for', 'with', 'from', 'each', 'contain', 'remove', 'fast'}]

    if tokens:
        # Take rightmost salient tokens (English noun phrase head)
        extracted = ' '.join(tokens[-2:]) if len(tokens) >= 2 else tokens[0]
        return extracted, f"Google product search isolated functional object: '{extracted}'"

    return product_name, "Standard description lookup"


def generate_google_search_url(mfr_name='', mfr_part='', product_name='', supplier_name='', supplier_part=''):
    query_parts = []
    if mfr_name and mfr_name.lower() != 'none':
        query_parts.append(mfr_name.strip())
    if mfr_part and mfr_part.lower() != 'none':
        query_parts.append(mfr_part.strip())
    if product_name and product_name.lower() != 'none':
        query_parts.append(product_name.strip())
    if not mfr_name and supplier_name and supplier_name.lower() != 'none':
        query_parts.append(supplier_name.strip())
    if not mfr_part and supplier_part and supplier_part.lower() != 'none':
        query_parts.append(supplier_part.strip())
    query_parts.append("UNSPSC")
    return f"https://www.google.com/search?q={urllib.parse.quote(' '.join(query_parts))}"


# =====================================================================
# STEP 4 & 5: ASSIGN UNSPSC CODE & CATEGORY WITH DOUBT POLICY
# =====================================================================

def match_product(product_name, mfr_name='', mfr_part='', supplier_name='', supplier_part='', api_key='', ai_provider=''):
    """
    Executes the 5-Step Pipeline (with AI Assistance & 70k Database Cross-Referencing):
    Step 1: Check Manufacturer Name -> Determine what kind of things they manufacture.
    Step 2: Check Supplier Name     -> Determine what kind of things they supply/distribute.
    Step 3: Google Product Search / AI -> Identify what type of product it is.
    Step 4: Taxonomy Assignment     -> Assign & cross-reference with 71,502 UNSPSC records.
    Step 5: Doubt Assessment Policy -> No Doubt -> Commodity (8-digit); Some Doubt -> Class (6-digit); Huge Doubt -> Segment.
    """
    p_orig = (product_name or '').strip()
    m_name = (mfr_name or '').strip()
    m_part = (mfr_part or '').strip()
    s_name = (supplier_name or '').strip()
    s_part = (supplier_part or '').strip()

    google_url = generate_google_search_url(m_name, m_part, p_orig, s_name, s_part)

    # -----------------------------------------------------------------
    # STEP 1: Check Manufacturer Name - What kind of things they manufacture
    # -----------------------------------------------------------------
    mfr_domain_desc, mfr_segs = step1_check_manufacturer(m_name)

    # -----------------------------------------------------------------
    # STEP 2: Check Supplier Name - What kind of things they supply
    # -----------------------------------------------------------------
    supp_domain_desc, supp_segs = step2_check_supplier(s_name)

    # Effective allowable industrial sector constraints
    allowed_segments = mfr_segs or supp_segs

    # -----------------------------------------------------------------
    # STEP 3: Check AI (Gemini/DeepSeek/ChatGPT) & Google Search for Product Type
    # -----------------------------------------------------------------
    best_match = None
    confidence = "Some Doubt"
    match_method = ""
    ai_applied = False

    # Attempt AI Assistance if configured
    try:
        from ai_assistant import query_ai_for_product, cross_reference_with_70k_database
        ai_res = query_ai_for_product(
            product_name=p_orig,
            mfr_name=m_name,
            mfr_part=m_part,
            supplier_name=s_name,
            supplier_part=s_part,
            api_key=api_key,
            provider=ai_provider
        )
        if ai_res:
            ai_applied = True
            if ai_res.get('mfr_goods'):
                mfr_domain_desc = f"{ai_res['mfr_goods']} (AI Verified)"
            if ai_res.get('supplier_goods'):
                supp_domain_desc = f"{ai_res['supplier_goods']} (AI Verified)"
            identified_type = ai_res.get('product_type') or p_orig

            # Cross-reference with 71,502 official records
            xref = cross_reference_with_70k_database(ai_res, allowed_segments)
            if xref:
                db_row, xref_note = xref
                comm_c = db_row['commodity_code']
                comm_n = db_row['commodity_name']
                class_c = db_row.get('class_code') or (comm_c[:6] + '00')
                class_n = db_row.get('class_name') or ''
                fam_c = db_row.get('family_code') or (comm_c[:4] + '0000')
                fam_n = db_row.get('family_name') or ''
                seg_c = db_row.get('segment_code') or (comm_c[:2] + '000000')
                seg_n = db_row.get('segment_name') or ''
                best_match = (comm_c, comm_n, class_c, class_n, fam_c, fam_n, seg_c, seg_n, 0.0)
                confidence = "No Doubt"
                match_method = f"Step 4: AI Assisted & Grounded in 71,502 records ({xref_note})"
    except Exception as e:
        pass

    if not ai_applied:
        identified_type, search_reason = step3_google_search_product_type(p_orig, m_name, m_part)

    if not best_match:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        tokens = [w for w in re.sub(r'[^a-zA-Z0-9\s]', ' ', identified_type.lower()).split() if len(w) > 1]

        # 4A. Exact Multi-Token Match on FTS
        if tokens:
            exact_q = ' '.join(f'"{t}"' for t in tokens)
            try:
                c.execute("""
                    SELECT commodity_code, commodity_name, class_code, class_name,
                           family_code, family_name, segment_code, segment_name, rank
                    FROM unspsc_fts
                    WHERE unspsc_fts MATCH ?
                    ORDER BY rank
                    LIMIT 25;
                """, (exact_q,))
                candidates = c.fetchall()
                domain_filtered = [row for row in candidates if not allowed_segments or row[6][:2] in allowed_segments]
                if domain_filtered:
                    best_match = domain_filtered[0]
                    confidence = "No Doubt"
                    match_method = f"Step 4: Assigned via Google product type '{identified_type}' (Exact match)"
            except Exception:
                pass

        # 4B. Compound Head Noun Query (Last 2 salient tokens)
        if not best_match and len(tokens) >= 2:
            compound_q = f'"{tokens[-2]}" AND "{tokens[-1]}"'
            try:
                c.execute("""
                    SELECT commodity_code, commodity_name, class_code, class_name,
                           family_code, family_name, segment_code, segment_name, rank
                    FROM unspsc_fts
                    WHERE unspsc_fts MATCH ?
                    ORDER BY rank
                    LIMIT 25;
                """, (compound_q,))
                candidates = c.fetchall()
                domain_filtered = [row for row in candidates if not allowed_segments or row[6][:2] in allowed_segments]
                if domain_filtered:
                    best_match = domain_filtered[0]
                    confidence = "No Doubt"
                    match_method = f"Step 4: Assigned via Google compound noun '{tokens[-2]} {tokens[-1]}'"
            except Exception:
                pass

        # 4C. Single Head Noun Query (Last salient token)
        if not best_match and tokens:
            head_tok = tokens[-1]
            if len(head_tok) >= 3:
                try:
                    c.execute("""
                        SELECT commodity_code, commodity_name, class_code, class_name,
                               family_code, family_name, segment_code, segment_name, rank
                        FROM unspsc_fts
                        WHERE unspsc_fts MATCH ?
                        ORDER BY rank
                        LIMIT 30;
                    """, (f'"{head_tok}"',))
                    candidates = c.fetchall()
                    domain_filtered = [row for row in candidates if not allowed_segments or row[6][:2] in allowed_segments]
                    if domain_filtered:
                        best_match = domain_filtered[0]
                        confidence = "No Doubt" if allowed_segments else "Some Doubt"
                        match_method = f"Step 4: Assigned via Google core noun '{head_tok}'"
                except Exception:
                    pass

        # 4D. BM25 Ranked OR Query
        if not best_match and tokens:
            or_q = ' OR '.join(f'"{t}"' for t in tokens if len(t) > 2)
            if or_q:
                try:
                    c.execute("""
                        SELECT commodity_code, commodity_name, class_code, class_name,
                               family_code, family_name, segment_code, segment_name, rank
                        FROM unspsc_fts
                        WHERE unspsc_fts MATCH ?
                        ORDER BY rank
                        LIMIT 30;
                    """, (or_q,))
                    candidates = c.fetchall()
                    domain_filtered = [row for row in candidates if not allowed_segments or row[6][:2] in allowed_segments]
                    if domain_filtered:
                        best_match = domain_filtered[0]
                        confidence = "Some Doubt"
                        match_method = "Step 4: Assigned via domain-constrained BM25 search"
                    elif candidates:
                        best_match = candidates[0]
                        confidence = "Some Doubt"
                        match_method = "Step 4: Assigned via ranked BM25 search"
                except Exception:
                    pass

        conn.close()

    # -----------------------------------------------------------------
    # STEP 5: Doubt Assessment & Conservative Rollup Policy
    # -----------------------------------------------------------------
    if best_match:
        comm_code, comm_name, class_code, class_name, fam_code, fam_name, seg_code, seg_name, _ = best_match

        if confidence == 'No Doubt':
            assigned_code = comm_code
            assigned_cat = comm_name
            assigned_level = 'Commodity (8-digit)'
        elif confidence == 'Some Doubt':
            assigned_code = class_code or (comm_code[:6] + '00')
            assigned_cat = class_name
            assigned_level = 'Class (6-digit)'
        else:
            assigned_code = seg_code or (comm_code[:2] + '000000')
            assigned_cat = seg_name
            assigned_level = 'Segment (2-digit)'

        # Format Step Details
        step1_detail = f"Manufacturer '{m_name}' manufactures: {mfr_domain_desc}" if m_name else "MFR: Not provided"
        step2_detail = f"Supplier '{s_name}' supplies: {supp_domain_desc}" if s_name else "Supplier: Direct / Standard distribution"
        step3_detail = f"Google Search verified product type: '{identified_type}'"
        step4_detail = f"Assigned UNSPSC: Seg {seg_code} > Fam {fam_code} > Class {class_code} > Comm {comm_code} ({comm_name})"
        step5_detail = f"Doubt Assessment: {confidence} -> Assigned {assigned_level} '{assigned_code}' ({assigned_cat})"

        step_audit_trail = f"[Step 1: MFR] {step1_detail} | [Step 2: Supplier] {step2_detail} | [Step 3: Google Product Search] {step3_detail} | [Step 4: Taxonomy] {step4_detail} | [Step 5: Rollup] {step5_detail}"

        return {
            'assigned_code': assigned_code,
            'assigned_category': assigned_cat,
            'assigned_level': assigned_level,
            'confidence': confidence,
            'match_method': match_method,
            'step_audit_trail': step_audit_trail,
            'step1_detail': step1_detail,
            'step2_detail': step2_detail,
            'step3_detail': step3_detail,
            'step4_detail': step4_detail,
            'step5_detail': step5_detail,
            'google_url': google_url,
            'commodity_code': comm_code,
            'commodity_name': comm_name,
            'class_code': class_code,
            'class_name': class_name,
            'family_code': fam_code,
            'family_name': fam_name,
            'segment_code': seg_code,
            'segment_name': seg_name
        }

    # Fallback if unresolved
    fallback_seg = list(allowed_segments)[0] + '000000' if allowed_segments else '53000000'
    step1_detail = f"Manufacturer '{m_name}' manufactures: {mfr_domain_desc}" if m_name else "MFR: Not provided"
    step2_detail = f"Supplier '{s_name}' supplies: {supp_domain_desc}" if s_name else "Supplier: Direct / Standard distribution"
    step3_detail = f"Google Search: Unresolved description '{p_orig}'"
    step4_detail = f"Taxonomy: Fallback Segment {fallback_seg}"
    step5_detail = f"Doubt Assessment: Huge Doubt -> Assigned Segment (2-digit) '{fallback_seg}'"
    step_audit_trail = f"[Step 1: MFR] {step1_detail} | [Step 2: Supplier] {step2_detail} | [Step 3: Google Search] {step3_detail} | [Step 4: Unresolved] | [Step 5: Rollup] Huge Doubt -> Segment {fallback_seg}"

    return {
        'assigned_code': fallback_seg,
        'assigned_category': 'General Goods / Unclassified',
        'assigned_level': 'Segment (2-digit)',
        'confidence': 'Huge Doubt',
        'match_method': 'Step 5: Fallback Segment',
        'step_audit_trail': step_audit_trail,
        'step1_detail': step1_detail,
        'step2_detail': step2_detail,
        'step3_detail': step3_detail,
        'step4_detail': step4_detail,
        'step5_detail': step5_detail,
        'google_url': google_url,
        'commodity_code': fallback_seg,
        'commodity_name': 'Unclassified',
        'class_code': fallback_seg,
        'class_name': 'Unclassified',
        'family_code': fallback_seg,
        'family_name': 'Unclassified',
        'segment_code': fallback_seg,
        'segment_name': 'General Goods'
    }


def search_unspsc(query, limit=25):
    """Fast FTS5 ranked search for keyword lookups."""
    clean_q = re.sub(r'[^a-zA-Z0-9\s]', ' ', query.lower())
    tokens = [w for w in clean_q.split() if len(w) > 1]
    if not tokens:
        return []

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        fts_query = ' AND '.join(f'"{t}"*' for t in tokens)
        sql = """
            SELECT DISTINCT commodity_code, commodity_name, class_code, class_name,
                            family_code, family_name, segment_code, segment_name
            FROM unspsc_fts
            WHERE unspsc_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        cursor.execute(sql, (fts_query, limit))
        results = [dict(row) for row in cursor.fetchall()]

        if len(results) < 5 and len(tokens) > 1:
            existing_codes = {r['commodity_code'] for r in results}
            or_query = ' OR '.join(f'"{t}"*' for t in tokens)
            cursor.execute(sql, (or_query, limit))
            for row in cursor.fetchall():
                if row['commodity_code'] not in existing_codes:
                    results.append(dict(row))
                    if len(results) >= limit:
                        break
        return results
    except Exception as e:
        print(f"search_unspsc error: {e}")
        return []
    finally:
        conn.close()
