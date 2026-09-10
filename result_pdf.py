"""Paginated individual result summaries; never embed questions or answer keys."""
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


def render_report(data):
    s=data['session'];output=BytesIO();styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReportTitle',fontName='Helvetica-Bold',fontSize=22,leading=27,textColor=colors.HexColor('#173553'),spaceAfter=12))
    styles.add(ParagraphStyle(name='Muted',fontSize=9,leading=13,textColor=colors.HexColor('#536477'),spaceAfter=9))
    styles.add(ParagraphStyle(name='Cell',fontSize=9,leading=13))
    def text(value,style='BodyText'):return Paragraph(escape(str('' if value is None else value)).replace('\n','<br/>'),styles[style])
    def number(value):return f'{float(value or 0):g}'
    def date(value):return datetime.fromtimestamp(value,timezone.utc).strftime('%d %b %Y, %H:%M UTC') if value else '-'
    def table(rows,widths,header=False):
        value=Table([[text(x,'Cell') for x in row] for row in rows],colWidths=widths,repeatRows=1 if header else 0,hAlign='LEFT')
        commands=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),.5,colors.HexColor('#d9e2ec'))]
        if header:commands+=[('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f7'))]
        value.setStyle(TableStyle(commands));return value
    story=[text('MERITIQRA','Muted'),text('Individual exam report','ReportTitle'),text(s['exam_name'],'Heading2'),text(s['student_name'] or 'Student','Heading3'),text(f"{s['subject'] or 'General'} | {s['level'] or 'All levels'} | Attempt {s['attempt_number']}",'Muted')]
    if not data['released']:story.append(text('ADMIN PREVIEW - results have not been released.','Heading3'))
    story += [table([['Score','Percentage','Best-attempt rank'],[f"{number(s['score'])} / {number(s['max_score'])}",f"{float(s['percentage'] or 0):.1f}%",f"{data['rank'] or '-'} / {data['participants']}"]],[175,150,174],True),Spacer(1,14),table([['Correct','Incorrect','Unanswered'],[s['correct_count'],s['incorrect_count'],s['unanswered_count']]],[166,166,167],True),Spacer(1,14),text(f"Submitted: {date(s['submitted_at'])} | Allowed duration: {s['duration_minutes']} minutes",'Muted'),text(f"Rank uses each student's best completed attempt; this student's ranking attempt is #{data['rank_attempt_number'] or '-'}. Equal percentage and marks share a rank. Rankings can change as more results are submitted.",'Muted')]
    if data['subjects']:
        story += [text('Subject performance','Heading2'),table([['Subject','Questions','Correct','Score / max']]+[[r['subject'],r['questions'],r['correct'],f"{number(r['score'])} / {number(r['max_score'])}"] for r in data['subjects']],[229,80,70,120],True)]
    story += [Spacer(1,18),text('This report reflects the saved examination attempt. Question text, answer keys and contact details are excluded.','Muted')]
    def footer(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(colors.HexColor('#d9e2ec'));canvas.line(48,43,A4[0]-48,43);canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#536477'));canvas.drawString(48,29,f"MeritIQra | Result #{s['id']}");canvas.drawRightString(A4[0]-48,29,f'Page {doc.page}');canvas.restoreState()
    SimpleDocTemplate(output,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=42,bottomMargin=58,title='Individual exam report',author='MeritIQra').build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
