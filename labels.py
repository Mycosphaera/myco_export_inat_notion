import io
import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def generate_qr_code(data):
    """Generate a QR code image in memory."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

def create_label_flowables(obs, styles, options):
    """Create the flowables for a single label."""
    
    # Extract Data
    taxon_name = obs.get('taxon', {}).get('name', 'Inconnu')
    
    # Date formatting
    date_str = "Date inconnue"
    obs_date = obs.get('time_observed_at')
    if obs_date:
        if hasattr(obs_date, 'strftime'):
             date_str = obs_date.strftime("%Y-%m-%d")
        else:
             date_str = str(obs_date)[:10]
    elif obs.get('observed_on_string'):
        date_str = str(obs.get('observed_on_string'))
        
    place = obs.get('place_guess', 'Lieu inconnu')
    
    # User / Collector
    user_login = obs.get('user', {}).get('login', '')
    user_name = obs.get('user', {}).get('name', '')
    collector = user_name if user_name else user_login
    
    # URL for QR
    if obs.get('custom_url'):
        obs_url = obs['custom_url']
    else:
        obs_url = f"https://www.inaturalist.org/observations/{obs['id']}"
    
    # Generate QR
    qr_img_data = generate_qr_code(obs_url)
    qr_img = Image(qr_img_data, width=0.8*inch, height=0.8*inch)
    
    # Styles
    style_normal = styles['Normal']
    style_italic = styles['Italic']
    style_small = styles['Small']
    style_title = styles['LabelTitle']
    
    # Title (User Configured)
    title_text = options.get('title', 'Herbarium Label')
    title_para = Paragraph(f"<b>{title_text}</b>", style_title)
    
    # Taxon
    taxon_para = Paragraph(f"<i>{taxon_name}</i>", style_italic)
    
    # Metadata
    meta_text = f"""
    <b>Date:</b> {date_str}<br/>
    <b>Loc:</b> {place}<br/>
    <b>Det:</b> {collector}<br/>
    <b>ID:</b> {obs['id']}
    """
    if options.get('include_coords'):
        loc = obs.get('location')
        if loc:
             meta_text += f"<br/><b>GPS:</b> {loc}"
             
    meta_para = Paragraph(meta_text, style_small)
    
    # Layout: Table with 2 columns (Text | QR)
    # Column widths: Text takes most space, QR takes fixed space
    col_widths = [2.6*inch, 0.9*inch] 
    
    data = [[
        [title_para, Spacer(1, 4), taxon_para, Spacer(1, 4), meta_para],
        [qr_img]
    ]]
    
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'CENTER'), # Center QR
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('Grid', (0,0), (-1,-1), 0.5, colors.black), # Inner grid (optional, maybe remove for cleaner look, but user wanted "labels")
        # Actually, let's make the label itself have a border, but not the inner cells, or maybe just a layout table.
        # Let's put a border around the whole table to define the label edge.
        ('BOX', (0,0), (-1,-1), 1, colors.black),
    ]))
    
    return t

def generate_label_pdf(observations, options):
    """Generate a PDF specific to 2x4 Avery-style or generic grid."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='LabelTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, spaceAfter=2))
    styles.add(ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=8, leading=9))
    
    # Flowables list
    story = []
    
    # We want to arrange labels in a grid.
    # ReportLab SimpleDocTemplate flows things.
    # To enforce a grid (e.g. 2 columns), we can use a big container Table for the page content,
    # or just flow them if they are sized correctly.
    # Let's try flowing KeepTogether blocks.
    
    # However, for printing labels, precise positioning is usually better.
    # But "SimpleDocTemplate" is... simple.
    # Let's try creating a "Table of Labels".
    # 2 columns per row.
    
    label_flowables = []
    for obs in observations:
        label = create_label_flowables(obs, styles, options)
        label_flowables.append(label)
        
    # Chunk into pairs for 2-column layout
    rows = []
    for i in range(0, len(label_flowables), 2):
        row = [label_flowables[i]]
        if i+1 < len(label_flowables):
            row.append(label_flowables[i+1])
        else:
            row.append("") # Empty cell
        rows.append(row)
        
    # Master Table
    # 3.75 inch width per label gives 7.5 total, fits in 8.5 with 0.5 margins.
    main_table = Table(rows, colWidths=[3.75*inch, 3.75*inch])
    main_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    
    story.append(main_table)
    
    doc.build(story)
    buffer.seek(0)
    return buffer
