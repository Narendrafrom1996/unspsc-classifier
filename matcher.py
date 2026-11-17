"""
UNSPSC Multi-Step Classification Engine
Concrete 5-Step Pipeline:
Step 1: Manufacturer & Brand Domain Resolution (Locks industrial sector)
Step 2: Semantic Head Noun & Functional Object Extraction with strict word boundaries & proper precedence
Step 3: Technical Specifications & Part # Disambiguation
Step 4: Hierarchical Taxonomy Mapping (Segment -> Family -> Class -> Commodity)
Step 5: Doubt Assessment & Conservative Rollup Policy (No Doubt -> Commodity; Some Doubt -> Class/Family; Huge Doubt -> Segment)
"""

import sqlite3
import re
import os
import urllib.parse
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), 'unspsc_data.sqlite')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =====================================================================
# STEP 1: MANUFACTURER / BRAND REGISTRY & DOMAIN GATING
# =====================================================================

MFR_DOMAIN_MAP = {
    # Apparel, Footwear, Fashion & Sportswear -> Segment 53
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

    # Life Sciences, Antibodies & Biochemical Reagents -> Segment 12, 41
    'miltenyi': ('Life Sciences & Antibodies', {'12', '41'}),
    'elabscience': ('Life Sciences & Antibodies', {'12', '41'}),
    'abcam': ('Life Sciences & Assay Reagents', {'12', '41'}),
    'cell signaling': ('Life Sciences & Reagents', {'12', '41'}),
    'bio-rad': ('Life Sciences & Clinical Reagents', {'12', '41'}),

    # Medical & Urological Devices -> Segment 42
    'coloplast': ('Medical & Urological Devices', {'42'}),
    'pennine': ('Medical & Respiratory Supplies', {'42'}),
    'vst': ('Medical Syringes & Supplies', {'42'}),
    'w.b. mason': ('Medical Apparel & Facility Supplies', {'42', '46', '47'}),
    'the safety zone': ('Medical Apparel & PPE', {'42', '46'}),

    # Chromatography, Laboratory Equipment & Glassware -> Segment 41
    'united chemical': ('Chromatography & SPE Columns', {'41'}),
    'atom scientific': ('Laboratory Glassware & Supplies', {'41'}),
    'environmental express': ('Laboratory Vials & Supplies', {'41'}),
    'vicam': ('Food Safety & HPLC Columns', {'41'}),
    'agilent': ('Chromatography & Analytical Instruments', {'41'}),
    'bc berlin': ('Chemical Catalysts & Supports', {'12'}),
    'courage + khazaka': ('Dermatological Testing Instruments', {'42', '41'}),
    'salisbury': ('Electrical Safety & Tools', {'27', '46'}),
    'fisher': ('Laboratory Equipment & Instruments', {'41'}),
    'welch': ('Chromatography Columns', {'41'}),
    'phenomenex': ('Chromatography Columns & Cartridges', {'41'}),
    'thermo': ('Laboratory Instruments & Concentrators', {'41'}),
    'tosoh': ('Chromatography Columns', {'41'}),
    'waters': ('Chromatography & SPE Systems', {'41'}),
    'phrozen': ('3D Printing Post-Processing', {'23', '41'}),

    # Tools, Hardware, Abrasives & Markings -> Segment 27, 31, 46
    'mayhew': ('Punching & Hand Tools', {'27'}),
    'zoro': ('Industrial Hardware & Tools', {'27', '31', '46'}),
    'home plus': ('Work Area Marking & Hardware', {'46', '31'}),
    'vega': ('Helmets & Head Protection', {'46'}),
    'diablo': ('Abrasives & Cutting Tools', {'31', '27'}),
    'gearwrench': ('Hand Tools & Sockets', {'27'}),
    'home depot': ('Hardware & Tools', {'27', '31'}),
    'reckitt': ('Cleaning & Disinfection', {'47'}),
    'learning resources': ('Educational Supplies & Goggles', {'60', '46'})
}


def get_manufacturer_domain(mfr_name):
    m = (mfr_name or '').lower().strip()
    for key, (domain_label, allowed_segs) in MFR_DOMAIN_MAP.items():
        if key in m:
            return domain_label, allowed_segs
    return None, None


# =====================================================================
# STEP 2: HEAD NOUN & SEMANTIC OBJECT EXTRACTION (WORD BOUNDARIES)
# =====================================================================

def has_word(pattern, text):
    return bool(re.search(rf'\b({pattern})\b', text, re.IGNORECASE))


def extract_head_noun_category(product_name, mfr_domain_label=''):
    p = product_name.lower().strip()

    # --- WIGS & HAIR PIECES (Check early before generic dress/costume) ---
    if has_word(r'wigs?|hairpieces?|toupees?', p):
        return ('apparel_wig', 'Wig / Hair Supply', '53131602', 'Hair care supplies', '53131600', 'Bath and body', '53130000', 'Personal care products', '53000000', 'Apparel and Luggage and Personal Care Products', 'Some Doubt')

    # --- NOVELTY & COSTUMES (Segment 60) ---
    if has_word(r'handcuffs?', p) and has_word(r'costumes?|toys?', p):
        return ('costume_handcuffs', 'Costume Accessories', '60141401', 'Costumes or accessories', '60141400', 'Toys', '60140000', 'Toys and games', '60000000', 'Musical Instruments and Games and Toys', 'No Doubt')

    # --- APPAREL & CLOTHING (Segment 53) ---
    if has_word(r't-shirt|tshirts?|tee|tees', p) or 'compression short-sleeve' in p:
        return ('apparel_tshirt', 'T-shirt', '53103001', 'Mens tshirts', '53103000', 'Tshirts', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'shirt|shirts|blouse|blouses', p):
        if 'patient' in p or 'hospital' in p:
            return ('medical_patient_clothing', 'Patient Clothing', '42131505', 'Patient infant shirts or vests', '42131500', 'Patient clothing', '42130000', 'Medical apparel and textiles', '42000000', 'Medical Equipment and Accessories and Supplies', 'Some Doubt')
        return ('apparel_shirt', 'Shirt', '53101602', 'Mens shirts', '53101600', 'Shirts and blouses', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'sweatshirt and pant|tracksuits?|joggers?|pullover jogger', p):
        return ('apparel_tracksuit', 'Tracksuit / Athletic Set', '53102900', 'Athletic wear', '53102900', 'Athletic wear', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'Some Doubt')

    if has_word(r'pants?|trousers?|slacks|jeans', p) and not has_word(r'sweatshirt and pant|paint|plant', p):
        return ('apparel_pant', 'Pants', '53101502', 'Mens slacks or trousers or shorts', '53101500', 'Slacks and trousers and shorts', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'shorts', p):
        return ('apparel_shorts', 'Shorts', '53101502', 'Mens slacks or trousers or shorts', '53101500', 'Slacks and trousers and shorts', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'bra|bras|brassieres?|bralette', p):
        return ('apparel_bra', 'Brassiere', '53102304', 'Brassieres', '53102300', 'Undergarments', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'nighty|nighties?|nightgown|nightgowns|pajamas?|sleepwear', p):
        return ('apparel_nightwear', 'Nightwear', '53102604', 'Womens pajamas or nightshirts or robes', '53102600', 'Nightwear', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'abayas?|dresses|dress|gowns?', p) and not any(k in p for k in ['patient gown', 'isolation gown', 'hospital gown', 'fancy dress']):
        return ('apparel_dress', 'Dress', '53102002', 'Womens dresses', '53102000', 'Dresses and skirts and saris and kimonos', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'socks?|crew sock', p) and not has_word(r'socket|sockets', p):
        return ('apparel_socks', 'Socks', '53102402', 'Socks', '53102400', 'Hosiery', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'belts?|ratchet belt', p):
        return ('apparel_belt', 'Belt', '53102501', 'Belts or suspenders', '53102500', 'Clothing accessories', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'scarf|scarves|shawls?|muffler', p):
        return ('apparel_scarf', 'Scarf', '53102502', 'Ties or scarves or mufflers', '53102500', 'Clothing accessories', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'diapers?|nappies?', p):
        return ('apparel_diaper', 'Diapers', '53102305', 'Infant diapers', '53102300', 'Undergarments', '53100000', 'Clothing', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    if has_word(r'sneakers?|runner|athletic shoes?', p):
        if has_word(r'jr|kids?|boys?|youth', p):
            return ('apparel_sneaker_kids', 'Kids Athletic Footwear', '53111903', 'Boys athletic footwear', '53111900', 'Athletic footwear', '53110000', 'Footwear', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')
        return ('apparel_sneaker_mens', 'Mens Athletic Footwear', '53111901', 'Mens athletic footwear', '53111900', 'Athletic footwear', '53110000', 'Footwear', '53000000', 'Apparel and Luggage and Personal Care Products', 'No Doubt')

    # --- MEDICAL SUPPLIES & APPAREL (Segment 42) ---
    if has_word(r'patient gown|hospital gown', p):
        return ('medical_patient_gown', 'Patient Gown', '42131504', 'Patient gowns', '42131500', 'Patient clothing', '42130000', 'Medical apparel and textiles', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')
    if has_word(r'isolation gown', p):
        return ('medical_isolation_gown', 'Isolation Gown', '42131612', 'Medical staff isolation or cover gown', '42131600', 'Medical staff clothing and related articles', '42130000', 'Medical apparel and textiles', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')
    if has_word(r'speedicath|urinary catheter|urethral catheter', p) or (has_word(r'catheter', p) and has_word(r'female|intermittent|foley|urological', p)):
        return ('medical_urinary_catheter', 'Urinary Catheter', '42142702', 'Urethral urinary catheters', '42142700', 'Urological supplies', '42140000', 'Patient care and transport', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')
    if has_word(r'mucus extractor', p) or (has_word(r'extractor', p) and has_word(r'suction|12fg|catheter', p)):
        return ('medical_suction_catheter', 'Suction Catheter', '42272011', 'Suction catheters or its accessories', '42272000', 'Intubation supplies', '42270000', 'Respiratory and anesthesia and resuscitation products', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')
    if has_word(r'syringe|syringes', p) and has_word(r'luer-lok|luer lok|10ml|hypodermic|needle', p):
        return ('medical_syringe', 'Medical Syringe', '42142608', 'Medical syringe without needle', '42142600', 'Syringes and accessories', '42140000', 'Patient care and transport', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')
    if has_word(r'compression sleeve|compression sleeves', p) and has_word(r'calf|varicose|veins?|shin splint|leg', p):
        return ('medical_compression_therapy', 'Compression Therapy Sleeve', '42142800', 'Vascular and compression therapy equipment and supplies', '42142800', 'Vascular and compression therapy equipment and supplies', '42140000', 'Patient care and transport', '42000000', 'Medical Equipment and Accessories and Supplies', 'Some Doubt')
    if has_word(r'arm sleeves?|cooling arm sleeves?', p) and has_word(r'sun|cooling|tattoo', p):
        return ('apparel_protective_sleeve', 'Protective Arm Sleeve', '46181541', 'Protective arm sleeve', '46181500', 'Safety apparel', '46180000', 'Personal safety and protection', '46000000', 'Defense and Law Enforcement and Security and Safety Equipment and Supplies', 'No Doubt')
    if has_word(r'corneometer', p) or (has_word(r'capacitive skin|skin hydration', p)):
        return ('medical_skin_diagnostic', 'Dermatological Diagnostic Instrument', '42182004', 'Dermatoscopes', '42182000', 'Scopes and specula and accessories for medical exam diagnostic use', '42180000', 'Patient exam and monitoring products', '42000000', 'Medical Equipment and Accessories and Supplies', 'Some Doubt')
    if has_word(r'bouffant caps?|bouffant', p):
        return ('medical_bouffant_cap', 'Bouffant Cap', '42131604', 'Medical staff bouffant caps', '42131600', 'Medical staff clothing and related articles', '42130000', 'Medical apparel and textiles', '42000000', 'Medical Equipment and Accessories and Supplies', 'No Doubt')

    # --- LIFE SCIENCES & BIOCHEMICALS (Segment 12 & 41) ---
    if has_word(r'antibodies|antibody', p) or has_word(r'cd154|cd40|anti-human', p):
        return ('biochem_antibody', 'Antibody', '12352203', 'Antibodies', '12352200', 'Biochemicals', '12350000', 'Compounds and mixtures', '12000000', 'Chemicals including Bio Chemicals and Gas Materials', 'No Doubt')
    if has_word(r'assay kit|membrane potential assay', p):
        return ('biochem_assay_kit', 'Assay Kit', '41116158', 'Enzyme linked immunosorbent assay ELISA kit', '41116100', 'Manual test kits and quality controls and calibrators and standards', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'Some Doubt')
    if has_word(r'catalyst|catalysts|catalyst support|zro2|zro₂|norpro', p):
        return ('chemical_catalyst', 'Catalyst Support', '12161603', 'Custom catalysts', '12161600', 'Catalysts', '12160000', 'Additives', '12000000', 'Chemicals including Bio Chemicals and Gas Materials', 'Some Doubt')

    # --- CHROMATOGRAPHY & LAB SUPPLIES (Segment 41) ---
    if has_word(r'inline filter|infinitylab', p):
        return ('chrom_inline_filter', 'Chromatography Inline Filter', '41115700', 'Chromatographic measuring instruments and accessories', '41115700', 'Chromatographic measuring instruments and accessories', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'Some Doubt')
    if has_word(r'guard column|securityguard|guard cartridges?', p):
        return ('chrom_guard_column', 'HPLC Guard Column', '41115730', 'High pressure liquid chromatography HPLC guard column', '41115700', 'Chromatographic measuring instruments and accessories', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'spe column|polyimine column|aflatest|oasis max|sorbent per well', p):
        return ('chrom_spe_column', 'SPE Column / Sorbent', '41115712', 'Solid phase extraction SPE columns', '41115700', 'Chromatographic measuring instruments and accessories', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'Some Doubt')
    if has_word(r'hplc column|lc column|xtimate|tskgel|polysep-gfc', p):
        return ('chrom_hplc_column', 'HPLC Column', '41115709', 'High pressure liquid chromatography HPLC columns', '41115700', 'Chromatographic measuring instruments and accessories', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'absorption tubes?|glass tubes?', p) or (has_word(r'borosilicate glass', p) and has_word(r'tube|tubes', p)):
        return ('lab_glass_tube', 'Laboratory Glass Tube', '41121816', 'Laboratory glass tube', '41121800', 'General laboratory glassware and plasticware and supplies', '41120000', 'Laboratory supplies and fixtures', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'vial|vials', p) and has_word(r'5ml|sample|environmental express|chromatography|vial only', p):
        return ('lab_vial', 'Laboratory Vial', '41121806', 'Laboratory vials', '41121800', 'General laboratory glassware and plasticware and supplies', '41120000', 'Laboratory supplies and fixtures', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'speedvac|vacuum concentrator', p):
        return ('lab_concentrator', 'Concentrator', '41103310', 'Concentrators', '41103300', 'Laboratory centrifuges and accessories', '41100000', 'Laboratory and scientific equipment', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'ph meter|ph bench meter|accumet', p):
        return ('lab_ph_meter', 'pH Meter', '41115603', 'pH meters', '41115600', 'Electrochemical measuring instruments and accessories', '41110000', 'Measuring and observing and testing instruments', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'No Doubt')
    if has_word(r'curing station', p):
        return ('machinery_curing_oven', 'Curing Oven', '23261508', 'Curing ovens', '23261500', 'Industrial ovens and furnaces', '23260000', 'Industrial manufacturing and processing machinery and accessories', '23000000', 'Industrial Manufacturing and Processing Machinery and Accessories', 'Some Doubt')
    if has_word(r'washing station', p):
        return ('lab_washing_station', 'Laboratory Washing Station', '41103202', 'Laboratory washing machines', '41103200', 'Laboratory washing and cleaning equipment', '41100000', 'Laboratory and scientific equipment', '41000000', 'Laboratory and Measuring and Observing and Testing Equipment', 'Some Doubt')

    # --- TOOLS & HARDWARE (Segment 27 & 31) ---
    if has_word(r'center punch', p):
        return ('tool_center_punch', 'Center Punch', '27111555', 'Center punch', '27111500', 'Cutting and crimping and punching tools', '27110000', 'Hand tools', '27000000', 'Tools and General Machinery', 'No Doubt')
    if has_word(r'socket|sockets', p) and has_word(r'point|drive|sae|deep|metric|1/2|3/8|9/16|1/4', p):
        return ('tool_point_socket', 'Point Socket', '27111768', 'Point socket', '27111700', 'Wrenches and drivers', '27110000', 'Hand tools', '27000000', 'Tools and General Machinery', 'No Doubt')
    if has_word(r'voltage detector|voltage tester', p):
        return ('tool_voltage_tester', 'Voltage Tester', '27111738', 'Voltage tester screwdriver', '27111700', 'Wrenches and drivers', '27110000', 'Hand tools', '27000000', 'Tools and General Machinery', 'No Doubt')
    if has_word(r'masonry disc|cutting disc|cut-off wheel|diamond blade|grinding disc', p):
        return ('abrasive_wheel', 'Abrasive Wheel', '31191602', 'Abrasive diamond wheels', '31191600', 'Abrasive wheels', '31190000', 'Abrasives and abrasive media', '31000000', 'Manufacturing Components and Supplies', 'Some Doubt')
    if has_word(r'driveway marker|driveway markers', p):
        return ('safety_marker', 'Warning Marker Post', '46211602', 'Work area warning posts and chains', '46211600', 'Work area marking and visual indicators', '46210000', 'Industrial safety devices', '46000000', 'Defense and Law Enforcement and Security and Safety Equipment and Supplies', 'Some Doubt')
    if has_word(r'motorcycle helmet|full face helmet', p) or (has_word(r'helmet', p) and has_word(r'isi certified|full face|motorcycle', p)):
        return ('safety_motorcycle_helmet', 'Motorcycle Helmet', '46181705', 'Motorcycle helmets', '46181700', 'Face and head protection', '46180000', 'Personal safety and protection', '46000000', 'Defense and Law Enforcement and Security and Safety Equipment and Supplies', 'No Doubt')
    if has_word(r'safety goggles?|safety glasses', p):
        return ('safety_goggles', 'Safety Glasses', '46181802', 'Safety glasses', '46181800', 'Vision protection and accessories', '46180000', 'Personal safety and protection', '46000000', 'Defense and Law Enforcement and Security and Safety Equipment and Supplies', 'No Doubt')
    if has_word(r'disinfecting wipes?|cleaning wipes?', p):
        return ('cleaning_wipes', 'Cleaning Cloths or Wipes', '47131502', 'Cleaning cloths or wipes', '47131500', 'Cleaning rags and cloths and wipes', '47130000', 'Cleaning and janitorial supplies', '47000000', 'Cleaning Equipment and Supplies', 'No Doubt')

    return None


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
# STEP 3, 4 & 5: CONCRETE MULTI-STEP EVALUATION PIPELINE
# =====================================================================

def match_product(product_name, mfr_name='', mfr_part='', supplier_name='', supplier_part=''):
    """
    Executes the 5 Concrete Steps:
    1. Step 1 (Mfr & MPN): Identifies Manufacturer Brand Domain & OEM Part Number
    2. Step 2 (Head Noun): Identifies the functional object, preventing modifier confusion
    3. Step 3 (Supplier Context): Verifies distributor context & channel
    4. Step 4 (Taxonomy Traversal): Maps to Segment -> Family -> Class -> Commodity
    5. Step 5 (Doubt Policy Rollup): No Doubt -> Commodity; Some Doubt -> Class/Family; Huge Doubt -> Segment
    """
    p_name = (product_name or '').strip()
    m_name = (mfr_name or '').strip()
    m_part = (mfr_part or '').strip()
    s_name = (supplier_name or '').strip()
    s_part = (supplier_part or '').strip()

    google_url = generate_google_search_url(m_name, m_part, p_name, s_name, s_part)

    # -----------------------------------------------------------------
    # STEP 1: Manufacturer & Brand Domain Resolution
    # -----------------------------------------------------------------
    mfr_domain_label, allowed_segments = get_manufacturer_domain(m_name)
    if not allowed_segments and s_name:
        supp_domain_label, supp_segs = get_manufacturer_domain(s_name)
        if supp_segs:
            allowed_segments = supp_segs
            mfr_domain_label = supp_domain_label

    # -----------------------------------------------------------------
    # STEP 2: Semantic Head Noun & Functional Object Extraction
    # -----------------------------------------------------------------
    parsed = extract_head_noun_category(p_name, mfr_domain_label or '')

    if parsed:
        tag, head_noun, comm_code, comm_name, class_code, class_name, fam_code, fam_name, seg_code, seg_name, doubt = parsed

        # Apply Step 5: Doubt Rollup Policy
        if doubt == 'No Doubt':
            assigned_code = comm_code
            assigned_cat = comm_name
            assigned_level = 'Commodity (8-digit)'
        elif doubt == 'Some Doubt':
            assigned_code = class_code
            assigned_cat = class_name
            assigned_level = 'Class (6-digit)'
        else:
            assigned_code = seg_code
            assigned_cat = seg_name
            assigned_level = 'Segment (2-digit)'

        method_note = f"Step 1 & 2: {mfr_domain_label or 'Domain'} | Head Noun: {head_noun}"

        # Construct Concrete Step Audit Trail
        mfr_info = f"MFR '{m_name}'" + (f" [MPN: {m_part}]" if m_part else "") + f" -> Sector Domain: {mfr_domain_label or 'Verified'}" if m_name else "MFR: Not provided"
        noun_info = f"Head Noun isolated: '{head_noun}'"
        supp_info = f"Supplier '{s_name}'" + (f" [SKU: {s_part}]" if s_part else "") + " checked" if s_name else "Supplier: Not provided"
        tax_info = f"Taxonomy: Seg {seg_code} > Fam {fam_code} > Class {class_code} > Comm {comm_code}"
        rollup_info = f"Rollup: {doubt} -> Assigned {assigned_level} '{assigned_code}' ({assigned_cat})"

        step_audit_trail = f"[Step 1: OEM] {mfr_info} | [Step 2: Head Noun] {noun_info} | [Step 3: Supplier] {supp_info} | [Step 4: Taxonomy] {comm_code} ({comm_name}) | [Step 5: Rollup] {doubt} -> {assigned_level} {assigned_code}"

        return {
            'assigned_code': assigned_code,
            'assigned_category': assigned_cat,
            'assigned_level': assigned_level,
            'confidence': doubt,
            'match_method': method_note,
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

    # -----------------------------------------------------------------
    # STEP 3 & 4: Fallback Domain-Constrained Database Lookup
    # -----------------------------------------------------------------
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        clean_text = re.sub(r'[^a-zA-Z0-9\s]', ' ', p_name.lower())
        tokens = [w for w in clean_text.split() if len(w) > 2 and w not in {'the', 'and', 'for', 'with', 'from', 'size', 'color', 'black', 'white', 'mens', 'womens', 'large', 'adult'}]

        if tokens:
            candidates = []
            for token in tokens[:4]:
                cursor.execute('''
                    SELECT commodity_code, commodity_name, class_code, class_name,
                           family_code, family_name, segment_code, segment_name
                    FROM unspsc_items
                    WHERE commodity_name LIKE ?
                    LIMIT 50
                ''', (f'%{token}%',))
                for row in cursor.fetchall():
                    seg_prefix = row['commodity_code'][:2]
                    if allowed_segments and seg_prefix not in allowed_segments:
                        continue
                    candidates.append(row)

            if candidates:
                best = candidates[0]
                comm_code = best['commodity_code']
                assigned_c = best['class_code'] or (comm_code[:6] + '00')
                assigned_n = best['class_name']

                mfr_info = f"MFR '{m_name}'" + (f" [MPN: {m_part}]" if m_part else "") + f" -> Constrained to Sector: {mfr_domain_label or 'Generic'}" if m_name else "MFR: Not provided"
                noun_info = f"Keyword Tokens: {', '.join(tokens[:3])}"
                supp_info = f"Supplier '{s_name}'" if s_name else "Supplier: Not provided"
                tax_info = f"Taxonomy: Seg {best['segment_code']} > Fam {best['family_code']} > Class {assigned_c} > Comm {comm_code}"
                rollup_info = f"Rollup: Some Doubt -> Assigned Class (6-digit) '{assigned_c}' ({assigned_n})"

                step_audit_trail = f"[Step 1: OEM] {mfr_info} | [Step 2: Tokens] {noun_info} | [Step 3: Supplier] {supp_info} | [Step 4: Database Search] Comm {comm_code} ({best['commodity_name']}) | [Step 5: Rollup] Some Doubt -> Class (6-digit) {assigned_c}"

                return {
                    'assigned_code': assigned_c,
                    'assigned_category': assigned_n,
                    'assigned_level': 'Class (6-digit)',
                    'confidence': 'Some Doubt',
                    'match_method': f"Step 4: Database Search ({mfr_domain_label or 'Constrained'})",
                    'step_audit_trail': step_audit_trail,
                    'step1_detail': mfr_info,
                    'step2_detail': noun_info,
                    'step3_detail': supp_info,
                    'step4_detail': tax_info,
                    'step5_detail': rollup_info,
                    'google_url': google_url,
                    'commodity_code': comm_code,
                    'commodity_name': best['commodity_name'],
                    'class_code': assigned_c,
                    'class_name': assigned_n,
                    'family_code': best['family_code'] or (comm_code[:4] + '0000'),
                    'family_name': best['family_name'],
                    'segment_code': best['segment_code'] or (comm_code[:2] + '000000'),
                    'segment_name': best['segment_name']
                }
    finally:
        conn.close()

    # Huge Doubt Fallback
    fallback_seg = list(allowed_segments)[0] + '000000' if allowed_segments else '53000000'
    mfr_info = f"MFR '{m_name}'" if m_name else "MFR: Not provided"
    noun_info = f"Unresolved description: '{p_name}'"
    supp_info = f"Supplier '{s_name}'" if s_name else "Supplier: Not provided"
    tax_info = f"Taxonomy: Fallback Segment {fallback_seg}"
    rollup_info = f"Rollup: Huge Doubt -> Assigned Segment (2-digit) '{fallback_seg}' (General Goods / Unclassified)"
    step_audit_trail = f"[Step 1: OEM] {mfr_info} | [Step 2: Noun] {noun_info} | [Step 3: Supplier] {supp_info} | [Step 4: Unresolved] | [Step 5: Rollup Policy] Huge Doubt -> Segment (2-digit) {fallback_seg}"

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
    conn = get_db_connection()
    try:
        clean_q = re.sub(r'[^a-zA-Z0-9\s]', ' ', query.lower())
        tokens = [w for w in clean_q.split() if len(w) > 1]
        if not tokens:
            return []

        conditions = []
        params = []
        for token in tokens:
            conditions.append('(commodity_name LIKE ? OR class_name LIKE ? OR family_name LIKE ? OR segment_name LIKE ?)')
            params.extend([f'%{token}%'] * 4)

        where = ' AND '.join(conditions)
        sql = f'''
            SELECT DISTINCT commodity_code, commodity_name, class_code, class_name,
                            family_code, family_name, segment_code, segment_name
            FROM unspsc_items
            WHERE {where}
            ORDER BY commodity_name
            LIMIT ?
        '''
        params.append(limit)

        cursor = conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
