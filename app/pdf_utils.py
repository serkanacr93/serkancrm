from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import os
import re
from datetime import datetime

# PDF ciktilarinda temizlenecek samimi/gundelik hitaplar (Bey/Usta/Hoca
# bilincli olarak HARIC tutuldu - bunlar Turkce'de resmi/saygi ifadesi
# sayilir ve is belgesinde kullanilmasi uygundur).
_INFORMAL_ADDRESS_RE = re.compile(r'\b(abi|amca|abla|baba|day[ıi])\b', re.IGNORECASE)


def _clean_for_pdf(text):
    """Musteri adi/firma adindan sadece PDF gorunumu icin samimi hitaplari
    temizler. Veritabanindaki gercek kayda dokunmaz."""
    if not text:
        return text
    cleaned = _INFORMAL_ADDRESS_RE.sub('', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or text

def register_fonts():
    font_dir = os.path.join(os.path.dirname(__file__), 'static', 'fonts')
    pdfmetrics.registerFont(TTFont('Vera', os.path.join(font_dir, 'Vera.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-Bold', os.path.join(font_dir, 'VeraBd.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-Italic', os.path.join(font_dir, 'VeraIt.ttf')))
    pdfmetrics.registerFont(TTFont('Vera-BoldItalic', os.path.join(font_dir, 'VeraBI.ttf')))
    pdfmetrics.registerFontFamily(
        'Vera', normal='Vera', bold='Vera-Bold',
        italic='Vera-Italic', boldItalic='Vera-BoldItalic',
    )

register_fonts()

def _get_company_settings_for_pdf():
    """PDF ciktilari icin firma bilgilerini dondurur - CompanySettings kaydi
    yoksa (henuz Ayarlar'dan doldurulmamissa) None yerine bos/varsayilan
    degerli bir obje dondurur, boylece PDF hicbir zaman hata vermez."""
    from app.models import CompanySettings
    company = CompanySettings.query.get(1)
    if not company:
        company = CompanySettings(company_name='Lema Ambalaj')
    return company

def generate_deal_pdf(deal):
    """Siparis Sozlesmesi formatinda teklif PDF'i. Fiyat/urun kalemleri
    tekliften gelir; Kagit Cinsi/Boy/En/Renk ve odeme sekli (Vade-Pesinat-
    Bakiye) alanlari veri modelinde tutulmadigi icin bos birakilir, elle
    doldurulmak uzere PDF'te yer kaplar."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)

    company = _get_company_settings_for_pdf()

    styles = getSampleStyleSheet()
    normal = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=8.5, leading=11)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=7.5, leading=10)
    box_heading = ParagraphStyle('BoxHeading', parent=normal, fontName='Vera-Bold', fontSize=8.5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=16, leading=19)
    doc_title_style = ParagraphStyle('DocTitle', parent=normal, fontName='Vera-Bold', fontSize=20, leading=24, alignment=2, spaceAfter=3)
    doc_meta_style = ParagraphStyle('DocMeta', parent=normal, fontName='Vera-Bold', fontSize=9, leading=13, alignment=2)
    terms_style = ParagraphStyle('TermsStyle', parent=normal, fontSize=7.5, leading=10)
    table_header_style = ParagraphStyle('TableHeader', parent=normal, fontName='Vera-Bold', fontSize=7, leading=8.5,
                                         textColor=colors.white, alignment=1)

    elements = []

    # ===== UST BASLIK: firma bilgisi (sol) + TEKLIF basligi (sag) =====
    left_cell = []
    if company.logo_data:
        try:
            from PIL import Image as PILImage
            PILImage.open(BytesIO(company.logo_data)).verify()
            img = Image(BytesIO(company.logo_data), width=3.5*cm, height=1.8*cm, kind='proportional')
            left_cell.append(img)
            left_cell.append(Spacer(1, 2*mm))
        except Exception:
            pass
    left_cell.append(Paragraph(company.company_name or 'Lema Ambalaj', company_name_style))
    if company.address:
        left_cell.append(Paragraph(company.address.replace('\n', '<br/>'), small))
    contact_bits = []
    if company.phone:
        contact_bits.append(f"Tel: {company.phone}")
    if company.fax:
        contact_bits.append(f"Faks: {company.fax}")
    if contact_bits:
        left_cell.append(Paragraph(' | '.join(contact_bits), small))
    contact_bits2 = []
    if company.email:
        contact_bits2.append(company.email)
    if company.website:
        contact_bits2.append(company.website)
    if contact_bits2:
        left_cell.append(Paragraph(' | '.join(contact_bits2), small))
    if company.tax_office or company.tax_id:
        left_cell.append(Paragraph(f"V.D.: {company.tax_office or '-'}  V.No: {company.tax_id or '-'}", small))

    right_cell = [
        Paragraph("TEKLİF", doc_title_style),
        Spacer(1, 4*mm),
        Paragraph(f"Teklif No: {deal.display_no}", doc_meta_style),
        Paragraph(f"Tarih: {deal.deal_date.strftime('%d.%m.%Y') if deal.deal_date else deal.created_at.strftime('%d.%m.%Y')}", doc_meta_style),
    ]

    header_table = Table([[left_cell, right_cell]], colWidths=[11*cm, 6.2*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 4*mm))
    elements.append(Table([['']], colWidths=[17.2*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
    elements.append(Spacer(1, 4*mm))

    # ===== MUSTERI BILGILERI + ODEME SEKLI kutulari =====
    customer = deal.customer
    customer_person_name = f"{_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}".strip()

    customer_box = [
        Paragraph("MÜŞTERİYE AİT BİLGİLER", box_heading),
        Spacer(1, 1.5*mm),
        Paragraph(f"<b>Sayın:</b> {customer_person_name or '-'}", normal),
    ]
    if customer.company_name:
        customer_box.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", normal))
    customer_box.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address or '-'}", normal))
    customer_box.append(Paragraph(f"<b>V.D.:</b> {customer.tax_office or '-'}  <b>V.No:</b> {customer.tax_id or '-'}", normal))
    payment_box = [
        Paragraph("ÖDEME ŞEKLİ", box_heading),
        Spacer(1, 1.5*mm),
        Paragraph("<b>Vade (Gün):</b> ...................", normal),
        Paragraph("<b>Peşinat:</b> ...................", normal),
        Paragraph("<b>Bakiye Ödemesi:</b> ...................", normal),
    ]

    info_table = Table([[customer_box, payment_box]], colWidths=[8.6*cm, 8.6*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOX', (0, 0), (0, 0), 0.75, colors.grey),
        ('BOX', (1, 0), (1, 0), 0.75, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 5*mm))

    # ===== URUN TABLOSU =====
    delivery_str = deal.expected_close.strftime('%d.%m.%Y') if deal.expected_close else '-'
    if deal.items:
        col_widths = [3.6*cm, 2.1*cm, 1.2*cm, 1.2*cm, 1.4*cm, 1.6*cm, 1.3*cm, 1.7*cm, 2.0*cm]
        headers = ['Ürün Cinsi', 'Kağıt Cinsi', 'Boy', 'En', 'Renk', 'Miktar', 'Birim', 'Fiyat', 'Teslim\nTarihi']
        data = [[Paragraph(h.replace('\n', '<br/>'), table_header_style) for h in headers]]
        for item in deal.items:
            data.append([
                Paragraph(item.description, small),
                '-', '-', '-', '-',
                f"{item.quantity:.2f}",
                item.unit,
                f"{item.unit_price:,.2f}",
                delivery_str
            ])
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
            ('FONTSIZE', (0, 1), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('TOPPADDING', (0, 0), (-1, 0), 4),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 2*mm))
        totals_data = [
            ['Ara Toplam:', f"{deal.subtotal:,.2f} TL"],
            [f'KDV (%{deal.vat_rate:.0f}):', f"{deal.vat_amount:,.2f} TL"],
            ['TOPLAM:', f"{deal.value:,.2f} TL"],
        ]
        totals_table = Table(totals_data, colWidths=[3*cm, 3*cm], hAlign='RIGHT')
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
            ('FONTNAME', (0, -1), (-1, -1), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(totals_table)
    else:
        elements.append(Paragraph("<i>Henüz ürün eklenmemiş.</i>", normal))

    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("<i>Fiyatlarımıza yürürlükteki K.D.V oranları ilave edilecektir.</i>", normal))
    elements.append(Spacer(1, 4*mm))

    # ===== SARTLAR / KOSULLAR =====
    company_short = company.company_name or 'Lema Ambalaj'
    terms = [
        f"Sipariş, {company_short} tarafından yazılı veya sözlü olarak onaylandığı andan itibaren geçerlilik kazanır.",
        "Teslim süresi, siparişin kesinleşmesi (onay ve varsa peşinatın alınması) tarihinden itibaren başlar.",
        "Fiyatlarımız, hammadde piyasasındaki değişiklikler nedeniyle önceden haber verilmeksizin güncellenebilir; kesinleşmiş siparişler bu durumdan etkilenmez.",
        "Ödemeler, yukarıda belirtilen vade ve tutarlara uygun şekilde yapılır; gecikme durumunda yasal faiz uygulanabilir.",
        "Üretim kapasitesine bağlı olarak kısmi teslimat yapılabilir.",
        "Mücbir sebep hallerinde (doğal afet, üretim durdurma, hammadde tedarik sorunları vb.) teslim süresi taraflarca yeniden değerlendirilir.",
        "Teslim edilen ürünler, teslim anında alıcı tarafından kontrol edilir; görünür hata ve eksiklikler ancak teslim anında bildirilirse dikkate alınır.",
        "Siparişin iptali, üretime başlanmadan önce yazılı bildirimle mümkündür; üretime başlanmış siparişlerde iptal talepleri değerlendirmeye tabidir.",
    ]
    for i, t in enumerate(terms, 1):
        elements.append(Paragraph(f"{i}. {t}", terms_style))
    elements.append(Spacer(1, 8*mm))

    # ===== IMZA KUTULARI =====
    signature_data = [
        [f'Firma Adına Sipariş Veren', '', f'{company_short} Adına Sipariş Alan'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['İmza:', '', 'İmza:'],
        ['Ünvanı:', '', 'Ünvanı:'],
    ]
    signature_table = Table(signature_data, colWidths=[7.5*cm, 2.2*cm, 7.5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTNAME', (0, 0), (0, 0), 'Vera-Bold'),
        ('FONTNAME', (2, 0), (2, 0), 'Vera-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_invoice_pdf(invoice):
    """Fatura (type='fatura') veya Irsaliye (type='irsaliye') kaydi icin PDF.
    Is 2: invoice_detail sayfasinda daha once hic PDF indirme secenegi
    yoktu - hem fatura hem irsaliye icin bu tek fonksiyon kullanilir."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)

    company = _get_company_settings_for_pdf()

    styles = getSampleStyleSheet()
    normal = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9, leading=12)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=8, leading=10)
    title_style = ParagraphStyle('TitleStyle', parent=normal, fontName='Vera-Bold', fontSize=18, leading=22)
    heading_style = ParagraphStyle('HeadingStyle', parent=normal, fontName='Vera-Bold', fontSize=11, leading=14, spaceAfter=5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=14, leading=17)

    is_fatura = invoice.type == 'fatura'
    doc_title = 'FATURA' if is_fatura else 'İRSALİYE'
    customer = invoice.customer

    elements = []

    header_left = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
    if company.address:
        header_left.append(Paragraph(company.address.replace('\n', '<br/>'), small))
    contact_bits = [b for b in [
        f"Tel: {company.phone}" if company.phone else None,
        company.email or None,
    ] if b]
    if contact_bits:
        header_left.append(Paragraph(' | '.join(contact_bits), small))
    if company.tax_office or company.tax_id:
        header_left.append(Paragraph(f"V.D.: {company.tax_office or '-'}  V.No: {company.tax_id or '-'}", small))

    header_right = [
        Paragraph(doc_title, title_style),
        Spacer(1, 2*mm),
        Paragraph(f"<b>{invoice.display_no}</b>", normal),
        Paragraph(f"Tarih: {invoice.date.strftime('%d.%m.%Y') if invoice.date else '-'}", normal),
        Paragraph(f"Teklif: {invoice.deal.display_no}", normal),
    ]

    header_table = Table([[header_left, header_right]], colWidths=[11*cm, 6*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 4*mm))
    elements.append(Table([['']], colWidths=[17*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    person_name = f"{_clean_for_pdf(customer.first_name) or ''} {_clean_for_pdf(customer.last_name) or ''}".strip()
    elements.append(Paragraph(f"<b>Sayın:</b> {person_name or '-'}", normal))
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", normal))
    elements.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address or '-'}", normal))
    elements.append(Paragraph(f"<b>V.D.:</b> {customer.tax_office or '-'}  <b>V.No:</b> {customer.tax_id or '-'}", normal))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("KALEMLER", heading_style))
    if invoice.items:
        data = [['Açıklama', 'Miktar', 'Birim', 'Birim Fiyat', 'Toplam']]
        for item in invoice.items:
            data.append([
                Paragraph(item.description, small),
                f"{item.quantity:.2f}",
                item.unit,
                f"{item.unit_price:,.2f} TL",
                f"{item.total_price:,.2f} TL"
            ])
        data.append(['', '', '', 'Ara Toplam:', f"{invoice.subtotal:,.2f} TL"])
        data.append(['', '', '', f'KDV (%{invoice.vat_rate:.0f}):', f"{invoice.vat_amount:,.2f} TL"])
        data.append(['', '', '', 'TOPLAM:', f"{invoice.total:,.2f} TL"])

        table = Table(data, colWidths=[6.5*cm, 2*cm, 1.5*cm, 3.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'Vera-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (-2, 0), (-2, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Kalem bulunmuyor.</i>", normal))

    if invoice.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(invoice.notes, normal))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_is_emri_pdf(production):
    """Dahili uretim talimati belgesi - fatura/irsaliye ile karistirilmamali,
    fiyat bilgisi icermez. Atolyeye elden verilmek uzere tasarlandi."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11, spaceAfter=5)

    deal = production.deal
    customer = deal.customer

    elements = []

    elements.append(Paragraph("İŞ EMRİ", title_style))
    elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph(f"<b>İş Emri No:</b> IE-{production.id:05d}", turkish_style))
    elements.append(Paragraph(f"<b>Tarih:</b> {datetime.now().strftime('%d.%m.%Y')}", turkish_style))
    elements.append(Paragraph(f"<b>Teklif No:</b> {deal.display_no}", turkish_style))
    customer_name = _clean_for_pdf(customer.company_name) if customer.company_name else \
        f"{_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}"
    elements.append(Paragraph(f"<b>Müşteri:</b> {customer_name}", turkish_style))
    if production.due_date:
        elements.append(Paragraph(f"<b>Teslim Tarihi:</b> {production.due_date.strftime('%d.%m.%Y')}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("ÜRÜN KALEMLERİ", heading_style))

    if production.items:
        data = [['Açıklama', 'Ölçü', 'Baskı Rengi/Sayısı', 'Kağıt Tipi', 'Gramaj', 'Planlanan Adet']]
        for item in production.items:
            data.append([
                Paragraph(item.description, turkish_style),
                item.olcu or '-',
                item.baski_bilgisi or '-',
                item.kagit_tipi or '-',
                item.gramaj or '-',
                f"{item.planned_quantity:.0f} {item.unit}"
            ])
        table = Table(data, colWidths=[4*cm, 2.3*cm, 3*cm, 2.7*cm, 2*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", turkish_style))

    elements.append(Spacer(1, 8*mm))
    elements.append(Paragraph("NOTLAR", heading_style))
    notes_table = Table([['']], colWidths=[17*cm], rowHeights=[3*cm])
    notes_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(notes_table)

    elements.append(Spacer(1, 15*mm))
    signature_data = [
        ['Üretimi Yapan:', '', 'Kontrol Eden:'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['Tarih:', '', 'Tarih:'],
    ]
    signature_table = Table(signature_data, colWidths=[5*cm, 4*cm, 5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_irsaliye_pdf(shipment):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11, spaceAfter=5)

    production = shipment.production
    customer = production.deal.customer

    elements = []

    elements.append(Paragraph("İRSALİYE", title_style))
    elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph(f"<b>Sevkiyat No:</b> SVN-{shipment.id:05d}", turkish_style))
    elements.append(Paragraph(f"<b>Teklif No:</b> {production.deal.display_no}", turkish_style))
    elements.append(Paragraph(f"<b>Gönderim Tarihi:</b> {shipment.ship_date.strftime('%d.%m.%Y') if shipment.ship_date else '-'}", turkish_style))
    if shipment.carrier:
        elements.append(Paragraph(f"<b>Kargo Firması:</b> {shipment.carrier}", turkish_style))
    if shipment.tracking_number:
        elements.append(Paragraph(f"<b>Takip No:</b> {shipment.tracking_number}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", turkish_style))
    elements.append(Paragraph(f"<b>Ad Soyad:</b> {_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}", turkish_style))
    if customer.company_address or customer.address:
        elements.append(Paragraph(f"<b>Adres:</b> {customer.company_address or customer.address}", turkish_style))
    if customer.company_phone or customer.phone:
        elements.append(Paragraph(f"<b>Telefon:</b> {customer.company_phone or customer.phone}", turkish_style))
    elements.append(Spacer(1, 5*mm))

    elements.append(Paragraph("ÜRÜN / MİKTAR", heading_style))

    if production.items:
        data = [['#', 'Açıklama', 'Miktar', 'Birim']]
        for i, item in enumerate(production.items, 1):
            data.append([
                str(i),
                Paragraph(item.description, turkish_style),
                f"{item.produced_quantity:.2f}",
                item.unit
            ])
        table = Table(data, colWidths=[1*cm, 9*cm, 3*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", turkish_style))

    if shipment.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(shipment.notes, turkish_style))

    elements.append(Spacer(1, 15*mm))
    signature_data = [
        ['Teslim Eden:', '', 'Teslim Alan:'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['Tarih:', '', 'Tarih:'],
    ]
    signature_table = Table(signature_data, colWidths=[5*cm, 4*cm, 5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
        ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
    ]))
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_statement_pdf(customer, statements, total_debit, total_credit):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=16)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11)
    
    elements = []
    
    elements.append(Paragraph("MÜŞTERİ EKSTRESİ", title_style))
    elements.append(Spacer(1, 8*mm))
    
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {_clean_for_pdf(customer.company_name)}", turkish_style))
    elements.append(Paragraph(f"<b>Müşteri:</b> {_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}", turkish_style))
    if customer.contact_person:
        elements.append(Paragraph(f"<b>Yetkili:</b> {customer.contact_person}", turkish_style))
    elements.append(Paragraph(f"<b>E-posta:</b> {customer.email}", turkish_style))
    elements.append(Paragraph(f"<b>Rapor Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}", turkish_style))
    elements.append(Spacer(1, 5*mm))
    
    if statements:
        data = [['Tarih', 'Tür', 'Açıklama', 'Tutar']]
        for s in statements:
            data.append([
                s.created_at.strftime('%d.%m.%Y'),
                s.type.upper(),
                Paragraph(s.description or '-', turkish_style),
                f"{s.amount:,.2f} TL"
            ])
        
        data.append(['', '', 'TOPLAM BORÇ:', f"{total_debit:,.2f} TL"])
        data.append(['', '', 'TOPLAM ALACAK:', f"{total_credit:,.2f} TL"])
        data.append(['', '', 'BAKİYE:', f"{total_debit - total_credit:,.2f} TL"])
        
        table = Table(data, colWidths=[2.5*cm, 2*cm, 7.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'Vera-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Henüz işlem bulunmuyor.</i>", turkish_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer
