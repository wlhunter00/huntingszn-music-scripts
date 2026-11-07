"""Parse Serato .crate files (read-only copies in /tmp/serato) -> crate_membership.csv"""
import csv, os, struct
D='/tmp/serato/Subcrates'; OUT='/workspace/music-pipeline/cue-analysis/crate_membership.csv'
def chunks(b):
    p=0
    while p+8<=len(b):
        t=b[p:p+4].decode('latin1'); l=struct.unpack('>I',b[p+4:p+8])[0]; yield t,b[p+8:p+8+l]; p+=8+l
rows=[]
for f in sorted(os.listdir(D)):
    if not f.endswith('.crate'): continue
    crate=f[:-6].replace('%%','/')
    for t,v in chunks(open(os.path.join(D,f),'rb').read()):
        if t=='otrk':
            for t2,v2 in chunks(v):
                if t2=='ptrk': rows.append((crate,v2.decode('utf-16-be')))
with open(OUT,'w',newline='') as fh: w=csv.writer(fh); w.writerow(['crate','serato_path']); w.writerows(rows)
print(len(rows)); import collections; print(collections.Counter(r[0].split('/')[0] for r in rows)); print(rows[:3])
