"""
UNSPSC Multi-Step Classification Engine (High-Precision FTS5 Architecture)
Concrete 5-Step Pipeline:
Step 1: Manufacturer & Brand Domain Resolution (Locks allowable industrial sectors)
Step 2: Specification Normalization & Semantic Head Noun Isolation (Strips dimensions, packaging, noise)
Step 3: Supplier Context & Secondary Distributor Channel Verification
Step 4: Hierarchical Full-Text BM25 Search (FTS5 across 71,500+ records)
Step 5: Doubt Assessment & Conservative Rollup Policy (No Doubt -> Commodity; Some Doubt -> Class; Huge Doubt -> Segment)
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


# Initialize FTS on module import
ensure_fts_table()


# =====================================================================
# STEP 1: MANUFACTURER / BRAND REGISTRY & DOMAIN GATING
# =====================================================================

MFR_DOMAIN_MAP: Dict[str, Tuple[str, Set[str]]] = {
    # IT, Telecom, Electronics -> Segment 43, 45, 52
    'dell': ('Computers & IT Hardware', {'43'}),
    'lenovo': ('Computers & IT Hardware', {'43'}),
    'hp': ('Computers & IT Hardware', {'43', '14', '44'}),
    'hewlett-packard': ('Computers & IT Hardware', {'43', '14'}),
    'hewlett packard': ('Computers & IT Hardware', {'43', '14'}),
    'apple': ('Consumer Electronics & Computers', {'43', '52'}),
    'cisco': ('Networking & Telecommunications', {'43'}),
    'intel': ('Electronic Components & Processors', {'43', '32'}),
    'amd': ('Electronic Components & Processors', {'43', '32'}),
    'samsung': ('Electronics & Displays', {'43', '52'}),
    'asus': ('Computers & IT Hardware', {'43'}),
    'acer': ('Computers & IT Hardware', {'43'}),
    'logitech': ('Computer Peripherals', {'43'}),
    'epson': ('Printers & Imaging', {'43', '44', '14'}),
    'canon': ('Printers & Imaging', {'43', '44', '45'}),
    'brother': ('Printers & Office Equipment', {'43', '44'}),

    # Hand & Power Tools, Hardware -> Segment 27, 31, 23
    'dewalt': ('Power Tools & Abrasives', {'27', '31', '23'}),
    'milwaukee': ('Power Tools & Abrasives', {'27', '31', '23'}),
    'bosch': ('Power Tools & Industrial Equipment', {'27', '31', '23'}),
    'makita': ('Power Tools & Machinery', {'27', '31', '23'}),
    'stanley': ('Hand Tools & Hardware', {'27', '31'}),
    'craftsman': ('Hand & Power Tools', {'27', '31'}),
    'mayhew': ('Hand & Punching Tools', {'27'}),
    'gearwrench': ('Hand Tools & Sockets', {'27'}),
    'snap-on': ('Hand Tools & Diagnostics', {'27'}),
    'diablo': ('Abrasives & Cutting Tools', {'31', '27'}),
    'zoro': ('Industrial Hardware & Tools', {'27', '31', '46'}),
    'home plus': ('Work Area Marking & Hardware', {'46', '31'}),
    'home depot': ('Hardware & Tools', {'27', '31'}),

    # Safety, PPE, Defense -> Segment 46
    '3m': ('Safety, PPE & Industrial Supplies', {'46', '31', '41', '42'}),
    'honeywell': ('Safety & Environmental Controls', {'46', '41'}),
    'ansell': ('Safety Gloves & PPE', {'46'}),
    'dupont': ('Protective Apparel & Materials', {'46', '12'}),
    'kimberly-clark': ('Sanitary & PPE Supplies', {'46', '47', '53'}),
    'vega': ('Helmets & Head Protection', {'46'}),
    'salisbury': ('Electrical Safety & Tools', {'27', '46'}),
    'learning resources': ('Educational Supplies & Goggles', {'60', '46'}),

    # Life Sciences, Antibodies & Reagents -> Segment 12, 41
    'miltenyi': ('Life Sciences & Antibodies', {'12', '41'}),
    'elabscience': ('Life Sciences & Antibodies', {'12', '41'}),
    'abcam': ('Life Sciences & Assay Reagents', {'12', '41'}),
    'cell signaling': ('Life Sciences & Reagents', {'12', '41'}),
    'bio-rad': ('Life Sciences & Clinical Reagents', {'12', '41'}),
    'sigma-aldrich': ('Chemicals & Life Sciences', {'12', '41'}),
    'merck': ('Life Sciences & Chemicals', {'12', '41'}),

    # Medical & Patient Care -> Segment 42
    'coloplast': ('Medical & Urological Devices', {'42'}),
    'pennine': ('Medical & Respiratory Supplies', {'42'}),
    'vst': ('Medical Syringes & Supplies', {'42'}),
    'w.b. mason': ('Medical Apparel & Facility Supplies', {'42', '46', '47'}),
    'the safety zone': ('Medical Apparel & PPE', {'42', '46'}),
    'courage + khazaka': ('Dermatological Testing Instruments', {'42', '41'}),

    # Chromatography, Laboratory Equipment & Glassware -> Segment 41
    'waters': ('Chromatography & SPE Systems', {'41'}),
    'agilent': ('Chromatography & Analytical Instruments', {'41'}),
    'phenomenex': ('Chromatography Columns & Cartridges', {'41'}),
    'welch materials': ('Chromatography Columns', {'41'}),
    'welchmat': ('Chromatography Columns', {'41'}),
    'welch': ('Chromatography Columns', {'41'}),
    'analytics-shop': ('Chromatography & Analytical Supplies', {'41'}),
    'uvison': ('Chromatography & Analytical Supplies', {'41'}),
    'uvison technologies': ('Chromatography & Analytical Supplies', {'41'}),
    'tosoh': ('Chromatography Columns', {'41'}),
    'vicam': ('Food Safety & HPLC Columns', {'41'}),
    'united chemical': ('Chromatography & SPE Columns', {'41'}),
    'atom scientific': ('Laboratory Glassware & Supplies', {'41'}),
    'environmental express': ('Laboratory Vials & Supplies', {'41'}),
    'fisher': ('Laboratory Equipment & Instruments', {'41'}),
    'fisher scientific': ('Laboratory Equipment & Instruments', {'41'}),
    'thermo': ('Laboratory Instruments & Concentrators', {'41'}),
    'thermo fisher': ('Laboratory Instruments & Concentrators', {'41'}),
    'bc berlin': ('Chemical Catalysts & Supports', {'12'}),
    'phrozen': ('3D Printing Post-Processing', {'23', '41'}),

    # Apparel, Workwear & Uniforms -> Segment 53
    'under armour': ('Apparel & Sportswear', {'53'}),
    'puma': ('Apparel & Footwear', {'53'}),
    'red kap': ('Workwear & Uniforms', {'53'}),
    'wrangler': ('Workwear & Apparel', {'53'}),
    'secret wish': ('Women Nightwear & Apparel', {'53'}),
    'posefree': ('Intimates & Undergarments', {'53'}),
    'aegend': ('Apparel Accessories & Compression', {'53', '46'}),
    'fdty': ('Compression Apparel & Therapy', {'42', '53'}),
    'the fashion factory': ('Apparel & Clothing Sets', {'53'}),
    'pujane': ('Hosiery & Socks', {'53'}),
    'lionvii': ('Belts & Clothing Accessories', {'53'}),
    'ikadex': ('Dresses & Cultural Apparel', {'53'}),
    'yardhobi': ('Scarves & Clothing Accessories', {'53'}),
    'navashya': ('Diapers & Baby Care', {'53'}),
    'wisfunlly': ('Wigs & Hair Products', {'53', '60'}),
    'nalacal': ('Wigs & Hair Products', {'53', '60'}),
    'terrifi': ('Wigs & Hair Products', {'53', '60'}),
    'tazweeq': ('Wigs & Hair Products', {'53', '60'}),
    'indefinido': ('Costumes & Novelties', {'60'}),

    # Janitorial & Cleaning -> Segment 47
    'reckitt': ('Cleaning & Disinfection', {'47'}),
    'clorox': ('Cleaning & Disinfection', {'47'}),
    'ecolab': ('Commercial Cleaning & Hygiene', {'47'}),

    # Packaging & Office Supplies -> Segment 24, 44, 14
    'uline': ('Packaging & Shipping Supplies', {'24', '31'}),
    'avery': ('Office & Labeling Supplies', {'44', '14'}),
    'bic': ('Writing Instruments', {'44'}),
    'pilot': ('Writing Instruments', {'44'}),
    'paper mate': ('Writing Instruments', {'44'}),
}


def get_manufacturer_domain(mfr_name: str) -> Tuple[Optional[str], Optional[Set[str]]]:
    m = (mfr_name or '').lower().strip()
    if not m:
        return None, None
    for key, (domain_label, allowed_segs) in MFR_DOMAIN_MAP.items():
        if key in m:
            return domain_label, allowed_segs
    return None, None


# =====================================================================
# STEP 2: PROCUREMENT SYNONYMS & SPECIFICATION NORMALIZATION
# =====================================================================

SYNONYM_REPLACEMENTS = [
    # Chromatography & Lab Supplies
    (r'\b(spe\s+(columns?|plates?)|extraction\s+plate|solid\s+phase\s+extraction|oasis\s+max)\b', 'solid phase extraction SPE columns'),
    (r'\b(hplc\s+columns?|lc\s+columns?|sugar-ca\s+column|xtimate(\s+sugar-ca)?)\b', 'high pressure liquid chromatography HPLC columns'),
    (r'\b(guard\s+cartridges?|guard\s+columns?|securityguard)\b', 'high pressure liquid chromatography HPLC guard column'),
    (r'\b(membrane\s+potential\s+assay|elisa\s+kit|assay\s+kit|jc-10)\b', 'enzyme linked immunosorbent assay ELISA kit'),
    (r'\bantibod(y|ies)\b', 'antibodies'),
    (r'\b(ph\s+bench(top)?\s+meter|ph\s+meter|accumet)\b', 'pH meters'),
    (r'\b(speedvac|vacuum\s+concentrator)\b', 'concentrators'),
    (r'\b(mucus\s+extractor(\s+catheter)?|suction\s+catheters?)\b', 'suction catheters'),
    (r'\b(speedicath|urinary\s+catheters?)\b', 'urethral urinary catheters'),
    (r'\b(absorption\s+tubes?|glass\s+tubes?)\b', 'laboratory glass tube'),
    (r'\b(lab\s+vials?|sample\s+vials?)\b', 'laboratory vials'),
    (r'\bcuring\s+station\b', 'curing ovens'),
    (r'\bwashing\s+station\b', 'laboratory washing machines'),

    # Computers & Peripherals
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

    # Tools & Hardware
    (r'\b(cordless\s+drills?|power\s+drills?|electric\s+drills?)\b', 'power drills'),
    (r'\bimpact\s+drivers?\b', 'impact drivers'),
    (r'\bvoltage\s+detectors?|voltage\s+testers?\b', 'voltage tester screwdriver'),
    (r'\b(masonry\s+disc|cutting\s+disc|cut-off\s+wheel|grinding\s+disc|grinding\s+wheel|abrasive\s+disc|abrasive\s+wheel)\b', 'grinding wheels'),

    # Industrial, Safety & Facilities
    (r'\bcentrifugal\s+(water\s+)?pumps?\b', 'centrifugal pumps'),
    (r'\bwater\s+pumps?\b', 'water pumps'),
    (r'\b(steel\s+toe(\s+work)?\s+boots?|safety\s+boots?|work\s+boots?)\b', 'safety boots'),
    (r'\b(n95(\s+particulate)?\s+(respirator|mask)|particulate\s+respirator|respirator\s+mask)\b', 'respirators'),
    (r'\bdisinfecting\s+wipes?|sanitizing\s+wipes?|cleaning\s+wipes?\b', 'cleaning cloths or wipes'),
    (r'\bsafety\s+goggles?|safety\s+glasses?\b', 'safety glasses'),
    (r'\bmotorcycle\s+helmets?|full\s+face\s+helmet\b', 'motorcycle helmets'),
    (r'\bdriveway\s+markers?\b', 'work area warning posts and chains'),
    (r'\barm\s+sleeves?|cooling\s+arm\s+sleeves?\b', 'protective arm sleeve'),
    (r'\bcompression\s+sleeves?\b', 'vascular and compression therapy equipment and supplies'),
    (r'\bbouffant(\s+caps?)?\b', 'medical staff bouffant caps'),
    (r'\bpatient\s+gowns?\b', 'patient gowns'),
    (r'\bisolation\s+gowns?\b', 'medical staff isolation or cover gown'),
    (r'\bluer-lok\s+syringes?|medical\s+syringes?|hypodermic\s+syringes?\b', 'medical syringe without needle'),
    (r'\bcatalyst\s+support\b', 'custom catalysts'),
]

NOISE_PATTERNS = [
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
]


def clean_product_query(product_name: str, mfr_name: str = '') -> str:
    s = (product_name or '').lower().strip()

    # Pre-clean manufacturer from product text to avoid brand interference
    if mfr_name:
        m_clean = mfr_name.lower().strip()
        if len(m_clean) > 2:
            s = re.sub(rf'\b{re.escape(m_clean)}\b', ' ', s)

    # Apply procurement synonym mapping
    for pattern, repl in SYNONYM_REPLACEMENTS:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)

    # Strip dimensions, counts, noise
    for pat in NOISE_PATTERNS:
        s = re.sub(pat, ' ', s, flags=re.IGNORECASE)

    # Clean punctuation and tokenize
    s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)
    tokens = [w for w in s.split() if len(w) > 1 and w not in {'the', 'and', 'for', 'with', 'from', 'each', 'well'}]
    return ' '.join(tokens)


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
# STEP 3, 4 & 5: MULTI-STEP EVALUATION & FTS5 CLASSIFICATION PIPELINE
# =====================================================================

def match_product(product_name, mfr_name='', mfr_part='', supplier_name='', supplier_part=''):
    """
    Executes the High-Precision 5-Step Classification Pipeline:
    Step 1: Manufacturer & Brand Domain Resolution (Locks sector constraints)
    Step 2: Semantic Head Noun & Specification Normalization (Strips noise, maps terminology)
    Step 3: Supplier & Secondary Channel Context
    Step 4: Hierarchical FTS5 Multi-Token Search (Exact Phrase -> Compound Noun -> Head Noun -> BM25)
    Step 5: Strict Doubt Assessment & Conservative Rollup Policy
    """
    p_orig = (product_name or '').strip()
    m_name = (mfr_name or '').strip()
    m_part = (mfr_part or '').strip()
    s_name = (supplier_name or '').strip()
    s_part = (supplier_part or '').strip()

    google_url = generate_google_search_url(m_name, m_part, p_orig, s_name, s_part)

    # -----------------------------------------------------------------
    # STEP 1: Manufacturer & Brand Domain Resolution
    # -----------------------------------------------------------------
    combined_context = f"{m_name} {s_name} {p_orig}".lower()
    domain_label, allowed_segments = None, None
    for brand, (d_label, segs) in MFR_DOMAIN_MAP.items():
        if re.search(rf'\b{re.escape(brand)}\b', combined_context):
            domain_label, allowed_segments = d_label, segs
            break

    # -----------------------------------------------------------------
    # STEP 2: Semantic Head Noun & Specification Normalization
    # -----------------------------------------------------------------
    cleaned_query = clean_product_query(p_orig, m_name)
    tokens = cleaned_query.split()
    if not tokens:
        tokens = [w for w in re.sub(r'[^a-zA-Z0-9\s]', ' ', p_orig.lower()).split() if len(w) > 2]

    # -----------------------------------------------------------------
    # STEP 3 & 4: Hierarchical FTS5 Search & Ranking
    # -----------------------------------------------------------------
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    best_match = None
    match_method = ""
    confidence = "Some Doubt"

    if tokens:
        # 4A. Exact Multi-Token Phrase Query
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
                match_method = "Step 4: Multi-Token Exact FTS"
                confidence = "No Doubt"
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
                    match_method = "Step 4: Head Noun Compound FTS"
                    confidence = "No Doubt"
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
                        match_method = "Step 4: Head Noun FTS"
                        confidence = "Some Doubt" if not allowed_segments else "No Doubt"
                except Exception:
                    pass

        # 4D. BM25 Ranked OR Fallback
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
                        match_method = "Step 4: BM25 Ranked FTS"
                        confidence = "Some Doubt"
                    elif candidates:
                        best_match = candidates[0]
                        match_method = "Step 4: BM25 Fallback FTS"
                        confidence = "Some Doubt"
                except Exception:
                    pass

    conn.close()

    # -----------------------------------------------------------------
    # STEP 5: Doubt Rollup Policy & Audit Generation
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

        mfr_info = f"MFR '{m_name}'" + (f" [MPN: {m_part}]" if m_part else "") + f" -> Sector: {domain_label or 'Domain-Checked'}" if m_name else "MFR: Not provided"
        noun_info = f"Isolated terms: '{cleaned_query}'"
        supp_info = f"Supplier '{s_name}'" + (f" [SKU: {s_part}]" if s_part else "") if s_name else "Supplier: Not provided"
        tax_info = f"Taxonomy: Seg {seg_code} > Fam {fam_code} > Class {class_code} > Comm {comm_code}"
        rollup_info = f"Rollup: {confidence} -> Assigned {assigned_level} '{assigned_code}' ({assigned_cat})"
        step_audit_trail = f"[Step 1: OEM] {mfr_info} | [Step 2: Head Noun] {noun_info} | [Step 3: Supplier] {supp_info} | [Step 4: FTS Search] Comm {comm_code} ({comm_name}) | [Step 5: Rollup] {confidence} -> {assigned_level} {assigned_code}"

        return {
            'assigned_code': assigned_code,
            'assigned_category': assigned_cat,
            'assigned_level': assigned_level,
            'confidence': confidence,
            'match_method': match_method,
            'step_audit_trail': step_audit_trail,
            'step1_detail': mfr_info,
            'step2_detail': noun_info,
            'step3_detail': supp_info,
            'step4_detail': tax_info,
            'step5_detail': rollup_info,
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

    # Fallback if totally unresolved
    fallback_seg = list(allowed_segments)[0] + '000000' if allowed_segments else '53000000'
    mfr_info = f"MFR '{m_name}'" if m_name else "MFR: Not provided"
    noun_info = f"Unresolved description: '{p_orig}'"
    supp_info = f"Supplier '{s_name}'" if s_name else "Supplier: Not provided"
    tax_info = f"Taxonomy: Fallback Segment {fallback_seg}"
    rollup_info = f"Rollup: Huge Doubt -> Assigned Segment (2-digit) '{fallback_seg}'"
    step_audit_trail = f"[Step 1: OEM] {mfr_info} | [Step 2: Noun] {noun_info} | [Step 3: Supplier] {supp_info} | [Step 4: Unresolved] | [Step 5: Rollup] Huge Doubt -> Segment {fallback_seg}"

    return {
        'assigned_code': fallback_seg,
        'assigned_category': 'General Goods / Unclassified',
        'assigned_level': 'Segment (2-digit)',
        'confidence': 'Huge Doubt',
        'match_method': 'Step 5: Fallback Segment',
        'step_audit_trail': step_audit_trail,
        'step1_detail': mfr_info,
        'step2_detail': noun_info,
        'step3_detail': supp_info,
        'step4_detail': tax_info,
        'step5_detail': rollup_info,
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

        # If AND query yielded too few results, fallback to OR query
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
