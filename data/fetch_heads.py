"""Read-only: download only the tag-bearing head of each audio file in B2 'DJ Music/'.
mp3: ID3v2 header size; flac: metadata blocks up to the VORBIS_COMMENT block. Uses `rclone cat --count`."""
import json, os, subprocess, struct, sys
from concurrent.futures import ThreadPoolExecutor
REMOTE = "b2:huntingszn-music/DJ Music/"
OUT = "/tmp/heads"
files = [x for x in json.load(open('/tmp/files.json')) if x['Path'].lower().rsplit('.',1)[-1] in ('mp3','flac','wav','m4a')]
def cat(path, n):
    return subprocess.run(["rclone","cat","--count",str(n),REMOTE+path],capture_output=True,timeout=300).stdout
def need(b, ext):
    if ext=='mp3':
        if b[:3]!=b'ID3': return 0
        s=b[6:10]; return 10+((s[0]<<21)|(s[1]<<14)|(s[2]<<7)|s[3])+10
    if ext=='flac':
        if b[:4]!=b'fLaC': return 0
        p=4
        while p+4<=len(b):
            h=b[p]; l=int.from_bytes(b[p+1:p+4],'big')
            if h&0x7f==4: return p+4+l
            if h>>7: return 0
            p+=4+l
        return p+4+16*1024*1024  # unknown, ask for more
    return 0
def one(x):
    path=x['Path']; ext=path.rsplit('.',1)[-1].lower(); dst=os.path.join(OUT,path)
    if os.path.exists(dst): return 'cached'
    os.makedirs(os.path.dirname(dst),exist_ok=True)
    if ext in ('wav','m4a'):
        b=cat(path, 2*1024*1024)  # wav LIST/ID3 chunk may be at end; best effort
    else:
        b=cat(path, 524288)
        for _ in range(3):
            n=need(b,ext)
            if n<=len(b): break
            b=cat(path, min(n, x['Size']))
    open(dst+'.part','wb').write(b); os.rename(dst+'.part',dst)
    return 'ok'
with ThreadPoolExecutor(24) as ex:
    for i,r in enumerate(ex.map(one, files)):
        if i%250==0: print(i, r, flush=True)
print('done', len(files))
