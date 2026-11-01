"""Parse Serato cue points (Markers2 + BeatGrid) from file heads -> cues.csv / tracks.csv.
Read-only. Reuses BeatGrid parser from huntingszn-music-scripts/serato_bpm_cleanup."""
import base64, csv, io, json, os, re, sqlite3, struct, sys
sys.path.insert(0, '/tmp/hz/packages/serato_bpm_cleanup')
from serato_bpm_cleanup.beatgrid import parse_beatgrid, TerminalMarker
from serato_bpm_cleanup.markers import parse_markers_v1_counts
from mutagen.id3 import ID3
from mutagen.mp3 import MPEGInfo
HEADS='/tmp/heads'; OUT='/workspace/music-pipeline/cue-analysis'
MIK=re.compile(r'^Energy\s+\d+$',re.I)

def b64(blob):
    c=blob.replace(b'\n',b'').replace(b'\r',b'').rstrip(b'=')
    if len(c)%4==1: c=c[:-1]
    return base64.b64decode(c+b'='*((4-len(c)%4)%4))

def markers2(data):
    if data[:2]!=b'\x01\x01': return None
    nul=data.find(b'\x00',2); raw=data[2:nul if nul>0 else None]
    p=b64(raw)
    if p[:2]!=b'\x01\x01': return None
    fp=io.BytesIO(p[2:]); out=[]
    while True:
        nm=bytearray()
        while (ch:=fp.read(1)) not in (b'',b'\x00'): nm+=ch
        if not nm: break
        rl=fp.read(4)
        if len(rl)<4: break
        body=fp.read(struct.unpack('>I',rl)[0]); nm=nm.decode('ascii','replace')
        if nm=='CUE':
            idx=body[1]; pos=struct.unpack('>I',body[2:6])[0]; col=body[7:10].hex().upper()
            name=body[12:].split(b'\x00')[0].decode('utf-8','replace')
            out.append(dict(kind='CUE',index=idx,pos_ms=pos,end_ms='',color=col,name=name))
        elif nm=='LOOP':
            idx=body[1]; s,e=struct.unpack('>II',body[2:10]); name=body[20:].split(b'\x00')[0].decode('utf-8','replace')
            out.append(dict(kind='LOOP',index=idx,pos_ms=s,end_ms=e,color='',name=name))
    return out

def vorbis_geobs(b):
    """FLAC: SERATO_* comments -> {desc: payload}"""
    res={}; p=4
    while p+4<=len(b):
        h=b[p]; l=int.from_bytes(b[p+1:p+4],'big'); blk=b[p+4:p+4+l]
        if h&0x7f==4 and len(blk)==l:
            vl=struct.unpack('<I',blk[:4])[0]; q=4+vl; n=struct.unpack('<I',blk[q:q+4])[0]; q+=4
            for _ in range(n):
                L=struct.unpack('<I',blk[q:q+4])[0]; s=blk[q+4:q+4+L]; q+=4+L
                k,_,v=s.partition(b'=')
                if k.upper().startswith(b'SERATO_'):
                    try:
                        d=b64(v); # "application/octet-stream\0\0<desc>\0<payload>"
                        parts=d.split(b'\x00',3); res[parts[2].decode()]=parts[3]
                    except Exception: pass
        if h&0x7f==0 and len(blk)>=18:
            x=int.from_bytes(blk[10:18],'big'); sr=x>>44; tot=x&((1<<36)-1)
            res['_dur']=tot/sr if sr else None
        if h>>7: break
        p+=4+l
    return res

def mp3_geobs(path, fullsize):
    t=ID3(path); res={f.desc:bytes(f.data) for f in t.getall('GEOB') if f.desc}
    try:
        with open(path,'rb') as fh:
            fh.seek(t.size); info=MPEGInfo(fh)
        tail=len(open(path,'rb').read())-t.size
        # mutagen estimates CBR length from available bytes -> rescale to full file size
        if not getattr(info,'_xing',None) and info.bitrate:
            est=(fullsize-t.size)*8/info.bitrate
            res['_dur']=est if abs(info.length - tail*8/info.bitrate)<1 else info.length
        else: res['_dur']=info.length
    except Exception: res['_dur']=None
    return res

def beat_at(grid, t):
    """continuous beat index (0 = first grid marker) at time t (s)"""
    ms=grid.markers; beat=0.0
    for i,m in enumerate(ms):
        if isinstance(m,TerminalMarker):
            return beat+(t-m.position_s)*m.bpm/60
        nxt=ms[i+1].position_s; n=m.beats_till_next_marker
        if t<nxt or i==0 and t<m.position_s:
            return beat+(t-m.position_s)*n/(nxt-m.position_s)
        beat+=n
    return None

def main():
    sizes={x['Path']:x['Size'] for x in json.load(open('/tmp/files_all.json'))}
    db=sqlite3.connect('/workspace/music-pipeline/catalog/library.sqlite')
    cat={r[0][len('DJ Music/'):]:r[1:] for r in db.execute('select relative_path,genre,duration_sec,bpm,camelot_key,artist,title from tracks')}
    cues=[]; tracks=[]
    for root,_,fs in os.walk(HEADS):
        for f in fs:
            full=os.path.join(root,f); rel=os.path.relpath(full,HEADS); ext=f.rsplit('.',1)[-1].lower()
            if ext not in('mp3','flac'): 
                tracks.append(dict(path=rel,ext=ext,status='unsupported_format')); continue
            st='ok'; g={}
            try:
                g=mp3_geobs(full,sizes.get(rel,0)) if ext=='mp3' else vorbis_geobs(open(full,'rb').read())
            except Exception as e: st='tag_error:'+type(e).__name__
            c=cat.get(rel,(None,)*6)
            dur=g.get('_dur') or c[1]
            grid=None; bpm=None; first=None; dyn=False
            if 'Serato BeatGrid' in g:
                try:
                    grid=parse_beatgrid(g['Serato BeatGrid']); bpm=grid.bpm; first=grid.first_beat_s; dyn=grid.is_dynamic
                except Exception: grid=None
            ents=[]
            if 'Serato Markers2' in g:
                try: ents=markers2(g['Serato Markers2']) or []
                except Exception as e: st='markers2_error'
            v1=None
            if 'Serato Markers_' in g:
                try: v1=parse_markers_v1_counts(g['Serato Markers_']).total
                except Exception: pass
            for e in ents:
                b=beat_at(grid,e['pos_ms']/1000) if grid else None
                e.update(path=rel,folder=rel.split('/')[0],bpm=bpm,beat=round(b,3) if b is not None else '',
                         bar=round(b/4,3) if b is not None else '',dur_s=round(dur,2) if dur else '',
                         from_end_beats=round((dur-e['pos_ms']/1000)*bpm/60,2) if dur and bpm else '',
                         mik_like=bool(MIK.match(e['name'].strip())), genre=c[0])
                cues.append(e)
            nc=sum(e['kind']=='CUE' for e in ents)
            tracks.append(dict(path=rel,ext=ext,status=st,folder=rel.split('/')[0],genre=c[0],dur_s=dur,
                serato_bpm=bpm,catalog_bpm=c[2],camelot=c[3],first_beat_s=first,dynamic_grid=dyn,
                has_markers2='Serato Markers2' in g,has_beatgrid=grid is not None,n_cues=nc,
                n_loops=sum(e['kind']=='LOOP' for e in ents),v1_count=v1))
    cols=['path','folder','genre','kind','index','pos_ms','end_ms','color','name','mik_like','bpm','beat','bar','dur_s','from_end_beats']
    with open(f'{OUT}/cues.csv','w',newline='') as fh:
        w=csv.DictWriter(fh,cols); w.writeheader(); [w.writerow({k:e.get(k) for k in cols}) for e in cues]
    with open(f'{OUT}/tracks.csv','w',newline='') as fh:
        cs=sorted({k for t in tracks for k in t}); w=csv.DictWriter(fh,cs); w.writeheader(); w.writerows(tracks)
    print(len(tracks),'tracks',len(cues),'cue/loop rows')
main()
