"""Yerel kayıt alanı: sürüm kontrollü düzenleme ve eklemeli işlem geçmişi."""
import sqlite3,json,hashlib
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone

class ConflictError(ValueError):pass

class Workspace:
    def __init__(self,path):
        self.path=str(path);Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY, dataset TEXT, actor TEXT, at TEXT, kind TEXT, before TEXT, after TEXT);
            CREATE TABLE IF NOT EXISTS snapshots(dataset TEXT, url TEXT, payload TEXT, PRIMARY KEY(dataset,url));''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def init(self,raw,ops,sources,reviews):
        key=hashlib.sha256(raw).hexdigest()
        payload=dict(opportunities=ops,sources=sources,reviews=reviews,approvals={})
        with self.connect() as c:c.execute('INSERT OR IGNORE INTO datasets VALUES(?,?,0)',(key,json.dumps(payload,ensure_ascii=False)))
        return key
    def read(self,key):
        with self.connect() as c:r=c.execute('SELECT * FROM datasets WHERE id=?',(key,)).fetchone()
        if not r:raise ValueError('Çalışma bulunamadı')
        return json.loads(r['payload']),r['revision']
    def save(self,key,revision,actor,kind,mutate,snapshot=None):
        if not actor.strip():raise ValueError('Kaydeden kişinin adını yazın.')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM datasets WHERE id=?',(key,)).fetchone()
            if not r or r['revision']!=revision:raise ConflictError('Başka bir değişiklik kaydedildi. Sayfayı yenileyip yeniden deneyin.')
            old=r['payload'];payload=json.loads(old);mutate(payload)
            new=json.dumps(payload,ensure_ascii=False)
            c.execute('UPDATE datasets SET payload=?,revision=revision+1 WHERE id=?',(new,key))
            c.execute('INSERT INTO history(dataset,actor,at,kind,before,after) VALUES(?,?,?,?,?,?)',(key,actor,datetime.now(timezone.utc).isoformat(),kind,old,new))
            if snapshot is not None:c.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)',(key,snapshot['url'],json.dumps(snapshot,ensure_ascii=False)))
        return revision+1
    def edit_review(self,key,revision,actor,op,criterion,changes):
        from validation import proposal_errors,evidence_errors
        def update(p):
            r=next(r for r in p['reviews'] if r['opportunity_id']==op and r['criterion']==criterion)
            r.update(changes)
            # UI düzenlemesi insan yayın/teknik onayı üretmez.
            r.update(assessment_status='on_inceleme',prepared_by=actor,prepared_date=datetime.now().date().isoformat(),reviewer='')
            errors=proposal_errors(r,{s['id']:s for s in p['sources']})
            if errors:raise ValueError('; '.join(errors))
            p['approvals'].pop(op,None)
        return self.save(key,revision,actor,'Ölçüt düzenlendi',update)
    def edit_opportunity(self,key,revision,actor,op,changes):
        def update(p):
            if not changes.get('action','').strip():raise ValueError('Önerilen değişiklik boş olamaz.')
            o=next(o for o in p['opportunities'] if o['id']==op)
            # Yeni aksiyon eski puanları otomatik devralamaz.
            if o.get('action')!=changes['action']:
                for r in p['reviews']:
                    if r['opportunity_id']==op:r.update(level='',assessment_status='eksik',reason='Aksiyon değişti; bu ölçüt yeni aksiyona göre değerlendirilmelidir.')
            o.update(changes);p['approvals'].pop(op,None)
        return self.save(key,revision,actor,'Aksiyon/not düzenlendi',update)
    def approve(self,key,revision,actor,op,note):
        def update(p):
            from scoring import analyze
            a,_=analyze(p['opportunities'],p['sources'],p['reviews'])
            if a.set_index('id').loc[op,'Ön ölçüt sayısı']!=4:raise ValueError('Dört kaynaklı ölçüt tamamlanmadan editoryal onay verilemez.')
            if not note.strip():raise ValueError('Onay gerekçesini yazın.')
            p['approvals'][op]=dict(actor=actor,note=note,revision=revision+1,at=datetime.now(timezone.utc).isoformat(),scope='Site iyileştirme önerisi ve puan gerekçesi; teknik iddiaların doğrulaması değildir')
        return self.save(key,revision,actor,'Editoryal değerlendirme onaylandı',update)
    def revoke_approval(self,key,revision,actor,op):
        def update(p):
            if op not in p['approvals']:raise ValueError('Bu öneride geri alınacak onay yok.')
            p['approvals'].pop(op)
        return self.save(key,revision,actor,'Editoryal onay geri alındı: '+op,update)
    def history(self,key,details=False):
        fields='*' if details else 'seq,actor,at,kind'
        with self.connect() as c:return [dict(r) for r in c.execute(f'SELECT {fields} FROM history WHERE dataset=? ORDER BY seq DESC',(key,))]
    def snapshot(self,key,url):
        with self.connect() as c:r=c.execute('SELECT payload FROM snapshots WHERE dataset=? AND url=?',(key,url)).fetchone()
        return json.loads(r[0]) if r else None
    def save_snapshot(self,key,revision,actor,op,snapshot):
        old=self.snapshot(key,snapshot['url'])
        changed=bool(old and old.get('hash') and snapshot.get('hash') and old['hash']!=snapshot['hash'])
        def update(p):
            if changed or snapshot.get('error'):
                source_ids={s['id'] for s in p['sources'] if s.get('url')==snapshot['url']}
                affected={o['id'] for o in p['opportunities'] if o.get('target_url')==snapshot['url']}
                affected.add(op)
                affected.update(r['opportunity_id'] for r in p['reviews'] if source_ids.intersection(x.strip() for x in r.get('source_ids','').split(';')))
                for oid in affected:p['approvals'].pop(oid,None)
                for r in p['reviews']:
                    if r['opportunity_id'] in affected:r.update(freshness_warning='Kaynak değişti veya erişilemedi; mevcut puan eski kaynaklara dayanıyor.')
        revision=self.save(key,revision,actor,'Web kaynağı yeniden alındı',update,snapshot=snapshot)
        return revision,changed
