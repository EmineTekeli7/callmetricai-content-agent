from pathlib import Path
from io import BytesIO
import logging
import hashlib
import streamlit as st
import pandas as pd
from validation import load_excel, CRITERIA
from scoring import analyze, export_excel, RULES, WEIGHTS
from workspace import Workspace
from editor import render_editor

BASE = Path(__file__).resolve().parent
(BASE/'logs').mkdir(exist_ok=True)
logger = logging.getLogger('callmetric')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(BASE/'logs'/'uygulama.log', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
st.set_page_config(page_title='CallMetric AI | İçerik fırsatları', layout='wide')
st.title('CallMetric AI · Site İçeriği Fırsatları')
st.caption('CONTENT-02 · Yalnızca 4. görev · Kurallara dayalı prototip')
st.info('Kaynaklı ön puanlar ile nihai insan puanları ayrı gösterilir. Eksik ölçüt varsa toplam hesaplanmaz. İlk 10 seçimi bu uygulamanın kapsamında değildir.')
with st.expander('Puanlar nasıl hesaplanır?'):
    st.write('Dört ölçüt eşit %25 ağırlıklıdır. Toplam: 4–20; gösterim: ağırlıklı ortalama ×20 = 20–100. Eksik ölçüt sıfır değildir; toplam ve sıra boş kalır. Eşit puan aynı sırayı alır.')
    st.table(pd.DataFrame({CRITERIA[k]: v for k,v in RULES.items()}, index=[1,2,3,4,5]))
    st.write('Puanlar gerekçe ve kaynakla kaydedilir. Web yenileme sayfa metnini ve değişimi alır; iddiaların doğruluğunu otomatik onaylamaz veya yeni puan üretmez. Editoryal onay teknik ürün doğrulamasından ayrıdır. 365 gün eşiği bir prototip varsayımıdır.')
    st.write('Kaynak dosyası/sayfa/hücre ve alıntı korunur. Kullanıcının teyit ettiği kaynaklar ayrıca kayıtlıdır. Ön toplam dört ölçütle hesaplanır; insan puanı ayrı kalır. Sayfanın bugün alınması eski yorumun veya GEO gözleminin tarihini yenilemez.')
reviewed_example=BASE/'kaynakli_degerlendirme.xlsx'
example = reviewed_example if reviewed_example.exists() else BASE/'ornek_giris.xlsx'
if example.exists():
    st.download_button('Kaynaklı giriş Excel’ini indir' if reviewed_example.exists() else 'Örnek giriş Excel’ini indir', example.read_bytes(), file_name=example.name)
upload = st.file_uploader('Excel yükleyin (.xlsx, en fazla 10 MB)', type=['xlsx'])
use_example = st.checkbox('Yüklenen dosyalardan hazırlanan 15 fırsatı kullan' if reviewed_example.exists() else 'Kaynaklı 15 fırsat örneğini kullan', value=True)

def display_table(frame):
    """Eksik sayıları kullanıcıya Python None ifadesiyle göstermeyin."""
    # Yalnız görünüm metne çevrilir; hesaplama ve Excel sayıları sayısal kalır.
    shown=frame.copy()
    for col in frame.columns:
        if not pd.api.types.is_numeric_dtype(frame[col]):
            shown[col]=frame[col].map(lambda value: 'Onay kaydı yok' if pd.isna(value) else str(value))
    return shown
data = upload.getvalue() if upload else (example.read_bytes() if use_example and example.exists() else None)
if data:
    try:
        ops, sources, reviews = load_excel(data)
        db=Workspace(BASE/'runtime'/'workspace.sqlite3')
        dataset_key=db.init(data,ops,sources,reviews)
        payload,revision=db.read(dataset_key)
        ops,sources,reviews=payload['opportunities'],payload['sources'],payload['reviews']
        if st.session_state.get('save_notice'):st.success(st.session_state.pop('save_notice'))
        st.write(f'{len(ops)} fırsat · {len(sources)} kaynak kaydı')
        if all(op.get('target_url') and op.get('opportunity_type') for op in ops):
            st.subheader('Hangi sayfada ne değişmeli?')
            st.caption('Öneriler mevcut ürün, çözüm, sektör ve entegrasyon sayfalarının geliştirilmesine yöneliktir. Teknik kapsam ve kaynak sınırları her adayda korunur.')
            action_view=pd.DataFrame([{'id':o['id'],'Fırsat türü':o['opportunity_type'],'Hedef sayfa':o['target_page'],'Sayfa bölümü':o['page_section'],'Önerilen değişiklik':o['action'],'Sayfayı aç':o['target_url']} for o in ops])
            st.dataframe(action_view,hide_index=True,column_config={'Sayfayı aç':st.column_config.LinkColumn('Sayfayı aç',display_text='Sayfaya git')})
            st.caption('Site geneli kontrolü: Envanterin TR/EN A20 notunda ana sayfanın ürün sayfalarından daha ayrıntılı olduğu ve bilgi dağılımının tutarsızlığı kaydedilmiş. İlgili sayfalarda açıklama kapsamını ve karşılıklı bağlantıları kontrol edin.')
        with st.expander('Girişteki 15 konu ve kaynak eşleştirmeleri'):
            st.dataframe(pd.DataFrame(ops), hide_index=True)
        digest = hashlib.sha256(data).hexdigest()+':'+str(revision)
        if st.session_state.get('input_hash') != digest:
            if 'analysis' in st.session_state:st.session_state['refresh_analysis']=True
            st.session_state.pop('analysis', None)
            st.session_state['input_hash'] = digest
        render_editor(db,dataset_key,revision,payload)
        run_analysis=st.button('Analizi Başlat', type='primary')
        if run_analysis or st.session_state.pop('refresh_analysis',False):
            results, details = analyze(ops, sources, reviews)
            results['Editoryal onay']=results['id'].map(lambda x:payload['approvals'].get(x,{}).get('actor','Onay kaydı yok'))
            st.session_state['analysis'] = (results, details)
            logger.info('Analiz tamamlandı: fırsat=%d tam=%d', len(ops), results['Puan /100'].notna().sum())
        if 'analysis' in st.session_state:
            results, details = st.session_state['analysis']
            if results['Ön puan /100'].notna().all():
                st.success(f'{len(results)} önerinin kaynaklı analizi tamamlandı. Puanlar analist önerisidir; yayın öncesi ürün bilgisi ihtiyaçları ayrıca belirtilir.')
            else:
                st.warning('Bazı önerilerde puanlamaya dayanak eksik. Eksik ölçütler aşağıda gösterilir.')
            if any(r.get('assessment_status')=='on_inceleme' for r in reviews):
                st.subheader('Dosyalara dayalı ön değerlendirme')
                st.caption('Kaynaklı analist değerlendirmesi · Öneri puanları · İnsan yayın onayı değildir.')
                st.caption('Başlıklara tıklamak yalnız tablo görünümünü sıralar. “İçerik” alfabetik, “Ön puan /100” puana göre sıralar. “Ön sıra” hesaplanan puan sırasıdır; eşit puanlar aynı sırayı alır.')
                count=results['Ön puan /100'].notna().sum()
                st.write(f"{int(results['Ön ölçüt sayısı'].sum())}/{len(ops)*4} ölçütte kaynaklı ön puan var. {count} adayda dört ölçüt tamam; diğerlerinde ön toplam boş.")
                columns=['Ön sıra','id','İçerik','Editoryal onay','Fırsat türü','Hedef sayfa',*['Ön '+label for label in CRITERIA.values()],'Ön puan /100','Ön ölçüt sayısı','Ön değerlendirme eksikleri','Belirsizlik']
                view=results.sort_values(['Ön puan /100','id'],ascending=[False,True],na_position='last')[columns]
                st.dataframe(display_table(view),hide_index=True)
            with st.expander('Kaydedilen editoryal onaylar'):
                if payload['approvals']:
                    st.dataframe(pd.DataFrame([dict(id=k,**v) for k,v in payload['approvals'].items()]),hide_index=True)
                else:st.write('Henüz kaydedilmiş editoryal onay yok. Yukarıdaki düzenleme bölümünde kişi adı, gerekçe ve inceleme kutusu doldurularak kaydedilir.')
            st.subheader('Her puanın gerekçesi ve kaynağı')
            selected=st.selectbox('Gerekçesini inceleyeceğiniz konu',['Tüm konular',*results['id'].tolist()])
            visible=details if selected=='Tüm konular' else details[details['id']==selected]
            st.dataframe(display_table(visible), hide_index=True)
            with st.expander('Kaynak dosyaları, hücreleri ve kontrol sınırları'):
                st.dataframe(pd.DataFrame(sources),hide_index=True)
            st.download_button('Sonuçları Excel olarak indir', export_excel(results, details, sources), file_name='CallMetricAI_Gorev4_Sonuclar.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except ValueError as exc:
        logger.warning('Girdi reddedildi: %s', exc)
        st.error(str(exc))
    except Exception:
        logger.exception('Beklenmeyen analiz hatası')
        st.error('Analiz tamamlanamadı. logs/uygulama.log kaydını inceleyin.')
else:
    st.write('Başlamak için Excel yükleyin veya örnek veriyi seçin.')
