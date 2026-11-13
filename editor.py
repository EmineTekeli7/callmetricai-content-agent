import json
from datetime import datetime,timezone
import pandas as pd
import streamlit as st
from validation import CRITERIA
from research import fetch

def render_editor(db,key,revision,payload):
    with st.expander('Önerileri düzenle, kaynakları incele ve kaydet'):
        st.caption('Kayıtlar bu bilgisayarda saklanır. Girilen ad kullanıcı beyanıdır; oturum açma/kimlik doğrulama değildir.')
        actor=st.text_input('Kaydeden kişi',key='editor_actor')
        opid=st.selectbox('Düzenlenecek öneri',[o['id'] for o in payload['opportunities']],key='editor_op')
        op=next(o for o in payload['opportunities'] if o['id']==opid)
        approval=payload['approvals'].get(opid)
        if approval:st.success(f"{opid} editoryal onayı kayıtlı. Onaylayan: {approval['actor']}. Gerekçe: {approval['note']}")
        else:st.info(f'{opid} için henüz editoryal onay kaydı yok.')
        tab1,tab2,tab3,tab4=st.tabs(['Öneri ve not','Puan ve gerekçe','Web kaynaklarını yenile','Onay ve geçmiş'])
        with tab1:
            with st.form(f'op_{opid}_{revision}'):
                action=st.text_area('Önerilen değişiklik',op.get('action',''))
                note=st.text_area('Bilgi ihtiyacı / not',op.get('uncertainty',''))
                st.caption('Önerinin kendisini değiştirmek eski puanları ve editoryal onayı geçersiz kılar. Sadece not değiştirmek puanları silmez.')
                if st.form_submit_button('Öneriyi kaydet'):
                    try:db.edit_opportunity(key,revision,actor,opid,dict(action=action,uncertainty=note));st.rerun()
                    except ValueError as exc:st.error(str(exc))
        with tab2:
            criterion=st.selectbox('Ölçüt',list(CRITERIA),format_func=lambda x:CRITERIA[x],key='editor_criterion')
            r=next(r for r in payload['reviews'] if r['opportunity_id']==opid and r['criterion']==criterion)
            source_map={s['id']:s for s in payload['sources']}
            ids=[s.strip() for s in r.get('source_ids','').split(';') if s.strip() in source_map]
            for sid in ids:
                s=source_map[sid]
                st.write(sid+' · '+s.get('source_file','')+' · '+s.get('cell',''))
                st.text(s['text'])
                if s.get('url'):st.write(s['url'])
            with st.form(f'review_{opid}_{criterion}_{revision}'):
                level=st.selectbox('Puan',[1,2,3,4,5],index=int(r.get('level') or 1)-1)
                reason=st.text_area('Gerekçe',r.get('reason',''))
                refs=st.text_input('Kaynak kimlikleri (noktalı virgülle)',r.get('source_ids',''))
                quote=st.text_area('Kaynak kaydından birebir alıntı',r.get('quote',''))
                next_step=st.text_area('Kapsam / uygulama için gerekli bilgi',r.get('next_step',''))
                inspected=st.checkbox('Gösterilen kaynakları ve puan gerekçesini inceledim')
                if st.form_submit_button('Değerlendirmeyi kaydet'):
                    try:
                        if not inspected:raise ValueError('Kaynak incelemesini işaretleyin.')
                        db.edit_review(key,revision,actor,opid,criterion,dict(level=str(level),reason=reason,source_ids=refs,quote=quote,next_step=next_step,freshness_warning=''))
                        st.rerun()
                    except ValueError as exc:st.error(str(exc))
        with tab3:
            related=[r for r in payload['reviews'] if r['opportunity_id']==opid]
            ids={x.strip() for r in related for x in r.get('source_ids','').split(';')}
            urls=list(dict.fromkeys([op.get('target_url','')]+[s.get('url','') for s in payload['sources'] if s['id'] in ids]))
            urls=[u for u in urls if u.startswith(('https://','http://'))]
            chosen=st.multiselect('Yeniden alınacak açık web sayfaları',urls,default=urls[:2],key=f'urls_{opid}')
            st.caption('Sayfa metni ve değişim kontrolü yapılır. Bu işlem iddiaların anlamını doğrulamaz, yeni puan üretmez. En fazla 6 sayfa; erişim başarısızlıkları ayrı kaydedilir.')
            if st.button('Seçili kaynakları yeniden kontrol et'):
                try:
                    if not actor.strip():raise ValueError('Kaydeden kişinin adını yazın.')
                    if not 1<=len(chosen)<=6:raise ValueError('1–6 sayfa seçin.')
                    rev=revision
                    progress=st.progress(0)
                    for index,url in enumerate(chosen):
                        snapshot=fetch(url)
                        rev,changed=db.save_snapshot(key,rev,actor,opid,snapshot)
                        progress.progress((index+1)/len(chosen))
                    st.rerun()
                except ValueError as exc:st.error(str(exc))
            for url in urls:
                snapshot=db.snapshot(key,url)
                if snapshot:
                    st.write(url)
                    if snapshot.get('error'):st.warning('Erişim sonucu: '+snapshot['error'])
                    else:
                        st.caption('Son alınma: '+snapshot['at'])
                        st.text_area('Alınan sayfa metni',snapshot['text'],height=150,key='snapshot_'+url,disabled=True)
        with tab4:
            if approval:
                st.caption('Onayı geri almak öneriyi veya puanları silmez. İşlem geçmişte saklanır.')
                if st.button('Onayı geri al',key='revoke_'+opid):
                    try:
                        db.revoke_approval(key,revision,actor,opid)
                        st.session_state['save_notice']=f'{opid} editoryal onayı geri alındı. Puanlar korundu.'
                        st.session_state['refresh_analysis']=True
                        st.rerun()
                    except ValueError as exc:st.error(str(exc))
            with st.form(f'approve_{opid}_{revision}'):
                approval_note=st.text_area('Editoryal onay gerekçesi')
                agreed=st.checkbox('Öneriyi ve dört puanın gerekçesini inceledim; teknik bilgi ihtiyaçlarının ayrı kaldığını biliyorum')
                if st.form_submit_button('Editoryal değerlendirmeyi onayla'):
                    try:
                        if not agreed:raise ValueError('İnceleme beyanını işaretleyin.')
                        db.approve(key,revision,actor,opid,approval_note)
                        st.session_state['save_notice']=f'{opid} editoryal onayı başarıyla kaydedildi. Onaylayan: {actor}.'
                        st.session_state['refresh_analysis']=True
                        st.rerun()
                    except ValueError as exc:st.error(str(exc))
            if payload['approvals']:st.dataframe(pd.DataFrame([dict(id=k,**v) for k,v in payload['approvals'].items()]),hide_index=True)
            st.dataframe(pd.DataFrame(db.history(key)),hide_index=True)
            st.download_button('Çalışma ve geçmiş yedeğini indir',json.dumps(dict(data=payload,revision=revision,history=db.history(key,details=True)),ensure_ascii=False,indent=2),file_name='CallMetric_Calisma_Yedegi.json',mime='application/json')
