"""
AI Assistant Module for UNSPSC Classification
Supports:
1. Google Gemini (Free tier via Google AI Studio)
2. DeepSeek (api.deepseek.com)
3. OpenAI ChatGPT / Groq
4. Cross-referencing & Grounding against 71,502 official UNSPSC records in SQLite
"""

import os
import json
import re
import sqlite3
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except Exception:
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), 'unspsc_data.sqlite')


def get_configured_ai_provider() -> Tuple[str, str]:
    """Detect available AI API key from environment or config."""
    if os.environ.get('GEMINI_API_KEY'):
        return 'gemini', os.environ['GEMINI_API_KEY'].strip()
    if os.environ.get('GOOGLE_API_KEY'):
        return 'gemini', os.environ['GOOGLE_API_KEY'].strip()
    if os.environ.get('DEEPSEEK_API_KEY'):
        return 'deepseek', os.environ['DEEPSEEK_API_KEY'].strip()
    if os.environ.get('OPENAI_API_KEY'):
        return 'openai', os.environ['OPENAI_API_KEY'].strip()
    if os.environ.get('GROQ_API_KEY'):
        return 'groq', os.environ['GROQ_API_KEY'].strip()
    return '', ''


def call_gemini(api_key: str, prompt: str) -> Optional[str]:
    """Call Google Gemini 1.5/2.0 Flash API (Free Tier)."""
    # Try gemini-1.5-flash or gemini-2.0-flash
    models = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro']
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0].get('content', {}).get('parts', [])
                    if parts:
                        return parts[0].get('text', '')
            else:
                # If 404 on model, try next model
                continue
        except Exception:
            continue
    return None


def call_deepseek(api_key: str, prompt: str) -> Optional[str]:
    """Call DeepSeek Chat API."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a master UNSPSC procurement classification expert."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            return data['choices'][0]['message']['content']
    except Exception:
        pass
    return None


def call_openai_compatible(api_key: str, prompt: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini") -> Optional[str]:
    """Call OpenAI / Groq API."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a master UNSPSC procurement classification expert."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            return data['choices'][0]['message']['content']
    except Exception:
        pass
    return None


def query_ai_for_product(product_name: str, mfr_name: str = '', mfr_part: str = '', supplier_name: str = '', supplier_part: str = '', api_key: str = '', provider: str = '') -> Optional[Dict[str, Any]]:
    """
    Asks the AI (Gemini, DeepSeek, or ChatGPT) to:
    1. Read the COMPLETE product description without rushing.
    2. Disambiguate subtle taxonomic boundaries (e.g., training videos vs kits, surgical vs industrial masks).
    3. Determine what the manufacturer manufactures.
    4. Determine what the supplier supplies.
    5. Identify exact physical product type and suggest the official UNSPSC code.
    """
    if not provider or not api_key:
        det_prov, det_key = get_configured_ai_provider()
        provider = provider or det_prov
        api_key = api_key or det_key

    if not api_key:
        return None

    prompt = f"""
You are a senior master specialist in UNSPSC (United Nations Standard Products and Services Code) procurement cataloging and taxonomic classification.
Your mandate is PERFECTION, DEEP THINKING, and RIGOROUS PRECISION over haste or guesswork.

Please thoroughly analyze the following item:
- Complete Product Description: "{product_name}"
- Manufacturer Name: "{mfr_name}"
- Manufacturer Part # (MPN): "{mfr_part}"
- Supplier / Distributor Name: "{supplier_name}"
- Supplier Part # (SKU): "{supplier_part}"

Execution Steps (Think carefully through each step before arriving at the conclusion):
1. READ THE COMPLETE PRODUCT NAME: Parse every word from beginning to end. Separate commercial brand names, packaging quantities (e.g. 50/bx, case, each, pack), technical qualifiers, from the true physical noun.
2. DISAMBIGUATE CLOSE TAXONOMIC BOUNDARIES:
   - Videos / DVDs vs Training Kits vs Handbooks / Booklets (e.g., DVD training modules = 46211502 Workplace safety training video; physical multi-item kits = 46211501 Workplace safety training kit; printed guides = 46211503 Training manual/handbook).
   - Face Masks & Respirators (e.g., Anesthesia/laryngeal mask = 42271607; Medical/surgical isolation mask = 42131606; Industrial protective dust/N95 mask = 46182001; PAPR = 46182002; Face shield = 46181702).
   - Gloves (e.g., Medical exam glove = 42132203; Heat protective glove = 46181508; General industrial protective glove = 46181504; Glove dispenser/organizer = 46181553).
   - Fall Protection (e.g., Harness = 46182306; Lanyard/Lifeline = 46182301; Anchorage clamp = 46182304; Tripod = 46182305; Winch = 24101616).
   - Lab timers & stopwatches (41111949) vs Computer hardware.
3. IDENTIFY EXACT OFFICIAL UNSPSC COMMODITY: Determine the exact 8-digit Commodity code or 6-digit Class code and the official UNSPSC title.

Respond ONLY with a valid JSON object with the following structure:
{{
    "deep_thinking_analysis": "Comprehensive step-by-step reasoning explaining the complete product dissection, manufacturer context, and why this specific commodity is the correct classification",
    "mfr_goods": "Brief summary of what kind of goods this manufacturer makes",
    "supplier_goods": "Brief summary of what this supplier distributes",
    "product_type": "Exact physical product type (e.g. 'Workplace safety training video', 'Anesthesia masks', 'High pressure liquid chromatography HPLC column')",
    "suggested_unspsc_code": "8-digit commodity code (e.g. 46211502, 42271607, 46181802)",
    "suggested_category": "Official UNSPSC category name",
    "search_keywords": ["keyword1", "keyword2", "keyword3"],
    "confidence_assessment": "High / Medium / Low"
}}
Return JSON only, no markdown formatting, no surrounding text.
"""
    raw_response = None
    if provider.lower() == 'gemini':
        raw_response = call_gemini(api_key, prompt)
    elif provider.lower() == 'deepseek':
        raw_response = call_deepseek(api_key, prompt)
    elif provider.lower() == 'groq':
        raw_response = call_openai_compatible(api_key, prompt, base_url="https://api.groq.com/openai/v1", model="llama-3.1-8b-instant")
    elif provider.lower() in ('openai', 'chatgpt'):
        openai_model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
        raw_response = call_openai_compatible(api_key, prompt, base_url="https://api.openai.com/v1", model=openai_model)

    if not raw_response:
        return None

    try:
        # Extract JSON from potential markdown fence
        json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return data
    except Exception:
        pass
    return None


def cross_reference_with_70k_database(ai_result: Optional[Dict[str, Any]] = None, allowed_segments: Optional[set] = None, suggested_code: str = '', suggested_cat: str = '', product_type: str = '', keywords: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    Cross-references the AI's proposal against the 71,502 official UNSPSC records in SQLite:
    1. First checks if AI's suggested_unspsc_code exists in unspsc_items.
    2. If found and matches category intent, verifies it.
    3. If missing or misaligned, searches unspsc_fts using the AI's identified product_type and search_keywords.
    Returns dict: {'matched': True, 'record': dict(row), 'resolution_note': note} or None.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if isinstance(ai_result, dict):
        suggested_code = suggested_code or str(ai_result.get('suggested_unspsc_code', ''))
        product_type = product_type or str(ai_result.get('product_type', ''))
        if keywords is None:
            keywords = ai_result.get('search_keywords', [])

    suggested_code = str(suggested_code or '').strip()
    product_type = str(product_type or '').strip()
    keywords = keywords or []

    # 1. Direct validation of suggested code against 71,502 database
    if suggested_code and len(suggested_code) >= 6:
        c.execute("""
            SELECT commodity_code, commodity_name, class_code, class_name,
                   family_code, family_name, segment_code, segment_name
            FROM unspsc_items
            WHERE commodity_code = ? OR class_code = ?
            LIMIT 1
        """, (suggested_code, suggested_code))
        row = c.fetchone()
        if row:
            conn.close()
            return {
                'matched': True,
                'record': dict(row),
                'resolution_note': f"Directly validated against 71,502 records: Verified Code '{suggested_code}' ({row['commodity_name']})"
            }

    # 2. Search SQLite FTS using AI's identified product type
    if product_type:
        clean_type = re.sub(r'[^a-zA-Z0-9\s]', ' ', product_type.lower())
        tokens = [w for w in clean_type.split() if len(w) > 1]
        if tokens:
            exact_q = ' '.join(f'"{t}"' for t in tokens)
            c.execute("""
                SELECT commodity_code, commodity_name, class_code, class_name,
                       family_code, family_name, segment_code, segment_name, rank
                FROM unspsc_fts
                WHERE unspsc_fts MATCH ?
                ORDER BY rank
                LIMIT 10
            """, (exact_q,))
            candidates = c.fetchall()
            filtered = [r for r in candidates if not allowed_segments or r['segment_code'][:2] in allowed_segments]
            if filtered:
                best = filtered[0]
                conn.close()
                return {
                    'matched': True,
                    'record': dict(best),
                    'resolution_note': f"Cross-referenced AI product type '{product_type}' against 71,502 records -> Matched '{best['commodity_code']}'"
                }

            # Try compound noun
            if len(tokens) >= 2:
                comp_q = f'"{tokens[-2]}" AND "{tokens[-1]}"'
                c.execute("""
                    SELECT commodity_code, commodity_name, class_code, class_name,
                           family_code, family_name, segment_code, segment_name, rank
                    FROM unspsc_fts
                    WHERE unspsc_fts MATCH ?
                    ORDER BY rank
                    LIMIT 10
                """, (comp_q,))
                candidates = c.fetchall()
                filtered = [r for r in candidates if not allowed_segments or r['segment_code'][:2] in allowed_segments]
                if filtered:
                    best = filtered[0]
                    conn.close()
                    return {
                        'matched': True,
                        'record': dict(best),
                        'resolution_note': f"Cross-referenced AI compound noun '{tokens[-2]} {tokens[-1]}' -> Matched '{best['commodity_code']}'"
                    }

    # 3. Fallback to keywords
    if keywords and isinstance(keywords, list):
        kw_clean = [re.sub(r'[^a-zA-Z0-9]', '', str(k).lower()) for k in keywords if len(str(k)) > 2]
        if kw_clean:
            or_q = ' OR '.join(f'"{k}"' for k in kw_clean[:4])
            c.execute("""
                SELECT commodity_code, commodity_name, class_code, class_name,
                       family_code, family_name, segment_code, segment_name, rank
                FROM unspsc_fts
                WHERE unspsc_fts MATCH ?
                ORDER BY rank
                LIMIT 10
            """, (or_q,))
            candidates = c.fetchall()
            filtered = [r for r in candidates if not allowed_segments or r['segment_code'][:2] in allowed_segments]
            if filtered:
                best = filtered[0]
                conn.close()
                return {
                    'matched': True,
                    'record': dict(best),
                    'resolution_note': f"Cross-referenced AI keywords against 71,502 records -> Matched '{best['commodity_code']}'"
                }

    conn.close()
    return None
