"""
UNSPSC Code Lookup Web Application
Flask app with Manufacturer & MPN Priority, Supplier Context, and Strict Doubt Policy.
Precedence:
1. Manufacturer Name + Manufacturer Part #
2. Product Name
3. Supplier Name + Supplier Part #
"""

import os
import uuid
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from matcher import match_product, search_unspsc, generate_google_search_url

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'downloads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_excel(filepath, api_key='', ai_provider=''):
    """
    Read an uploaded Excel file, detecting:
    - Manufacturer Name & Part #
    - Product Name
    - Supplier Name & Part #
    Evaluates in strict priority order with optional AI assistance and 70k database verification.
    """
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active

    headers = []
    for cell in ws[1]:
        headers.append(str(cell.value).strip() if cell.value is not None else '')

    product_col = None
    mfr_name_col = None
    mfr_part_col = None
    supplier_col = None
    supplier_part_col = None

    for i, h in enumerate(headers):
        h_clean = h.lower().strip()
        if not h_clean:
            continue

        # Manufacturer Part / MPN
        if any(k in h_clean for k in ['mfr part', 'manufacturer part', 'mfg part', 'mfr. part', 'mfg. part', 'oem part', 'mpn']):
            if mfr_part_col is None:
                mfr_part_col = i
        # Manufacturer Name
        elif any(k in h_clean for k in ['mfr name', 'manufacturer name', 'mfg name', 'mfr', 'manufacturer', 'mfg', 'oem', 'make', 'brand']):
            if mfr_name_col is None:
                mfr_name_col = i
        # Supplier Part #
        elif any(k in h_clean for k in ['supplier part', 'vendor part', 'distributor part', 'supplier sku', 'vendor sku']):
            if supplier_part_col is None:
                supplier_part_col = i
        # Supplier Name
        elif any(k in h_clean for k in ['supplier name', 'vendor name', 'supplier', 'vendor', 'distributor']):
            if supplier_col is None:
                supplier_col = i
        # Product Description / Name
        elif any(k in h_clean for k in ['product', 'item', 'description', 'material']) and 'unspsc' not in h_clean and 'unspc' not in h_clean:
            if product_col is None:
                product_col = i
        # Fallback Part / SKU if not already assigned
        elif any(k in h_clean for k in ['part #', 'part number', 'part no', 'part_number', 'sku', 'catalog #', 'catalog number', 'cat #']):
            if 'unspsc' not in h_clean and 'unspc' not in h_clean:
                if mfr_part_col is None:
                    mfr_part_col = i
                elif supplier_part_col is None:
                    supplier_part_col = i

    # Fallback product column if still None
    if product_col is None:
        for i in range(len(headers)):
            if i not in (mfr_name_col, mfr_part_col, supplier_col, supplier_part_col):
                product_col = i
                break
        if product_col is None:
            product_col = 0

    results = []
    total_rows = 0

    for row in ws.iter_rows(min_row=2, values_only=False):
        values = [cell.value for cell in row]

        if all(v is None or str(v).strip() == '' for v in values):
            continue

        product_name = str(values[product_col]).strip() if product_col is not None and product_col < len(values) and values[product_col] is not None else ''
        mfr_name = str(values[mfr_name_col]).strip() if mfr_name_col is not None and mfr_name_col < len(values) and values[mfr_name_col] is not None else ''
        mfr_part = str(values[mfr_part_col]).strip() if mfr_part_col is not None and mfr_part_col < len(values) and values[mfr_part_col] is not None else ''
        supplier_name = str(values[supplier_col]).strip() if supplier_col is not None and supplier_col < len(values) and values[supplier_col] is not None else ''
        supplier_part = str(values[supplier_part_col]).strip() if supplier_part_col is not None and supplier_part_col < len(values) and values[supplier_part_col] is not None else ''

        if not product_name or product_name.lower() == 'none':
            if not mfr_part and not supplier_part:
                continue

        total_rows += 1
        m = match_product(
            product_name=product_name,
            mfr_name=mfr_name,
            mfr_part=mfr_part,
            supplier_name=supplier_name,
            supplier_part=supplier_part,
            api_key=api_key,
            ai_provider=ai_provider
        )

        results.append({
            'sno': total_rows,
            'product_name': product_name,
            'mfr_name': mfr_name,
            'mfr_part': mfr_part,
            'supplier_name': supplier_name,
            'supplier_part': supplier_part,
            'assigned_code': m['assigned_code'],
            'assigned_category': m['assigned_category'],
            'assigned_level': m['assigned_level'],
            'confidence': m['confidence'],
            'match_method': m['match_method'],
            'step_audit_trail': m.get('step_audit_trail', ''),
            'step1_detail': m.get('step1_detail', ''),
            'step2_detail': m.get('step2_detail', ''),
            'step3_detail': m.get('step3_detail', ''),
            'step4_detail': m.get('step4_detail', ''),
            'step5_detail': m.get('step5_detail', ''),
            'google_url': m.get('google_url') or generate_google_search_url(mfr_name, mfr_part, product_name, supplier_name, supplier_part),
            'commodity_code': m['commodity_code'],
            'commodity_name': m['commodity_name'],
            'class_code': m['class_code'],
            'class_name': m['class_name'],
            'family_code': m['family_code'],
            'family_name': m['family_name'],
            'segment_code': m['segment_code'],
            'segment_name': m['segment_name']
        })

    wb.close()
    return results


def create_output_excel(results, original_filename):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "UNSPSC Mapped"

    headers = [
        "S.No", "Product Name", "Manufacturer Name", "Manufacturer Part #",
        "Supplier Name", "Supplier Part #",
        "Assigned UNSPSC Code", "Assigned Category", "Assigned Level", "Doubt / Confidence", "Match Method",
        "Concrete Step Audit Trail",
        "Google / Catalog Search",
        "Commodity Code", "Commodity Name", "Class Code", "Class Name",
        "Family Code", "Family Name", "Segment Code", "Segment Name"
    ]
    ws.append(headers)

    hdr_fill = PatternFill(start_color="1A5276", end_color="1A5276", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    link_font = Font(name="Calibri", size=10, color="0000EE", underline="single")
    thin_border = Border(
        left=Side(style='thin', color='D0D3D4'),
        right=Side(style='thin', color='D0D3D4'),
        top=Side(style='thin', color='D0D3D4'),
        bottom=Side(style='thin', color='D0D3D4')
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    no_doubt_fill = PatternFill(start_color="D5F5E3", end_color="D5F5E3", fill_type="solid")
    some_doubt_fill = PatternFill(start_color="FEF9E7", end_color="FEF9E7", fill_type="solid")
    huge_doubt_fill = PatternFill(start_color="FADBD8", end_color="FADBD8", fill_type="solid")
    none_fill = PatternFill(start_color="F2F3F4", end_color="F2F3F4", fill_type="solid")

    for r in results:
        g_url = r['google_url']
        row_data = [
            r['sno'], r['product_name'], r['mfr_name'], r['mfr_part'],
            r['supplier_name'], r['supplier_part'],
            r['assigned_code'], r['assigned_category'], r['assigned_level'], r['confidence'], r['match_method'],
            r.get('step_audit_trail', ''),
            f'=HYPERLINK("{g_url}", "Verify on Google")',
            r['commodity_code'], r['commodity_name'], r['class_code'], r['class_name'],
            r['family_code'], r['family_name'], r['segment_code'], r['segment_name']
        ]
        ws.append(row_data)

        row_num = ws.max_row
        conf = r['confidence']
        fill = no_doubt_fill if conf in ('No Doubt', 'High') else some_doubt_fill if conf in ('Some Doubt', 'Medium') else huge_doubt_fill if conf in ('Huge Doubt', 'Low') else none_fill

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

        ws.cell(row=row_num, column=7).fill = fill
        ws.cell(row=row_num, column=9).fill = fill
        ws.cell(row=row_num, column=10).fill = fill

        link_cell = ws.cell(row=row_num, column=13)
        link_cell.font = link_font
        link_cell.alignment = Alignment(horizontal="center", vertical="center")

    widths = [6, 40, 22, 22, 22, 20, 20, 36, 18, 16, 28, 60, 20, 16, 32, 16, 32, 16, 32, 16, 45]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions

    base = Path(original_filename).stem
    output_name = f"{base}_UNSPSC_mapped_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], output_name)
    wb.save(output_path)
    return output_path, output_name


# ============ ROUTES ============

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload .xlsx, .xls, or .csv files.', 'error')
        return redirect(url_for('index'))

    unique_name = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    file.save(filepath)

    ai_provider = request.form.get('ai_provider', '').strip()
    ai_key = request.form.get('ai_key', '').strip()

    try:
        start_time = time.time()
        results = process_excel(filepath, api_key=ai_key, ai_provider=ai_provider)
        processing_time = round(time.time() - start_time, 2)

        if not results:
            flash('No data rows found in the uploaded file.', 'error')
            return redirect(url_for('index'))

        output_path, output_name = create_output_excel(results, file.filename)

        total = len(results)
        no_doubt = sum(1 for r in results if r['confidence'] in ('No Doubt', 'High'))
        some_doubt = sum(1 for r in results if r['confidence'] in ('Some Doubt', 'Medium'))
        huge_doubt = sum(1 for r in results if r['confidence'] in ('Huge Doubt', 'Low'))
        no_match = sum(1 for r in results if r['confidence'] == 'None')

        return render_template('results.html',
                               results=results,
                               total=total,
                               no_doubt=no_doubt,
                               some_doubt=some_doubt,
                               huge_doubt=huge_doubt,
                               no_match=no_match,
                               processing_time=processing_time,
                               output_file=output_name,
                               original_file=file.filename)

    except Exception as e:
        flash(f'Error processing file: {str(e)}', 'error')
        return redirect(url_for('index'))
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True, download_name=filename)
    flash('File not found', 'error')
    return redirect(url_for('index'))


@app.route('/search')
def search_page():
    return render_template('search.html')


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])
    results = search_unspsc(query, limit=25)
    return jsonify(results)


@app.route('/about')
def about():
    return render_template('about.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ('true', '1')
    print("\n" + "=" * 60)
    print(f"  UNSPSC Code Lookup Tool (Mfr & MPN Priority)")
    print(f"  Open your browser to: http://localhost:{port}")
    print("=" * 60 + "\n")
    app.run(debug=debug, host='0.0.0.0', port=port)
