"""Package the application with an existing licensed Windows CPython/Tk installation."""
import argparse,hashlib,json,pathlib,shutil,sys

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--python-home',required=True,type=pathlib.Path);parser.add_argument('--output',required=True,type=pathlib.Path);args=parser.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=args.output.resolve();py=out/'python';app=out/'app';py.mkdir(parents=True,exist_ok=True);app.mkdir(exist_ok=True)
    for name in ('python.exe','pythonw.exe','python3.dll','python311.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        shutil.copy2(args.python_home/name,py/name)
    for name in ('Lib','DLLs','tcl'):
        shutil.copytree(args.python_home/name,py/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc','*.pyo'))
    (py/'python311._pth').write_text('../app\nLib\nDLLs\n',encoding='utf-8')
    shutil.copy2(root/'src/project_manager/app.py',app/'project_manager.pyw');shutil.copy2(root/'tools/cloud_project_receiver.py',app/'cloud_project_receiver.py');shutil.copy2(root/'README.md',app/'README.md')
    (out/'START.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0python\\pythonw.exe" "%~dp0app\\project_manager.pyw"\r\n',encoding='ascii')
    manifest={'files':{p.relative_to(out).as_posix():{'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='RUNTIME-MANIFEST.json'}}
    (out/'RUNTIME-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(out),'files':len(manifest['files'])}))
if __name__=='__main__':main()
