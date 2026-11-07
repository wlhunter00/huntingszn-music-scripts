"""Test Will's cue formula (slots 1-8 = Serato A-H = index 0-7). Spacing in beats from Serato BeatGrid."""
import pandas as pd, numpy as np
T=pd.read_pickle('/tmp/T.pkl'); TOL=1.0
def near(x,v): return (x-v).abs()<=TOL
def mult(x,k): return ((x+TOL)%k)<=2*TOL
d=lambda a,b: T[a]-T[b]
R={}
R['R1 cue3 = cue4-32']        =(near(d(4,3),32), T[[3,4]].notna().all(1))
R['R2 cue2 = cue3-32|64']     =(near(d(3,2),32)|near(d(3,2),64), T[[2,3]].notna().all(1))
R['R3 cue1 = cue4-k*32 (k>=1), before cue2']=(mult(d(4,1),32)&(d(4,1)>TOL)&(T[1]<T[2]+TOL), T[[1,2,4]].notna().all(1))
R['R4 cue5 = cue6-32']        =(near(d(6,5),32), T[[5,6]].notna().all(1))
R['R5 cue7 = cue6+32']        =(near(d(7,6),32), T[[6,7]].notna().all(1))
R['R6 cue8 = cue6+64']        =(near(d(8,6),64), T[[6,8]].notna().all(1))
R['R7 cue6-cue4 multiple of 32 (>=0)']=(mult(d(6,4),32)&(d(6,4)>-TOL), T[[4,6]].notna().all(1))
R['R8 slots in time order 1<2<3<4<=5<6<7<8']=(None,None)
S=T[[1,2,3,4,5,6,7,8]]
def ordered(r):
    v=r.dropna().values; return bool(np.all(np.diff(v)>=-TOL)) if len(v)>1 else np.nan
T['ordered']=S.apply(ordered,axis=1)
R['R8 slots in time order 1<2<3<4<=5<6<7<8']=(T.ordered==True, T.ordered.notna())
# relaxed: any multiple of 16 for each consecutive pair
T['n_slots']=S.notna().sum(1)
T['full8']=T.n_slots==8
groups={'gold':T.group=='gold','own':T.group=='own','other':T.group=='other','ALL':T.group.notna()}
T['mikcls']=np.select([T.mik_named==1,T.mik_named==0],['all Energy-named','no Energy names'],'mixed')
rows=[]
for rn,(ok,base) in R.items():
    row={'rule':rn}
    for g,gm in groups.items():
        b=base&gm&(T.n_slots>0); row[g]=f"{100*ok[b].mean():.0f}% (n={b.sum()})"
    for g in ['all Energy-named','no Energy names']:
        b=base&(T.mikcls==g); row[g]=f"{100*ok[b].mean():.0f}% (n={b.sum()})"
    rows.append(row)
    T['ok_'+rn.split()[0]]=np.where(base,ok,np.nan)
out=pd.DataFrame(rows); print(out.to_string(index=False))
okc=[c for c in T if str(c).startswith('ok_')]
T['n_rules_tested']=T[okc].notna().sum(1); T['n_rules_ok']=(T[okc]==1).sum(1)
T['formula_strict']=(T.n_rules_tested>=5)&(T.n_rules_ok==T.n_rules_tested)
print('\nstrict-formula tracks (all tested rules pass, >=5 rules):'); print(T[T.n_slots>0].groupby('group').formula_strict.agg(['mean','sum']))
print(T[T.n_slots>0].groupby('mikcls').formula_strict.agg(['mean','sum','size']))
print('\nsingle-drop (cue6 == cue4):',(near(d(6,4),0)[T[[4,6]].notna().all(1)]).mean())
print('cue4->cue6 beats:',d(6,4).round().describe())
print('cue1 offset from grid first beat (beats):',T[1].round().describe(), T[1].round().value_counts().head(8).to_dict())
fe=(T.dur_s-0)  # from end
T['c8_from_end']= (T.dur_s*T.serato_bpm/60)-T[8]
print('cue8 beats before end:',T.c8_from_end.describe(), '\nwithin 16-48:',T.c8_from_end.between(16,48).mean())
print('cue8 beats before end binned:',pd.cut(T.c8_from_end,[-1e9,0,16,32,48,64,96,128,1e9]).value_counts().sort_index().to_dict())
print('\nslot-usage patterns (top):'); print(S.notna().apply(lambda r:''.join(str(i) for i in range(1,9) if r[i]),axis=1)[T.n_slots>0].value_counts().head(12))
T.to_pickle('/tmp/T2.pkl'); out.to_csv('rule_adherence.csv',index=False)
