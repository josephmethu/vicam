"""Generate an exact downloadable PDF, then certify its final bytes."""
import hashlib
import io
from html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether,Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from qrcode import QRCode
from qrcode.constants import ERROR_CORRECT_M
from .config import ROOT
from .pdf_signing import sign_pdf

SCHEMA='''CREATE TABLE IF NOT EXISTS pdf_artifacts(
 copy_id TEXT PRIMARY KEY REFERENCES document_copies(id) ON DELETE CASCADE,
 pdf_bytes BLOB NOT NULL, pdf_sha256 TEXT NOT NULL,
 signing_mode TEXT NOT NULL, certificate_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
'''
NAVY=colors.HexColor('#092653');TEAL=colors.HexColor('#0b827b');CYAN=colors.HexColor('#38c9f4')
pdfmetrics.registerFont(TTFont('VICAM',str(ROOT/'app/fonts/DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('VICAMBold',str(ROOT/'app/fonts/DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('VICAM',normal='VICAM',bold='VICAMBold')

class QR(Flowable):
    def __init__(self,url):
        super().__init__();self.width=self.height=29*mm
        q=QRCode(error_correction=ERROR_CORRECT_M,border=4);q.add_data(url);q.make(fit=True);self.matrix=q.get_matrix()
    def draw(self):
        unit=self.width/len(self.matrix);self.canv.setFillColor(colors.white);self.canv.rect(0,0,self.width,self.height,fill=1,stroke=0);self.canv.setFillColor(colors.black)
        for y,row in enumerate(self.matrix):
            for x,black in enumerate(row):
                if black:self.canv.rect(x*unit,self.height-(y+1)*unit,unit,unit,fill=1,stroke=0)

class Logo(Flowable):
    def __init__(self):super().__init__();self.width=150;self.height=40
    def draw(self):
        c=self.canv;c.setStrokeColor(NAVY);c.setLineWidth(2.7)
        c.arc(0,6,29,35,20,140);c.arc(0,6,29,35,200,140)
        p=c.beginPath();p.moveTo(8,27);p.lineTo(15,14);p.lineTo(22,27);c.drawPath(p)
        c.setFillColor(NAVY);c.setFont('VICAMBold',22);c.drawString(39,12,'VICAM')

def payment_label(original):
    if original['kind']!='invoices' or original['status']=='void' or original.get('paid_minor',0)<=0:
        return None
    return 'PAID' if original['balance_minor']==0 else 'PARTIALLY PAID'

class PaymentBadge(Flowable):
    def __init__(self,label):
        super().__init__();self.label=label;self.width=132 if label=='PARTIALLY PAID' else 79;self.height=24
    def draw(self):
        c=self.canv;green=colors.HexColor('#15803d')
        c.setFillColor(colors.HexColor('#eaf8ef'));c.setStrokeColor(colors.HexColor('#b7e4c8'));c.setLineWidth(.7)
        c.roundRect(0,0,self.width,self.height,12,stroke=1,fill=1)
        c.setFillColor(green);c.circle(13,12,6,stroke=0,fill=1)
        c.setStrokeColor(colors.white);c.setLineWidth(1.25)
        p=c.beginPath();p.moveTo(10,12);p.lineTo(12,10);p.lineTo(16,14);c.drawPath(p)
        c.setFillColor(green);c.setFont('VICAMBold',8);c.drawString(25,9,self.label)


def render_pdf(original,copy_id,stamp,url,mode):
    # Reject unsupported glyphs instead of silently replacing client information.
    chars=''.join(str(v) for v in original.values() if v is not None)
    if any(ord(c)>31 and ord(c) not in pdfmetrics.getFont('VICAM').face.charToGlyph for c in chars):raise ValueError('The document contains characters not supported by the PDF font')
    buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=18*mm,bottomMargin=26*mm,title=original['reference'],author=original.get('issuer',{}).get('name','VICAM'))
    styles={key:ParagraphStyle(key,fontName='VICAMBold' if key in {'heading','project','label','total'} else 'VICAM',fontSize=size,leading=size*1.5,textColor=color,spaceAfter=gap) for key,size,color,gap in [('heading',17,NAVY,4),('project',13,NAVY,10),('body',9,NAVY,9),('label',8,TEAL,5),('fine',7,colors.HexColor('#5b7288'),6),('total',20,colors.white,0)]}
    def para(value,key='body'):return Paragraph(escape(str(value)).replace('\n','<br/>'),styles[key])
    money=lambda n:original['currency']+' '+f'{n/100:,.2f}'
    story=[]
    label=payment_label(original)
    heading=[para('Quotation' if original['kind']=='quotes' else 'Invoice','heading')]
    if label:heading.extend([Spacer(1,3),PaymentBadge(label)])
    issuer=original.get('issuer',{'name':'VICAM'})
    identity=[para(issuer['name'],'project')]
    if issuer.get('registration'):identity.append(para('Registration: '+issuer['registration'],'fine'))
    if issuer.get('email'):identity.append(para(issuer['email'],'fine'))
    h=Table([[identity,heading]],colWidths=[105*mm,69*mm]);h.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),.5,colors.HexColor('#ccdeea')),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story+=[h,Spacer(1,14),para(original['title'],'project'),para(original['reference'],'label')]
    rows=[]
    for label,value in [('Client',original['client_name']),('Organization',original['organization']),('Status',original['status']),('Issued copy',stamp),('Due / valid until',original['due_date'])]:
        if value:rows.append([para(label,'label'),para(value)])
    details=Table(rows,colWidths=[35*mm,139*mm],hAlign='LEFT');details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),5)]));story+=[details,Spacer(1,8),para('SERVICE SCOPE','label'),para(original['description'] or 'See agreed service scope.'),Spacer(1,7)]
    pricing=original.get('pricing')
    if pricing:
        rows=[[para('Item','label'),para('Qty','label'),para('Unit','label'),para('Amount','label')]]
        for item in pricing['line_items']:rows.append([para(item['description']),para(item['quantity']),para(money(item['unit_amount_minor'])),para(money(item['line_total_minor']))])
        table=Table(rows,colWidths=[77*mm,17*mm,40*mm,40*mm],repeatRows=1)
        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.5,CYAN),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story += [table,Spacer(1,10),para('Subtotal: '+money(pricing['subtotal_minor'])+' | Discount ('+pricing['discount_percent']+'%): '+money(pricing['discount_minor'])),para('After discount: '+money(pricing['net_minor'])+' | VAT ('+pricing['vat_percent']+'%): '+money(pricing['vat_minor']))]
    styles['total_label']=ParagraphStyle('total_label',fontName='VICAM',fontSize=7,leading=11,textColor=colors.HexColor('#cce8f4'))
    total=Table([[para('QUOTATION TOTAL' if original['kind']=='quotes' else 'INVOICE TOTAL','total_label')],[para(money(original['amount_minor']),'total')]],colWidths=[174*mm]);total.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),NAVY),('LINEABOVE',(0,0),(-1,0),2,CYAN),('LEFTPADDING',(0,0),(-1,-1),14),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story+=[total,Spacer(1,14)]
    if original['kind']=='invoices':story.append(para('Recorded payments: '+money(original['paid_minor'])+' · Balance: '+money(original['balance_minor'])))
    signing='Certificate-signed PDF. Validate the signature in a compatible PDF reader.' if mode=='certificate' else 'LOCAL TEST SIGNATURE - not a trusted VICAM company identity.' if mode=='test' else 'UNSIGNED DRAFT - this file has no certificate-based signature.'
    info=[para('VERIFY THIS COPY','label'),para('Scan the QR on the issuer’s confirmed domain to compare the saved details.','fine'),para('Copy ID: '+copy_id[:8],'fine'),para(url,'fine')]
    qr=Table([[QR(url),info]],colWidths=[34*mm,140*mm]);qr.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0)]));story.append(KeepTogether([qr,Spacer(1,10),para(signing,'fine'),para('Totals calculated from entered line items; confirm tax treatment before customer use.' if pricing else 'Legacy manual total. Company particulars and tax treatment must be reviewed before customer use.','fine')]))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('VICAM',7);canvas.setFillColor(colors.HexColor('#60788c'));canvas.drawString(18*mm,13*mm,issuer['name']+' · '+original['reference']);canvas.drawRightString(192*mm,13*mm,'Page '+str(doc.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

def generate_pdf(original,copy_id,stamp,url,settings,signed):
    mode=settings.pdf_signing_mode if signed else 'disabled'
    pdf=render_pdf(original,copy_id,stamp,url,mode)
    fingerprint=''
    if signed:pdf,fingerprint=sign_pdf(pdf,settings)
    if len(pdf)>5*1024*1024:raise ValueError('Generated PDF is too large')
    return pdf,hashlib.sha256(pdf).hexdigest(),mode,fingerprint
