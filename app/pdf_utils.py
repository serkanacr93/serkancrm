from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
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

def _sanitize_pdf_free_text(text):
    """Serbest metin alanlarinda (Aciklama/Not kutulari) kullanicinin elle
    yazdigi ' TL' isareti (U+20BA) Vera fontunda glif olarak bulunmuyor -
    PDF'te bozuk/kare karakter olarak cikiyordu. PDF'in geri kalaninda zaten
    tutarli sekilde 'TL' metni kullanildigi icin (bkz. Ara Toplam/KDV/Toplam
    kutulari) ayni donusum burada da uygulanir."""
    if not text:
        return text
    return text.replace('₺', 'TL')

def _draw_watermark(canvas, doc, text):
    """Sayfa ortasinda TEK, buyuk, ince cerceveli (sadece kontur - ici bos)
    bir filigran ciziyor, -25 derece egik. onFirstPage/onLaterPages
    callback'i olarak cagrilir - reportlab bu callback'i sayfanin flowable
    icerigi (tablo/metin) cizilmeden ONCE calistirir, bu yuzden filigran
    otomatik olarak icerigin ALTINDA kalir, ustune binmez. Ici dolu
    olmamasi icin PDFTextObject.setTextRenderMode(1) (Tr 1 = sadece kontur
    ciz, doldurma) kullanilir - drawString gibi normal metin cizim
    fonksiyonlari her zaman ICI DOLU (fill) cizer, bu yuzden dogrudan
    text object uzerinden calisilir."""
    if not text:
        return
    canvas.saveState()
    canvas.translate(A4[0] / 2.0, A4[1] / 2.0)
    canvas.rotate(-25)
    font_size = 65
    canvas.setLineWidth(1.1)
    canvas.setStrokeColorRGB(20 / 255.0, 20 / 255.0, 40 / 255.0)
    text_w = canvas.stringWidth(text, 'Vera-Bold', font_size)
    text_obj = canvas.beginText(-text_w / 2.0, -font_size / 3.0)
    text_obj.setFont('Vera-Bold', font_size)
    text_obj.setTextRenderMode(1)  # 1 = stroke only (kontur), fill yok
    text_obj.textOut(text)
    canvas.drawText(text_obj)
    canvas.restoreState()

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

def _payment_method_checkboxes(text_style):
    """Nakit/KK/Cek/Senet icin cizilmis kutucuklar dondurur (Vera fontunda
    Unicode checkbox glifi (U+2610) bulunmuyor, o yuzden kucuk BOX kenarli
    hucreler kullanilir)."""
    labels = ['Nakit', 'KK', 'Çek', 'Senet']
    row = []
    widths = []
    for label in labels:
        row.append('')
        widths.append(0.35*cm)
        row.append(Paragraph(label, text_style))
        widths.append(1.4*cm)
    table = Table([row], colWidths=widths)
    box_cols = [i for i in range(0, len(row), 2)]
    style = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]
    for c in box_cols:
        style.append(('BOX', (c, 0), (c, 0), 0.75, colors.black))
    table.setStyle(TableStyle(style))
    return table

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
    tekliften gelir. Vade/Pesinat/Bakiye Deal alanlarindan geliyor (bos ise
    noktali cizgi kalir). Kagit Cinsi/Boy/En/Renk/Teslim Tarihi sutunlari
    DealItem'dan gelir, doldurulmamis olan alanlar '-' ile gosterilir.
    AÇIKLAMA kutusu deal.notes'tan doldurulur."""
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
    company_text_block = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
    if company.address:
        company_text_block.append(Paragraph(company.address.replace('\n', '<br/>'), small))
    contact_bits = []
    if company.phone:
        contact_bits.append(f"Tel: {company.phone}")
    if company.fax:
        contact_bits.append(f"Faks: {company.fax}")
    if contact_bits:
        company_text_block.append(Paragraph(' | '.join(contact_bits), small))
    contact_bits2 = []
    if company.email:
        contact_bits2.append(company.email)
    if company.website:
        contact_bits2.append(company.website)
    if contact_bits2:
        company_text_block.append(Paragraph(' | '.join(contact_bits2), small))
    if company.tax_office or company.tax_id:
        company_text_block.append(Paragraph(f"V.D.: {company.tax_office or '-'}  V.No: {company.tax_id or '-'}", small))

    logo_img = None
    if company.logo_data:
        try:
            from PIL import Image as PILImage
            PILImage.open(BytesIO(company.logo_data)).verify()
            # Logo, firma adinin SOLUNDA, dikey ortalanmis olarak gosteriliyor
            # (eskiden ustte ayri bir kutuda, kucuk boyuttaydi). Boyut ~%45
            # buyutuldu (3.5x1.8cm -> 5.1x2.6cm) ve metin blogunun toplam
            # yuksekligine yakinlasmasi hedeflendi.
            logo_img = Image(BytesIO(company.logo_data), width=5.1*cm, height=2.6*cm, kind='proportional')
        except Exception:
            logo_img = None

    if logo_img is not None:
        logo_row_table = Table([[logo_img, company_text_block]], colWidths=[5.1*cm, 5.9*cm])
        logo_row_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            # logo ile metin arasinda 10-15pt bosluk
            ('RIGHTPADDING', (0, 0), (0, 0), 12),
            ('LEFTPADDING', (1, 0), (1, 0), 0),
            ('RIGHTPADDING', (1, 0), (1, 0), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        left_cell = [logo_row_table]
    else:
        left_cell = company_text_block

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

    dots = "..................."
    payment_box = [
        Paragraph("ÖDEME ŞEKLİ", box_heading),
        Spacer(1, 1.5*mm),
        Paragraph(f"<b>Vade (Gün):</b> {deal.vade_gun or dots}", normal),
        Paragraph(f"<b>Peşinat:</b> {deal.pesinat or dots}", normal),
        Paragraph(f"<b>Bakiye Ödemesi:</b> {deal.bakiye_odemesi or dots}", normal),
        Spacer(1, 2*mm),
        _payment_method_checkboxes(normal),
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
    # Kagit Cinsi/Boy/En/Renk/Teslim Tarihi DealItem'da yapisal olarak
    # tutuluyor (teklif formundan doldurulur, hepsi opsiyonel) - doluysa
    # gercek deger, bossa '-' gosterilir. Kalemin kendi teslim tarihi
    # girilmemisse teklifin genel beklenen kapanis tarihine dusulur.
    deal_delivery_fallback = deal.expected_close.strftime('%d.%m.%Y') if deal.expected_close else '-'
    # Coklu Para Birimi - TRY icin Vera fontunda ₺ glifi olmadigindan
    # (bkz. _sanitize_pdf_free_text) tutarlar hep 'TL' metniyle gosterilir;
    # EUR/USD sembolleri Vera'da mevcut, dogrudan kullanilabilir.
    para_birimi_text = 'TL' if deal.para_birimi == 'TRY' else deal.para_birimi_sembol
    if deal.items:
        table_small = ParagraphStyle('TableSmall', parent=small, fontSize=8, leading=10)
        table_header_style_normal = ParagraphStyle('TableHeaderNormal', parent=table_header_style, fontSize=8, leading=10)
        # Kagit Cinsi/Boy/En/Renk onceden DUZ METIN olarak ekleniyordu - Table
        # hucrelerinde duz metin SARMAZ (sadece Paragraph flowable'lar sarar),
        # bu yuzden uzun bir deger hucre sinirini asip yandaki sutune biniyordu.
        # Paragraph'a cevirip dar sutunlara uygun kucuk/ortali bir stil verildi.
        table_narrow = ParagraphStyle('TableNarrow', parent=small, fontSize=7.5, leading=9, alignment=1)
        col_widths = [4.0*cm, 2.1*cm, 1.6*cm, 1.6*cm, 1.3*cm, 1.6*cm, 1.3*cm, 1.8*cm, 1.8*cm]
        headers = ['Ürün Cinsi', 'Kağıt Cinsi', 'Boy', 'En', 'Renk', 'Miktar', 'Birim', f'Fiyat\n({para_birimi_text})', 'Teslim\nTarihi']
        data = [[Paragraph(h.replace('\n', '<br/>'), table_header_style_normal) for h in headers]]

        def _pdf_cell_text(value):
            # Paragraph icerigi (duz metnin aksine) XML/HTML olarak
            # ayristirilir - kullanicinin elle girdigi bir '<'/'>'/'&' PDF
            # olusturmayi kirmasin diye kacis karakterleri uygulanir.
            from xml.sax.saxutils import escape
            cleaned = _sanitize_pdf_free_text(value)
            return escape(cleaned) if cleaned else '-'

        for item in deal.items:
            item_delivery_str = item.teslim_tarihi.strftime('%d.%m.%Y') if item.teslim_tarihi else deal_delivery_fallback
            data.append([
                Paragraph(_pdf_cell_text(item.description), table_small),
                Paragraph(_pdf_cell_text(item.kagit_cinsi), table_narrow),
                Paragraph(_pdf_cell_text(item.boy), table_narrow),
                Paragraph(_pdf_cell_text(item.en), table_narrow),
                Paragraph(_pdf_cell_text(item.renk), table_narrow),
                f"{item.quantity:.2f}",
                item.unit,
                f"{item.unit_price:,.2f}",
                item_delivery_str
            ])
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ]))
        elements.append(table)

        elements.append(Spacer(1, 2*mm))
        totals_data = [
            ['Ara Toplam:', f"{deal.subtotal:,.2f} {para_birimi_text}"],
            [f'KDV (%{deal.vat_rate:.0f}):', f"{deal.vat_amount:,.2f} {para_birimi_text}"],
            ['TOPLAM:', f"{deal.value:,.2f} {para_birimi_text}"],
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

        # Doviz teklifte, kullanilan_kur girilmisse gosterge TL karsiligi
        if deal.para_birimi != 'TRY' and deal.kullanilan_kur:
            elements.append(Spacer(1, 1*mm))
            kur_note = ParagraphStyle('KurNote', parent=terms_style, alignment=2)
            elements.append(Paragraph(
                f"Gösterge kur: 1 {deal.para_birimi} = {deal.kullanilan_kur:,.4f} TL &nbsp;-&nbsp; "
                f"yaklaşık TL karşılığı: {deal.tl_karsiligi:,.2f} TL",
                kur_note
            ))
    else:
        elements.append(Paragraph("<i>Henüz ürün eklenmemiş.</i>", normal))

    elements.append(Spacer(1, 4*mm))
    elements.append(Paragraph("<i>Fiyatlarımıza yürürlükteki K.D.V oranları ilave edilecektir.</i>", normal))
    elements.append(Spacer(1, 4*mm))

    # ===== ACIKLAMA (deal.notes'tan doldurulur, bossa bos kutu kalir) =====
    elements.append(Paragraph("AÇIKLAMA", box_heading))
    if deal.notes:
        from xml.sax.saxutils import escape
        notes_paragraph = Paragraph(escape(_sanitize_pdf_free_text(deal.notes)).replace('\n', '<br/>'), normal)
        aciklama_table = Table([[notes_paragraph]], colWidths=[17.2*cm])
        aciklama_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
    else:
        aciklama_table = Table([['']], colWidths=[17.2*cm], rowHeights=[2*cm])
        aciklama_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
    elements.append(aciklama_table)
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
    if deal.para_birimi != 'TRY':
        # Doviz sartlar metni - odemeler ayri gunlerde farkli kurla
        # gelebilecegi icin (bkz. Payment.kur_orani), her tahsilatin
        # kendi gununun TCMB kuru uzerinden TL'ye cevrilecegi acikca belirtilir.
        terms.append(
            f"İşbu teklif {deal.para_birimi} cinsindendir; ödemeler, ödemenin yapıldığı gün geçerli olan "
            f"T.C. Merkez Bankası döviz satış kuru üzerinden Türk Lirası karşılığı olarak tahsil edilir."
        )
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

    watermark_text = (company.company_name or 'LEMA AMBALAJ').upper()
    _watermark_cb = lambda cnv, d: _draw_watermark(cnv, d, watermark_text)
    doc.build(elements, onFirstPage=_watermark_cb, onLaterPages=_watermark_cb)
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
    heading_style = ParagraphStyle('HeadingStyle', parent=normal, fontName='Vera-Bold', fontSize=11, leading=14, spaceAfter=5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=14, leading=17)

    is_fatura = invoice.type == 'fatura'
    # ONEMLI: bu kayit RESMI bir vergi faturasi DEGIL, sadece dahili
    # takip amacli bir kayit (gercek resmi fatura ayri bir muhasebe
    # programinda kesiliyor) - baslikta "FATURA" tek basina resmi belge
    # izlenimi verebilecegi icin notr bir ifade kullaniliyor.
    if is_fatura:
        doc_title = 'FATURA / TAHSİLAT<br/>TAKİP BELGESİ'
        title_style = ParagraphStyle('TitleStyle', parent=normal, fontName='Vera-Bold', fontSize=13, leading=16)
    else:
        doc_title = 'İRSALİYE'
        title_style = ParagraphStyle('TitleStyle', parent=normal, fontName='Vera-Bold', fontSize=18, leading=22)
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
    ]
    if invoice.deal:
        header_right.append(Paragraph(f"Teklif: {invoice.deal.display_no}", normal))

    header_table = Table([[header_left, header_right]], colWidths=[10.5*cm, 6.5*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        # Uzun (2 satirli) "FATURA / TAHSİLAT TAKİP BELGESİ" basligi eklendikten
        # sonra iki sutun arasinda hic bosluk olmamasi (RIGHTPADDING=0) sol
        # sutundaki firma adresiyle gorsel olarak neredeyse cakisiyordu -
        # sol sutuna kucuk bir sag bosluk eklendi.
        ('RIGHTPADDING', (0, 0), (0, -1), 10),
        ('RIGHTPADDING', (1, 0), (1, -1), 0),
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
        elements.append(Paragraph(_sanitize_pdf_free_text(invoice.notes), normal))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_is_emri_pdf(production, copy_label=None):
    """Dahili uretim talimati belgesi - fatura/irsaliye ile karistirilmamali,
    fiyat bilgisi icermez. Atolyeye elden verilmek uzere tasarlandi.
    copy_label: 'Baski Ustasi' / 'Makine Ustasi' gibi nusha etiketi (opsiyonel).

    Is 1: Birden fazla uretim kalemi varsa HER KALEM KENDI AYRI SAYFASINDA
    olusturulur (atolyede kalem basina ayri kagit/is takibi yapilabilsin
    diye) - tasarim gorseli de artik cok daha buyuk (tam genislik) basiliyor."""
    from app.models import PRODUCTION_STAGES

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.3*cm, leftMargin=1.3*cm, topMargin=1.3*cm, bottomMargin=1.3*cm)

    company = _get_company_settings_for_pdf()

    normal = ParagraphStyle('TurkishStyle', fontName='Vera', fontSize=9, leading=12)
    small = ParagraphStyle('SmallStyle', parent=normal, fontSize=7.5, leading=10)
    heading_style = ParagraphStyle('HeadingStyle', parent=normal, fontName='Vera-Bold', fontSize=11, leading=14, spaceAfter=5)
    company_name_style = ParagraphStyle('CompanyName', parent=normal, fontName='Vera-Bold', fontSize=15, leading=18)
    badge_style = ParagraphStyle('BadgeStyle', parent=normal, fontName='Vera-Bold', fontSize=15, leading=18,
                                  textColor=colors.white, alignment=1)
    copy_style = ParagraphStyle('CopyStyle', parent=normal, fontName='Vera-Bold', fontSize=9, leading=11, alignment=2)
    table_header_style = ParagraphStyle('TableHeaderIE', parent=normal, fontName='Vera-Bold', fontSize=8, leading=10,
                                         textColor=colors.white, alignment=1)
    customer_name_style = ParagraphStyle('CustomerNameBig', parent=normal, fontName='Vera-Bold', fontSize=20, leading=24)

    deal = production.deal
    customer = deal.customer
    customer_name = _clean_for_pdf(customer.company_name) if customer.company_name else \
        f"{_clean_for_pdf(customer.first_name)} {_clean_for_pdf(customer.last_name)}"

    uretim_items = production.uretim_items
    # Kalem yoksa yine de tek, bilgilendirici bir sayfa uretilsin.
    pages = uretim_items if uretim_items else [None]
    total_pages = len(pages)

    elements = []

    for page_idx, item in enumerate(pages, 1):
        # ===== 1) Firma adi (buyuk) + vergi/adres (kucuk) - solda =====
        header_left = [Paragraph(company.company_name or 'Lema Ambalaj', company_name_style)]
        legal_bits = []
        if company.address:
            legal_bits.append(company.address)
        if company.tax_office or company.tax_id:
            legal_bits.append(f"V.D.: {company.tax_office or '-'} V.No: {company.tax_id or '-'}")
        if legal_bits:
            header_left.append(Paragraph(' | '.join(legal_bits), small))

        # ===== 2) Sagda koyu arka planli "IS EMRI" rozeti =====
        badge_table = Table([[Paragraph('İŞ EMRİ', badge_style)]], colWidths=[4.5*cm], rowHeights=[1*cm])
        badge_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1a252f')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        header_right = [badge_table, Spacer(1, 2*mm)]
        # ===== 3) Nusha etiketi + sayfa no =====
        if copy_label:
            header_right.append(Paragraph(f"Nüsha: {copy_label}", copy_style))
        header_right.append(Paragraph(f"IE-{production.id:05d}", copy_style))
        if total_pages > 1:
            header_right.append(Paragraph(f"Sayfa {page_idx}/{total_pages}", copy_style))
        header_right.append(Paragraph(f"Tarih: {datetime.now().strftime('%d.%m.%Y')}", copy_style))

        header_table = Table([[header_left, header_right]], colWidths=[12.5*cm, 4.7*cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 4*mm))
        elements.append(Table([['']], colWidths=[17.2*cm], style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1a252f'))]))
        elements.append(Spacer(1, 4*mm))

        # ===== Musteri adi - buyuk punto, tabloda =====
        customer_name_table = Table([[Paragraph(customer_name, customer_name_style)]], colWidths=[17.2*cm])
        customer_name_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(customer_name_table)
        elements.append(Spacer(1, 3*mm))

        elements.append(Paragraph(f"<b>Teklif No:</b> {deal.display_no}", normal))
        # ===== 5) Teslim tarihi =====
        if production.due_date:
            elements.append(Paragraph(f"<b>Teslim Tarihi:</b> {production.due_date.strftime('%d.%m.%Y')}", normal))
        elements.append(Spacer(1, 4*mm))

        # ===== 4) Durum cubugu: Uretimde -> Hazir -> Sevkiyat =====
        if production.status != 'iptal':
            try:
                active_idx = [k for k, _ in PRODUCTION_STAGES].index(production.status)
            except ValueError:
                active_idx = -1
            status_cells = []
            for i, (key, label) in enumerate(PRODUCTION_STAGES):
                if i == active_idx:
                    fg = colors.white
                elif i < active_idx:
                    fg = colors.HexColor('#1a252f')
                else:
                    fg = colors.grey
                cell_style = ParagraphStyle(f'Stage{page_idx}_{i}', parent=normal, fontName='Vera-Bold', fontSize=8,
                                             alignment=1, textColor=fg)
                status_cells.append(Paragraph(label, cell_style))
            status_table = Table([status_cells], colWidths=[5.7*cm]*3)
            style = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]
            for i, (key, label) in enumerate(PRODUCTION_STAGES):
                bg = colors.HexColor('#1a252f') if i == active_idx else (colors.HexColor('#c8e6c9') if i < active_idx else colors.HexColor('#f0f0f0'))
                style.append(('BACKGROUND', (i, 0), (i, 0), bg))
            status_table.setStyle(TableStyle(style))
            elements.append(status_table)
            elements.append(Spacer(1, 5*mm))

        # ===== 6) Tasarim gorseli (varsa) - tam genislik, orana sadik =====
        if production.tasarim_gorseli:
            try:
                import os as _os
                img_path = _os.path.join(_os.path.dirname(__file__), 'static', production.tasarim_gorseli)
                with open(img_path, 'rb') as f:
                    img_data = f.read()
                from PIL import Image as PILImage
                PILImage.open(BytesIO(img_data)).verify()
                elements.append(Paragraph("TASARIM GÖRSELİ", heading_style))
                # Genislik tam sayfa genisligine kadar kullanilir (yatay/genis
                # gorseller icin), yukseklik 7.5cm ile sinirlanir ki alttaki
                # urun tablosu/notlar/imza alani ayni sayfada tasmadan sigsin.
                elements.append(Image(BytesIO(img_data), width=17.2*cm, height=7.5*cm, kind='proportional'))
                elements.append(Spacer(1, 4*mm))
            except Exception:
                pass

        # ===== 7) Tablo: Kagit Cinsi | Kac Kg | Baski Rengi | Olcu | Planlanan | Gerceklesen =====
        # Is 4: 'ticaret' tipi kalemler atolyede uretilmedigi icin bu dahili
        # uretim talimatina dahil edilmez (ayri, basit bir durumla takip edilir).
        elements.append(Paragraph("ÜRÜN KALEMİ", heading_style))

        if item is not None:
            headers = ['Kağıt Cinsi', 'Kaç Kg', 'Baskı Rengi', 'Ölçü', 'Planlanan Adet', 'Gerçekleşen Adet']
            data = [[Paragraph(h, table_header_style) for h in headers]]
            kagit_cell = item.kagit_tipi or item.description
            if item.kagit_tipi and item.description:
                kagit_cell = f"{item.kagit_tipi}<br/><font size=6>{item.description}</font>"
            data.append([
                Paragraph(kagit_cell, small),
                item.kac_kg or '-',
                item.baski_bilgisi or '-',
                item.olcu or '-',
                f"{item.planned_quantity:.0f} {item.unit}",
                f"{item.produced_quantity:.0f} {item.unit}" if item.produced_quantity else '-'
            ])
            table = Table(data, colWidths=[4.5*cm, 2.2*cm, 3*cm, 2.5*cm, 2.5*cm, 2.5*cm], repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a252f')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 1), (-1, -1), 'Vera'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
                ('TOPPADDING', (0, 0), (-1, 0), 4),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph("<i>Ürün kalemi bulunamadı.</i>", normal))

        elements.append(Spacer(1, 6*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        notes_table = Table([['']], colWidths=[17.2*cm], rowHeights=[2.5*cm])
        notes_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(notes_table)
        elements.append(Spacer(1, 8*mm))

        # ===== 8) UC imza alani =====
        signature_data = [
            ['Üretimi Yapan:', '', 'Kontrol Eden:', '', 'Teslim Alan:'],
            ['', '', '', '', ''],
            ['', '', '', '', ''],
            ['Adı Soyadı:', '', 'Adı Soyadı:', '', 'Adı Soyadı:'],
            ['Tarih:', '', 'Tarih:', '', 'Tarih:'],
        ]
        signature_table = Table(signature_data, colWidths=[5*cm, 1.1*cm, 5*cm, 1.1*cm, 5*cm])
        signature_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Vera'),
            ('FONTNAME', (0, 0), (0, 0), 'Vera-Bold'),
            ('FONTNAME', (2, 0), (2, 0), 'Vera-Bold'),
            ('FONTNAME', (4, 0), (4, 0), 'Vera-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LINEBELOW', (0, 2), (0, 2), 1, colors.black),
            ('LINEBELOW', (2, 2), (2, 2), 1, colors.black),
            ('LINEBELOW', (4, 2), (4, 2), 1, colors.black),
        ]))
        elements.append(signature_table)

        if page_idx < total_pages:
            elements.append(PageBreak())

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
        elements.append(Paragraph(_sanitize_pdf_free_text(shipment.notes), turkish_style))

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

def generate_manual_irsaliye_pdf(manual_irsaliye):
    """generate_irsaliye_pdf ile ayni gorsel format - ama Shipment/Production
    yerine dogrudan ManualIrsaliye+customer'dan besleniyor (teklif/uretim
    kaydi olmadan olusturulan bagimsiz irsaliyeler icin)."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    turkish_style = ParagraphStyle('TurkishStyle', parent=styles['Normal'], fontName='Vera', fontSize=9)
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName='Vera-Bold', fontSize=18)
    heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontName='Vera-Bold', fontSize=11, spaceAfter=5)

    customer = manual_irsaliye.customer

    elements = []

    elements.append(Paragraph("İRSALİYE", title_style))
    elements.append(Spacer(1, 8*mm))

    elements.append(Paragraph(f"<b>İrsaliye No:</b> {manual_irsaliye.display_no}", turkish_style))
    elements.append(Paragraph(f"<b>Gönderim Tarihi:</b> {manual_irsaliye.ship_date.strftime('%d.%m.%Y') if manual_irsaliye.ship_date else '-'}", turkish_style))
    if manual_irsaliye.carrier:
        elements.append(Paragraph(f"<b>Kargo Firması:</b> {manual_irsaliye.carrier}", turkish_style))
    if manual_irsaliye.tracking_number:
        elements.append(Paragraph(f"<b>Takip No:</b> {manual_irsaliye.tracking_number}", turkish_style))
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

    if manual_irsaliye.items:
        from xml.sax.saxutils import escape
        data = [['#', 'Açıklama', 'Miktar', 'Birim']]
        for i, item in enumerate(manual_irsaliye.items, 1):
            data.append([
                str(i),
                Paragraph(escape(_sanitize_pdf_free_text(item.description) or '-'), turkish_style),
                f"{item.quantity:.2f}",
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

    if manual_irsaliye.notes:
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("NOTLAR", heading_style))
        elements.append(Paragraph(_sanitize_pdf_free_text(manual_irsaliye.notes), turkish_style))

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
