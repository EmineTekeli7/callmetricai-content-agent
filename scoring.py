"""İnsan tarafından kaynakla kodlanan düzeyleri deterministik hesaplar."""
from io import BytesIO
import math
import pandas as pd
from validation import CRITERIA, evidence_errors, proposal_errors

WEIGHTS = dict.fromkeys(CRITERIA, 0.25)
RULES = {
 'gap': ['İhtiyaç mevcut içeriklerde karşılanıyor', 'Küçük bir açıklama eksik', 'Bazı alt konular eksik', 'Önemli bir alt ihtiyaç karşılanmıyor', 'Belgeli karşılaştırmada belirgin boşluk var'],
 'intent': ['Sorgu ihtiyacıyla zayıf eşleşme', 'Sorgunun sınırlı bölümünü yanıtlıyor', 'İlgili fakat geniş ihtiyaç', 'Belirli ihtiyacı büyük ölçüde yanıtlıyor', 'Belirli soruyu ve SERP niyetini doğrudan yanıtlıyor'],
 'product': ['Doğrulanmış ürün kapsamıyla zayıf ilişki', 'Dolaylı ilişki', 'Kısmen doğrulanmış kapsamla ilgili', 'Doğrulanmış yetenekle güçlü ilişki', 'Doğrulanmış temel yetenekle doğrudan ilişki'],
 'evidence': ['Teyitli fakat tekil/dolaylı dayanak', 'Birden fazla fakat aynı kökten dayanak', 'Birbirini destekleyen ekip kayıtları', 'Doğrudan birincil ve destekleyici kayıtlar', 'Birden fazla bağımsız, güncel, doğrudan ve teyitli dayanak']}

def analyze(ops, sources, reviews):
    source_map = {s['id']: s for s in sources}
    review_map = {(r['opportunity_id'], r['criterion']): r for r in reviews}
    rows, details = [], []
    for op in ops:
        row = {'id': op['id'], 'İçerik': op['title'], 'Belirsizlik': op.get('uncertainty','')}
        row.update({'Fırsat türü':op.get('opportunity_type','İçerik adayı'),
                    'Hedef sayfa':op.get('target_page',''), 'Hedef URL':op.get('target_url',''),
                    'Sayfa bölümü':op.get('page_section',''), 'Önerilen değişiklik':op.get('action',''),
                    'Özgün araştırma konusu':op.get('original_title',op['title'])})
        warnings = []
        proposal_warnings=[]
        for key, label in CRITERIA.items():
            review = review_map.get((op['id'], key))
            errors = evidence_errors(review, source_map) if review else ['Kaynaklı insan değerlendirmesi eksik']
            proposed = bool(review and review.get('assessment_status')=='on_inceleme')
            missing = bool(review and review.get('assessment_status')=='eksik')
            if proposed or missing:
                errors = ['Nihai insan değerlendirmesi/onayı bekliyor']
            score = None if errors else int(review['level'])
            proposal_checks=proposal_errors(review,source_map) if proposed else ['Kaynaklı ön inceleme yok']
            preliminary = int(review['level']) if proposed and not proposal_checks else score
            row['Ön '+label]=preliminary
            row[label] = score
            warnings.extend(label + ': ' + e for e in errors)
            if preliminary is None:proposal_warnings.append(label+': '+(review.get('reason','') if missing else '; '.join(proposal_checks)))
            details.append({'id': op['id'], 'Ölçüt': label, 'Puan': score, 'Ön puan': preliminary, 'Değerlendirme türü': 'Kaynaklı AI ön incelemesi' if proposed else ('Eksik kanıt' if missing else 'İnsan değerlendirmesi'), 'Değerlendirme kapsamı':review.get('assessment_scope','') if review else '', 'Gerekçe': review['reason'] if review else '', 'Kural': RULES[key][preliminary-1] if preliminary else '', 'Kaynak': review['source_ids'] if review else '', 'Alıntı': review['quote'] if review else '', 'Kontrol eden': review['reviewer'] if review else '', 'Hazırlayan': review.get('prepared_by','') if review else '', 'Tamamlama adımı': review.get('next_step','') if review else '', 'Uyarı': '; '.join(errors+([] if preliminary is not None else proposal_checks))})
        complete = all(row[label] is not None for label in CRITERIA.values())
        row['Toplam /20'] = sum(row[l] for l in CRITERIA.values()) if complete else None
        row['Puan /100'] = round(sum(row[l]*WEIGHTS[k] for k,l in CRITERIA.items())*20, 2) if complete else None
        row['Durum'] = 'Değerlendirildi — yayın onayı değildir' if complete else 'Kontrol bekliyor'
        row['Uyarılar'] = '; '.join(warnings)
        preliminary_complete=all(row['Ön '+label] is not None for label in CRITERIA.values())
        row['Ön ölçüt sayısı']=sum(row['Ön '+label] is not None for label in CRITERIA.values())
        row['Ön toplam /20']=sum(row['Ön '+label] for label in CRITERIA.values()) if preliminary_complete else None
        row['Ön puan /100']=row['Ön toplam /20']*5 if preliminary_complete else None
        row['Ön değerlendirme durumu']='Kaynaklı analiz tamamlandı — öneri puanı' if preliminary_complete else 'Eksik ölçüt var — ön toplam hesaplanmadı'
        if preliminary_complete and not complete:
            row['Durum']='Kaynaklı analiz tamamlandı; insan puanı ayrı'
        row['Ön değerlendirme eksikleri']='; '.join(proposal_warnings)
        rows.append(row)
    df = pd.DataFrame(rows).sort_values(['Puan /100','id'], ascending=[False,True], na_position='last')
    df.insert(0, 'Sıra', df['Puan /100'].rank(method='min', ascending=False).astype('Int64'))
    df['Ön sıra']=df['Ön puan /100'].rank(method='min',ascending=False).astype('Int64')
    return df, pd.DataFrame(details)

def export_excel(results, details, sources):
    # Metinleri Excel formülü olarak çalıştırma.
    def safe(df):
        return df.map(lambda x: "'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for name, df in [('Sonuclar',results), ('Gerekceler',details), ('Kaynaklar',pd.DataFrame(sources))]:
            safe(df).to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = 'B2'
            ws.auto_filter.ref = ws.dimensions
            from openpyxl.styles import Alignment, Font, PatternFill
            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='183B56')
                cell.alignment = Alignment(wrap_text=True, vertical='center')
            ws.row_dimensions[1].height = 36
            for column in ws.columns:
                title=str(column[0].value)
                long_text={'Belirsizlik','Uyarılar','Ön değerlendirme eksikleri','Gerekçe','Kural','Alıntı','Tamamlama adımı','text','verification_note','Önerilen değişiklik'}
                medium_text={'İçerik','Kaynak','url','source_file','source_sha256','Hedef URL','Özgün araştırma konusu'}
                width=70 if title in long_text else 52 if title in medium_text else min(35,max(16,len(title)+3))
                ws.column_dimensions[column[0].column_letter].width = width
            for cells in ws.iter_rows(min_row=2):
                lines=1
                for cell in cells:
                    cell.alignment = Alignment(wrap_text=True, vertical='top')
                    width=ws.column_dimensions[cell.column_letter].width
                    lines=max(lines,sum(max(1,math.ceil(len(part)/max(8,int(width*0.95)))) for part in str(cell.value or '').split('\n')))
                ws.row_dimensions[cells[0].row].height = min(409.5,max(30,lines*16+12))
    return output.getvalue()
