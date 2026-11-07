import pandas as pd,numpy as np,unicodedata as U
T=pd.read_pickle('/tmp/T2.pkl'); m=pd.read_csv('crate_membership.csv')
m['key']=m.serato_path.map(lambda s:U.normalize('NFC',s)).str.replace('^DJ Music/','',regex=True)
def style(cr):
    c=cr.lower()
    for k,v in [('dubstep','Dubstep'),('dnb','DnB'),("drum'n'bass",'DnB'),('trap','Trap'),('house','House'),('big room','House'),('future bass','Future Bass'),('mashup','Mashups'),('pop','Pop'),('rap','Rap')]:
        if k in c: return v
first={}
for k,cr in zip(m.key,m.crate):
    s=style(cr)
    if s and k not in first: first[k]=s
T['style']=pd.Series(T.index.map(first),index=T.index); T.loc[T['style'].isna()&(T.folder=='Crunkz Mashups'),'style']='Mashups'; T['style']=T['style'].fillna('?')
T['bpmband']=pd.cut(T.serato_bpm,[0,100,118,135,145,160,200],labels=['<100','100-118','118-135','135-145','145-160','160+'])
C=T[(T.mikcls=='no Energy names')&(T.n_slots>0)].copy()
C['d76']=C[7]-C[6]; C['d87']=C[8]-C[7]; C['d46']=C[6]-C[4]
okc=['ok_R1','ok_R2','ok_R3','ok_R4','ok_R5','ok_R6','ok_R8']
agg=C.groupby('style').agg(n=('n_slots','size'),bpm_med=('serato_bpm','median'),slots_med=('n_slots','median'),
    cue1_at_start=(1,lambda s:(s.abs()<1).mean()),d46_med=('d46','median'),c8_end_med=('c8_from_end','median'),
    c8_eq_c7p32=('d87',lambda s:((s-32).abs()<=1).mean()),c7_before_c6=('d76',lambda s:(s<0).mean()),
    **{r:(r,'mean') for r in okc})
print(agg.round(2).to_string())
print(C.groupby('bpmband',observed=True)[okc+['n_slots']].mean().round(2).assign(n=C.groupby('bpmband',observed=True).size()).to_string())
print('dubstep bpm values:',C[C['style']=='Dubstep'].serato_bpm.round().value_counts().head(6).to_dict())
T.to_pickle('/tmp/T3.pkl'); agg.round(3).to_csv('by_style.csv')
