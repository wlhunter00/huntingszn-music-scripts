"""How far off are existing grids? (1) tag stats for gold; (2) audio onset-vs-grid offsets for tracks in /tmp/audio."""
import pandas as pd,numpy as np,hashlib,os,librosa
T=pd.read_pickle('/tmp/T3.pkl'); G=T[T.group=='gold']
b=G.serato_bpm.dropna()
print('gold with grid',len(b),'of',len(G),'| integer bpm (±0.02):',((b-b.round()).abs()<0.02).mean().round(3),'| dynamic',G.dynamic_grid.sum())
print('half-time-ish (<90) share',(b<90).mean().round(3))
fr=((G[[1,2,3,4,5,6,7,8]].stack()+.5)%1-.5).abs()
print('gold human cues |off-grid| beats: median',fr[G.loc[fr.index.get_level_values(0),'mikcls'].values=='no Energy names'].median())
C=G[G.mikcls=='no Energy names']; f=((C[[1,2,3,4,5,6,7,8]].stack()+.5)%1-.5).abs()
print('clean gold cues within .05/.1/.25 beat:',[(f<x).mean().round(3) for x in (.05,.1,.25)])
rows=[]
for k,r in T.iterrows():
    p='/tmp/audio/'+hashlib.md5(k.encode()).hexdigest()+'.mp3'
    if not os.path.exists(p) or pd.isna(r.serato_bpm): continue
    try: y,sr=librosa.load(p,sr=22050,mono=True)
    except Exception: continue
    hop=128; env=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    spb=60/r.serato_bpm; n=int((len(y)/sr-r.first_beat_s)/spb)
    offs=[]
    for i in range(n):
        t=r.first_beat_s+i*spb; c=int(t*sr/hop); w=int(0.25*spb*sr/hop)
        if c-w<0 or c+w>=len(env): continue
        seg=env[c-w:c+w+1]
        if seg.max()<np.percentile(env,75): continue
        offs.append((np.argmax(seg)-w)*hop/sr*1000)
    offs=np.array(offs); h=len(offs)//2
    rows.append(dict(track=k,bpm=r.serato_bpm,n=len(offs),med_ms=np.median(offs),mad_ms=np.median(np.abs(offs-np.median(offs))),
                     drift_ms=np.median(offs[h:])-np.median(offs[:h])))
D=pd.DataFrame(rows); D.to_csv('grid_check.csv',index=False)
print(len(D),'audio tracks'); print(D[['med_ms','mad_ms','drift_ms']].describe().round(1))
print('|median offset|<=10ms',(D.med_ms.abs()<=10).mean(),' <=20ms',(D.med_ms.abs()<=20).mean(),' |drift|<=10ms',(D.drift_ms.abs()<=10).mean())
