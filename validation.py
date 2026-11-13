"""Excel sözleşmesi ve kanıt kontrolleri. Web doğrulaması yapmaz."""
from io import BytesIO
from datetime import date
from urllib.parse import urlparse
import pandas as pd
import re

CRITERIA = {'gap': 'Rakip içerik boşluğu', 'intent': 'Arama niyeti', 'product': 'Ürün uyumu', 'evidence': 'Kanıt gücü'}
OP_COLUMNS = ['id', 'title', 'keyword', 'uncertainty']
SOURCE_COLUMNS = ['id', 'type', 'text', 'url', 'date', 'verified']
REVIEW_COLUMNS = ['opportunity_id', 'criterion', 'level', 'reason', 'source_ids', 'quote', 'reviewer']

def clean(value):
    return '' if pd.isna(value) else str(value).strip()

def load_excel(data):
    try:
        raw = data if isinstance(data, bytes) else data.read()
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError('Dosya 10 MB sınırını aşıyor.')
        sheets = pd.read_excel(BytesIO(raw), sheet_name=None, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise ValueError('Excel okunamadı. Geçerli ve şifresiz .xlsx kullanın.') from exc
    required = {'Firsatlar': OP_COLUMNS, 'Kaynaklar': SOURCE_COLUMNS, 'Degerlendirmeler': REVIEW_COLUMNS}
    for sheet, columns in required.items():
        if sheet not in sheets or not set(columns).issubset(sheets[sheet].columns):
            raise ValueError(f'{sheet} sayfası veya zorunlu sütunlar eksik: {", ".join(columns)}')
    ops, sources, reviews = (sheets[s].fillna('').to_dict('records') for s in required)
    if not ops or len(ops) > 1000 or len(sources) > 10000 or len(reviews) > 4000:
        raise ValueError('Boş fırsat listesi veya satır sınırı aşımı (1000/10000/4000).')
    for rows, label in [(ops, 'Fırsat'), (sources, 'Kaynak')]:
        ids = [clean(r['id']) for r in rows]
        if any(not x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError(label + ' kimlikleri boş veya tekrarlı.')
    if any(not clean(o['title']) for o in ops):
        raise ValueError('Fırsat başlığı boş olamaz.')
    pairs = [(r['opportunity_id'], r['criterion']) for r in reviews]
    if len(pairs) != len(set(pairs)):
        raise ValueError('Aynı fırsat/ölçüt için birden fazla değerlendirme var.')
    if any(r['opportunity_id'] not in {o['id'] for o in ops} or r['criterion'] not in CRITERIA for r in reviews):
        raise ValueError('Değerlendirmede bilinmeyen fırsat veya ölçüt var.')
    if any(clean(r.get('assessment_status','')) not in {'','nihai','on_inceleme','eksik'} for r in reviews):
        raise ValueError('Bilinmeyen değerlendirme durumu.')
    return ops, sources, reviews

def evidence_errors(review, sources, today=None):
    today = today or date.today()
    errors = []
    if clean(review.get('level')) not in {'1','2','3','4','5'}:
        errors.append('1–5 tam sayı düzeyi eksik/geçersiz')
    for key in ['reason', 'reviewer', 'quote']:
        if not clean(review.get(key)):
            errors.append(key + ' eksik')
    ids = [x.strip() for x in clean(review.get('source_ids')).split(';') if x.strip()]
    if not ids:
        errors.append('Kaynak kimliği eksik')
    chosen = [sources[x] for x in ids if x in sources]
    if len(chosen) != len(ids):
        errors.append('Kaynak kimliği bulunamadı')
    for s in chosen:
        if clean(s['verified']).lower() not in {'true', 'evet', '1'}:
            errors.append(s['id'] + ': insan teyidi yok')
        url = urlparse(clean(s['url']))
        if url.scheme not in {'https','http'} or not url.netloc:
            errors.append(s['id'] + ': URL eksik/geçersiz')
        try:
            age = (today - date.fromisoformat(clean(s['date']))).days
            if age < 0 or age > 365:
                errors.append(s['id'] + ': tarih gelecek veya 365 günden eski')
        except ValueError:
            errors.append(s['id'] + ': tarih YYYY-MM-DD olmalı')
    quote = clean(review.get('quote'))
    if quote and not any(quote in clean(s['text']) for s in chosen):
        errors.append('Alıntı kaynak metninde birebir bulunamadı')
    types = {s['type'] for s in chosen}
    needed = {'gap': 'competitor_comparison', 'intent': 'serp', 'product': 'product'}
    if review['criterion'] in needed and needed[review['criterion']] not in types:
        errors.append('Ölçüte uygun kanıt türü eksik: ' + needed[review['criterion']])
    return list(dict.fromkeys(errors))

def proposal_errors(review, sources, today=None):
    """Belge incelemesi insan teyidi değildir; yalnız ayrı ön puan alanını açar."""
    today = today or date.today()
    errors=[]
    if clean(review.get('freshness_warning','')):errors.append(clean(review['freshness_warning']))
    if clean(review.get('assessment_status')) != 'on_inceleme':
        return ['Kaynaklı ön inceleme yok']
    if clean(review.get('level')) not in {'1','2','3','4','5'}:
        errors.append('1–5 düzeyi eksik/geçersiz')
    for field in ['reason','quote','prepared_by','prepared_date','next_step']:
        if not clean(review.get(field)):errors.append(field+' eksik')
    ids=[x.strip() for x in clean(review.get('source_ids')).split(';') if x.strip()]
    if not ids:errors.append('Kaynak kimliği eksik')
    if len(ids)!=len(set(ids)):errors.append('Tekrar eden kaynak kimliği')
    chosen=[sources[x] for x in ids if x in sources]
    if len(chosen)!=len(ids):errors.append('Kaynak kimliği bulunamadı')
    for s in chosen:
        for field in ['source_file','sheet','cell','text','verification_note']:
            if not clean(s.get(field)):errors.append(s['id']+': '+field+' eksik')
        if clean(s.get('document_checked')).lower() not in {'true','evet','1'}:
            errors.append(s['id']+': belge kontrolü yok')
        if not re.fullmatch('[a-f0-9]{64}',clean(s.get('source_sha256'))):
            errors.append(s['id']+': kaynak dosya özeti eksik/geçersiz')
        try:
            age=(today-date.fromisoformat(clean(s.get('checked_date')))).days
            if age<0 or age>365:errors.append(s['id']+': belge incelemesi güncel değil')
        except ValueError:errors.append(s['id']+': belge inceleme tarihi geçersiz')
    try:
        if date.fromisoformat(clean(review.get('prepared_date')))>today:errors.append('Ön inceleme tarihi gelecekte')
    except ValueError:errors.append('Ön inceleme tarihi geçersiz')
    quote=clean(review.get('quote'))
    if quote and not any(quote in clean(s.get('text')) for s in chosen):errors.append('Alıntı kaynak kaydında bulunamadı')
    required={'gap':'competitor_comparison','intent':'keyword_map','product':'product_inventory'}
    if review['criterion'] in required and required[review['criterion']] not in {s['type'] for s in chosen}:
        errors.append('Ölçüte uygun belge türü eksik: '+required[review['criterion']])
    return list(dict.fromkeys(errors))
