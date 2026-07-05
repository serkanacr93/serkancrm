from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import os
from datetime import datetime

def register_fonts():
    font_paths = [
        ("DejaVuSans", "C:/Windows/Fonts/arial.ttf"),
        ("DejaVuSans-Bold", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for font_name, font_path in font_paths:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont(font_name, font_path))

register_fonts()

def generate_deal_pdf(deal):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='DejaVuSans', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='DejaVuSans-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='DejaVuSans-Bold', fontSize=11, spaceAfter=5)
    
    elements = []
    
    elements.append(Paragraph("TEKLİF / FİYAT LİSTESİ", title_style))
    elements.append(Spacer(1, 8*mm))
    
    elements.append(Paragraph(f"<b>Teklif No:</b> TKL-{deal.id:05d}", turkish_style))
    elements.append(Paragraph(f"<b>Teklif Tarihi:</b> {deal.deal_date.strftime('%d.%m.%Y') if deal.deal_date else deal.created_at.strftime('%d.%m.%Y')}", turkish_style))
    if deal.valid_until:
        days_left = deal.days_until_expire
        validity_text = f"<b>Geçerlilik:</b> {deal.valid_until.strftime('%d.%m.%Y')}"
        if days_left is not None and days_left >= 0:
            validity_text += f" (Kalan: {days_left} gün)"
        else:
            validity_text += " (Süresi dolmuş)"
        elements.append(Paragraph(validity_text, turkish_style))
    elements.append(Spacer(1, 5*mm))
    
    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", heading_style))
    if deal.customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {deal.customer.company_name}", turkish_style))
    elements.append(Paragraph(f"<b>Ad Soyad:</b> {deal.customer.first_name} {deal.customer.last_name}", turkish_style))
    if deal.customer.contact_person:
        elements.append(Paragraph(f"<b>Yetkili Kişi:</b> {deal.customer.contact_person} ({deal.customer.contact_title or ''})", turkish_style))
    if deal.customer.tax_id:
        elements.append(Paragraph(f"<b>Vergi No:</b> {deal.customer.tax_id}", turkish_style))
    if deal.customer.tax_office:
        elements.append(Paragraph(f"<b>Vergi Dairesi:</b> {deal.customer.tax_office}", turkish_style))
    if deal.customer.company_email:
        elements.append(Paragraph(f"<b>E-posta:</b> {deal.customer.company_email}", turkish_style))
    elif deal.customer.email:
        elements.append(Paragraph(f"<b>E-posta:</b> {deal.customer.email}", turkish_style))
    if deal.customer.company_phone:
        elements.append(Paragraph(f"<b>Telefon:</b> {deal.customer.company_phone}", turkish_style))
    elif deal.customer.phone:
        elements.append(Paragraph(f"<b>Telefon:</b> {deal.customer.phone}", turkish_style))
    elements.append(Spacer(1, 5*mm))
    
    elements.append(Paragraph("ÜRÜN / HİZMET DETAYLARI", heading_style))
    
    if deal.items:
        data = [['#', 'Açıklama', 'Miktar', 'Birim', 'Birim Fiyat', 'Toplam']]
        for i, item in enumerate(deal.items, 1):
            data.append([
                str(i),
                Paragraph(item.description, turkish_style),
                f"{item.quantity:.2f}",
                item.unit,
                f"{item.unit_price:,.2f} ₺",
                f"{item.total_price:,.2f} ₺"
            ])
        
        data.append(['', '', '', '', 'Ara Toplam:', f"{deal.subtotal:,.2f} ₺"])
        data.append(['', '', '', '', f'KDV (%{deal.vat_rate:.0f}):', f"{deal.vat_amount:,.2f} ₺"])
        data.append(['', '', '', '', 'TOPLAM:', f"{deal.value:,.2f} ₺"])
        
        table = Table(data, colWidths=[1*cm, 5.5*cm, 2*cm, 1.5*cm, 3*cm, 3*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'DejaVuSans-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (-2, 0), (-2, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Henüz ürün eklenmemiş.</i>", turkish_style))
    
    elements.append(Spacer(1, 8*mm))
    
    if deal.notes:
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(deal.notes, turkish_style))
    
    elements.append(Spacer(1, 15*mm))
    elements.append(Paragraph("Bu teklif yukarıdaki tarihe kadar geçerlidir.", turkish_style))
    elements.append(Spacer(1, 12*mm))
    
    signature_data = [
        ['Müşteri İmzası:', '', 'Yetkili İmza:'],
        ['', '', ''],
        ['', '', ''],
        ['Adı Soyadı:', '', 'Adı Soyadı:'],
        ['Tarih:', '', 'Tarih:'],
    ]
    signature_table = Table(signature_data, colWidths=[5*cm, 4*cm, 5*cm])
    signature_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
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
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='DejaVuSans', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='DejaVuSans-Bold', fontSize=16)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='DejaVuSans-Bold', fontSize=11)
    
    elements = []
    
    elements.append(Paragraph("MÜŞTERİ EKSTRESİ", title_style))
    elements.append(Spacer(1, 8*mm))
    
    if customer.company_name:
        elements.append(Paragraph(f"<b>Firma:</b> {customer.company_name}", turkish_style))
    elements.append(Paragraph(f"<b>Müşteri:</b> {customer.first_name} {customer.last_name}", turkish_style))
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
                f"{s.amount:,.2f} ₺"
            ])
        
        data.append(['', '', 'TOPLAM BORÇ:', f"{total_debit:,.2f} ₺"])
        data.append(['', '', 'TOPLAM ALACAK:', f"{total_credit:,.2f} ₺"])
        data.append(['', '', 'BAKİYE:', f"{total_debit - total_credit:,.2f} ₺"])
        
        table = Table(data, colWidths=[2.5*cm, 2*cm, 7.5*cm, 3.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'DejaVuSans-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (-1, -3), (-1, -1), colors.HexColor('#e8f4f8')),
            ('FONTNAME', (-1, -3), (-1, -1), 'DejaVuSans-Bold'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.white, colors.HexColor('#f8f9fa')]),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("<i>Henüz işlem bulunmuyor.</i>", turkish_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer
