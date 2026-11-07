"""Sanity check: does RMS energy change at cue points vs random 32-beat grid points? Downloads ~30 full files to /tmp/audio (read-only from B2)."""
import pandas as pd, numpy as np, subprocess, os, librosa, json
T=pd.read_pickle('/tmp/T3.pkl')
C=T[(T.mikcls=='no Energy names')&(T.n_slots==8)&(T.group.isin(['gold','own']))&(T.ext=='mp3')&(T.ok_R1==1)]
C=C.sample(frac=1,random_state=0); C=C[C.groupby('style').cumcount()<6].head(30)
rows=[]
for k,r in C.iterrows():
    src=('b2:huntingszn-music/' if k.startswith('My Songs') else 'b2:huntingszn-music/DJ Music/')+k
    dst='/tmp/audio/'+__import__('hashlib').md5(k.encode()).hexdigest()+'.mp3'
    if not os.path.exists(dst): subprocess.run(['rclone','copyto',src,dst],check=True)
    try: y,sr=librosa.load(dst,sr=11025,mono=True)
    except Exception as e: print('skip',k,e); continue
    hop=256; rms=librosa.feature.rms(y=y,hop_length=hop)[0]; rdb=20*np.log10(rms+1e-6)
    spb=60/r.serato_bpm; t0=r.first_beat_s
    def delta(beat,w=8):
        t=t0+beat*spb; a=int((t-w*spb)*sr/hop); b=int(t*sr/hop); c=int((t+w*spb)*sr/hop)
        if a<0 or c>len(rdb): return np.nan
        return rdb[b:c].mean()-rdb[a:b].mean()
    for s in range(1,9): rows.append(dict(track=k,style=r['style'],slot=s,delta_db=delta(r[s])))
    nb=int(len(y)/sr/spb)
    for b in range(int(r[1]%32),nb,32):
        if all(abs(b-r[s])>2 for s in range(1,9)): rows.append(dict(track=k,style=r['style'],slot='grid32_noncue',delta_db=delta(b)))
D=pd.DataFrame(rows); D.to_csv('audio_check.csv',index=False)
print(len(C),'tracks'); print(D.groupby('slot').delta_db.agg(['median','mean',lambda s:(s.abs()>3).mean(),'count']).round(2))
