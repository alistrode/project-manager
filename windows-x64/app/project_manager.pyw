import json, os, threading, tkinter as tk, io, zipfile, webbrowser, uuid
from tkinter import ttk, messagebox
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote
BASE=Path(__file__).resolve().parent
DATA_BASE=BASE
DATA_CONFIG=BASE.parent/'data-location.json'
if DATA_CONFIG.is_file():
    configured=Path(json.loads(DATA_CONFIG.read_text(encoding='utf-8'))['data_directory']).expanduser()
    DATA_BASE=(configured if configured.is_absolute() else DATA_CONFIG.parent/configured).resolve()
DATA_BASE.mkdir(parents=True,exist_ok=True)
DATA=DATA_BASE/'projects.json'
INDEX=DATA_BASE/'session_index.json'
PORT=18762
LOCK=threading.RLock()
PROJECTS=[]
SESSIONS=[]
INDEX_META={}
DOWNLOAD_FILES=None

def load():
    global PROJECTS,SESSIONS,INDEX_META
    items=json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else []
    index=json.loads(INDEX.read_text(encoding='utf-8')) if INDEX.exists() else {'sessions':[]}
    if not isinstance(items,list):raise ValueError('projects.json 必须是项目数组')
    with LOCK:
        PROJECTS,SESSIONS=items,index.get('sessions',[])
        INDEX_META={k:v for k,v in index.items() if k!='sessions'}
        INDEX_META['indexed_last_activity']=max((x.get('last_seen','') for x in SESSIONS),default='')

def usage_context():
    return {
        'paths_host': 'Windows 远端电脑；通过已验证 SSH 访问，不是云端本地路径',
        'session_backup': {
            'archive': INDEX_META.get('archive',''),
            'indexed_from': INDEX_META.get('cutoff',''),
            'indexed_last_activity': INDEX_META.get('indexed_last_activity',''),
            'scope': '历史备份索引，不含备份之后的会话；不代表已导入当前 Codex',
            'location_format': 'archive 是 tar 文件路径；archive_members 是归档内部成员，可能含多个分段',
        },
        'association_notes': '工作目录是上下文关联；命令或请求提及仅为候选关联。共享会话不能单独证明项目相同。',
        'project_identity_rule': '相同非通用目录一般视为同一项目的重要依据；通用目录、父子目录及同一会话提及不自动合并。疑似重复先报告用户。',
        'directory_notes': '目录角色以 directories 的 kind、verified、evidence 为准；运行包、脚本、第三方依赖和备份不冒称源码。',
        'manager_backups': 'ProjectManager 下 backup-* 是管理器自身备份，与会话归档分开。',
    }

def response_context(body):
    if isinstance(body,dict):return {**body,'usage_context':usage_context()}
    return body

def project_sessions(project):
    ids=set(project.get('session_ids',[]));pid=project.get('id')
    with LOCK:
        indexed=[s for s in SESSIONS if s['id'] in ids or (pid and pid in s.get('project_ids',[])) or any(x['name']==project['name'] for x in s.get('projects',[]))]
    known={s['id'] for s in indexed}
    # Current thread references are explicit project metadata, not additions to the historical archive index.
    references=[dict(s) for s in project.get('sessions',[]) if isinstance(s,dict) and s.get('id') in ids and s.get('source_type')=='current-session-reference' and s['id'] not in known]
    return indexed+references

def session_search(query='',project=None):
    rows=project_sessions(project) if project else SESSIONS[:]
    q=query.strip().casefold()
    if q:rows=[x for x in rows if q in ' '.join([x['id'],x.get('title',''),*[p['name'] for p in x.get('projects',[])]]).casefold()]
    return sorted(rows,key=lambda x:session_timestamp(x.get('last_seen','')),reverse=True)

def describe(project):
    result=dict(project);sessions=sorted(project_sessions(project),key=lambda x:session_timestamp(x.get('last_seen','')),reverse=True)
    session_ids=list(dict.fromkeys([s['id'] for s in sessions]+list(project.get('session_ids',[]))))
    result.update(session_ids=session_ids,session_count=len(session_ids),sessions=sessions,last_session=sessions[0].get('last_seen','') if sessions else '',usage_context=usage_context())
    return result

def session_timestamp(value):
    if not value:return 0
    try:
        from datetime import datetime,timezone,timedelta
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        return parsed.timestamp()
    except (ValueError,TypeError):return 0

def latest_activity(project):
    return max((session_timestamp(s.get('last_seen','')) for s in project_sessions(project)),default=0)

def directory_column(project,source=True):
    if source:return '；'.join(project.get('source_paths',[])) or '未确认源码目录'
    return '；'.join('['+d['kind']+'] '+d['path'] for d in project.get('non_source_paths',[])) or '未登记'

def full_project_info(project):
    p=describe(project);backup=usage_context()['session_backup'];lines=[p['name'],'',p.get('summary','待补充概述'),'','【会话备份】',backup['archive'],'索引范围：'+backup['indexed_from']+' 至 '+display_time(backup['indexed_last_activity']),backup['scope'],'','【目录及核实依据】']
    for d in p.get('directories',[]):
        lines+=['['+d['kind']+'] '+d['path'],('本机存在' if d.get('exists') else '本机未找到 / 历史路径')+'；'+d.get('evidence','')]
    if not p.get('directories'):lines+=[p['path']+'（用途待确认）' if p['path'] else '项目目录待确认']
    lines+=['','【项目关联】',json.dumps(p.get('related_projects',[]),ensure_ascii=False),json.dumps(p.get('parent_project',{}),ensure_ascii=False),'','【项目说明】',p.get('notes','无补充说明'),'','【最近会话】',display_time(p.get('last_session','')) or '无','目录核实时间：'+display_time(p.get('directory_reviewed_at','')),'','【全部 Codex 会话索引与 ID】']
    indexed=set()
    for i,x in enumerate(p['sessions'],1):
        lines+=[str(i)+'. '+x.get('title','未命名会话')+'  '+display_time(x.get('last_seen','')),'ID: '+x['id'],'备份：'+x.get('archive',''),'归档内文件：'+'；'.join(x.get('archive_members',[])),'关联依据：'+json.dumps(x.get('projects',[]),ensure_ascii=False)];indexed.add(x['id'])
    for sid in p['session_ids']:
        if sid not in indexed:lines+=['未找到详细索引；ID: '+sid]
    return '\n'.join(lines)

def save():
    with LOCK:
        temp=DATA.with_suffix('.json.tmp')
        temp.write_text(json.dumps(PROJECTS,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,DATA)

def lookup(name='',exact=False):
    q=name.strip().casefold()
    with LOCK:rows=sorted([dict(p) for p in PROJECTS],key=latest_activity,reverse=True)
    if not q:return rows
    named=[p for p in rows if q==p['name'].casefold()]
    if named:return named
    found=[p for p in rows if q in [a.casefold() for a in p.get('aliases',[])]]
    if found or exact:return found
    return [p for p in rows if q in ' '.join([p['name'],p['path'],p.get('summary',''),*p.get('aliases',[]),*[x.get('title','')+' '+x['id'] for x in project_sessions(p)]]).casefold()]

# Project context delivery uses the existing authenticated SSH connection.
import hashlib,hmac,secrets,time,socket
from datetime import datetime,timezone
RELAY_DIRECTORY=Path(r'C:\Users\Acer\Downloads\ssh-remote-win10-portable\ssh-remote-win10-portable')
class ProjectHandoff:
    def __init__(self):
        self.lock=threading.RLock();self.receivers={};self.deliveries={}
        folder=DATA_BASE/'handoff'
        if folder.is_dir():
            for state in folder.glob('*.state.json'):
                try:
                    d=json.loads(state.read_text(encoding='utf-8'));delivery_id=state.name.split('.')[0]
                    if len(delivery_id)!=32:continue
                    d['packet']=json.loads((folder/(delivery_id+'.json')).read_text(encoding='utf-8'));self.deliveries[delivery_id]=d
                except (OSError,ValueError,KeyError):pass
    def persist(self,delivery_id):
        d={k:v for k,v in self.deliveries[delivery_id].items() if k!='packet'}
        target=DATA_BASE/'handoff'/(delivery_id+'.state.json');tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(target)
    def config(self):
        config=json.loads((RELAY_DIRECTORY/'data'/'remote.json').read_text(encoding='utf-8'))
        if config.get('target')!='win10' or config.get('user')!='relay':raise ValueError('中继配置不匹配')
        return config
    def active(self):
        with self.lock:return [r for r in self.receivers.values() if time.time()-r['last_seen']<15]
    def register(self,data):
        cfg=self.config();stamp=int(data.get('timestamp',0));rid=data.get('receiver_id','');name=data.get('name','');inbox=data.get('inbox','')
        if len(rid)!=32 or any(c not in '0123456789abcdef' for c in rid) or abs(time.time()-stamp)>60 or not name or len(name)>160 or len(inbox)>1024:raise ValueError('接收端注册信息无效')
        body='|'.join([cfg['session'],rid,name,str(stamp),inbox]).encode()
        expected=hmac.new(bytes.fromhex(cfg['secret']),body,hashlib.sha256).hexdigest()
        if data.get('relay_session')!=cfg['session'] or not hmac.compare_digest(expected,str(data.get('proof',''))):raise ValueError('接收端未通过中继身份验证')
        token=secrets.token_hex(32)
        with self.lock:self.receivers[rid]={'id':rid,'name':name,'inbox':inbox,'last_seen':time.time(),'token':token}
        return {'token':token,'receiver_id':rid}
    def receiver(self,authorization):
        token=authorization.removeprefix('Bearer ')
        with self.lock:
            for r in self.receivers.values():
                if hmac.compare_digest(r['token'],token):r['last_seen']=time.time();return r
        raise ValueError('接收端认证已失效')
    def send(self,project):
        with self.lock:
            receivers=self.active()
            if not receivers:raise ValueError('没有可接收项目的 SSH 云端连接；请先使用配套 Skill 连接云端。')
            if len(receivers)>1:raise ValueError('检测到多个云端接收端，请保留目标云端连接后再发送。')
            receiver=receivers[0];delivery_id=uuid.uuid4().hex
            packet={'version':1,'delivery_id':delivery_id,'created_at':datetime.now(timezone.utc).isoformat(),'source_host':socket.gethostname(),'relay_directory':str(RELAY_DIRECTORY),'project':describe(project)}
            digest=hashlib.sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            folder=DATA_BASE/'handoff';folder.mkdir(exist_ok=True)
            (folder/(delivery_id+'.json')).write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
            self.deliveries[delivery_id]={'packet':packet,'receiver_id':receiver['id'],'receiver_name':receiver['name'],'digest':digest,'status':'queued'}
            self.persist(delivery_id)
            return {'delivery_id':delivery_id,'project':project['name'],'session_count':packet['project']['session_count'],'receiver':receiver['name'],'status':'queued'}
    def pending(self,receiver):
        with self.lock:return {'packets':[d['packet'] for d in self.deliveries.values() if d['receiver_id']==receiver['id'] and d['status']=='queued']}
    def ack(self,receiver,data):
        with self.lock:
            d=self.deliveries.get(data.get('delivery_id'))
            if not d or d['receiver_id']!=receiver['id'] or not hmac.compare_digest(d['digest'],str(data.get('sha256',''))):raise ValueError('送达回执校验失败')
            d.update(status='delivered',received_at=datetime.now(timezone.utc).isoformat(),cloud_json=data.get('json_path',''),cloud_markdown=data.get('markdown_path',''))
            receipt={k:v for k,v in d.items() if k not in ('packet','digest')}
            receipt['delivery_id']=data['delivery_id']
            (DATA_BASE/'handoff'/(data['delivery_id']+'.receipt.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
            self.persist(data['delivery_id'])
            return {'ok':True,'status':'delivered'}
    def status(self,delivery_id=''):
        with self.lock:
            result={'connected':bool(self.active()),'receivers':[{'name':r['name'],'inbox':r['inbox']} for r in self.active()]}
            if delivery_id and delivery_id in self.deliveries:
                d=self.deliveries[delivery_id];result['delivery']={k:v for k,v in d.items() if k not in ('packet','digest','receiver_id')};result['delivery']['project']=d['packet']['project']['name']
            return result
HANDOFF=ProjectHandoff()

class API(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,code,body):
        raw=json.dumps(response_context(body),ensure_ascii=False).encode('utf-8');self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536:raise ValueError('请求大小无效')
            data=json.loads(self.rfile.read(length));route=urlparse(self.path).path
            if route=='/api/handoff/register':body=HANDOFF.register(data)
            elif route=='/api/handoff/ack':body=HANDOFF.ack(HANDOFF.receiver(self.headers.get('Authorization','')),data)
            elif route=='/api/handoff/send':
                projects=lookup(data.get('project',''),True)
                if len(projects)!=1:raise ValueError('请指定唯一的项目名称')
                body=HANDOFF.send(projects[0])
            else:self.reply(404,{'error':'接口不存在'});return
            self.reply(200,body)
        except (ValueError,OSError,KeyError) as e:self.reply(400,{'error':str(e)})
    def do_GET(self):
        u=urlparse(self.path); qs=parse_qs(u.query); code=200
        if u.path=='/api/handoff/status':self.reply(200,HANDOFF.status(qs.get('delivery_id',[''])[0]));return
        if u.path=='/api/handoff/pending':
            try:self.reply(200,HANDOFF.pending(HANDOFF.receiver(self.headers.get('Authorization',''))))
            except ValueError:self.reply(401,{'error':'接收端认证已失效'})
            return
        if u.path=='/download':
            files=DOWNLOAD_FILES or {n:(BASE/n).read_bytes() for n in ('project_manager.pyw','README.md','启动项目管理器.cmd','项目清单.csv','session_index.json','cloud_project_receiver.py','connect-win10-public-ssh-skill.zip') if (BASE/n).is_file()}
            files=dict(files)
            if INDEX.is_file():files['session_index.json']=INDEX.read_bytes()
            with LOCK: files['projects.json']=json.dumps(PROJECTS,ensure_ascii=False,indent=2).encode('utf-8')
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
                for name,content in files.items():z.writestr('project-manager/'+name,content)
            data=stream.getvalue();self.send_response(200)
            self.send_header('Content-Type','application/zip');self.send_header('Content-Disposition','attachment; filename="project-manager.zip"')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        if u.path=='/health': body={'ok':True,'service':'project-manager'}
        elif u.path in ('/api/projects','/api/lookup'):
            name=qs.get('name',[''])[0]
            if u.path=='/api/lookup' and not name.strip():code,body=400,{'error':'缺少 name 参数'}
            else:
                rows=lookup(name,qs.get('exact',['0'])[0]=='1')
                body={'query':name,'count':len(rows),'projects':[describe(p) for p in rows]}
        elif u.path=='/api/sessions':
            name=qs.get('project',[''])[0];q=qs.get('q',[''])[0];sid=qs.get('id',[''])[0]
            if not name.strip():code,body=400,{'error':'请提供 project 参数；会话查询必须归属于项目'}
            else:
                projects=lookup(name,True);rows=list({x['id']:x for p in projects for x in session_search(q,p)}.values())
                if sid:rows=[x for x in rows if x['id']==sid]
                body={'project':name,'count':len(rows),'session_ids':list(dict.fromkeys(x['id'] for x in rows)),'sessions':rows}
        else:code,body=404,{'error':'接口不存在'}
        data=json.dumps(response_context(body),ensure_ascii=False).encode('utf-8')
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

VIEW_FILE=DATA_BASE/'view-settings.json'
GROUP_MODES=('加入顺序','按主机','按项目性质','主次 / 依赖树')
SORT_MODES=('加入顺序 ↓','加入顺序 ↑','最近活动 ↓','最近活动 ↑','最近会话 ↓','最近会话 ↑','项目名称 A→Z')

def registered_time(project):
    return project.get('registered_at') or project.get('added_at') or ''

def activity_time(project):
    values=[project.get(key,'') for key in ('last_seen','updated_at','last_activity_at')]
    values.extend(session.get('last_seen','') for session in project_sessions(project))
    return max(values,key=session_timestamp,default='')

def project_hosts(project):
    hosts=[]
    def add(value):
        if isinstance(value,str) and value.strip() and value.strip() not in hosts:hosts.append(value.strip())
    values=project.get('hosts',[])
    if isinstance(values,str):values=values.replace('；',';').split(';')
    for value in values:add(value)
    for key in ('host','runtime_host'):add(project.get(key))
    for key in ('runtime_repository','source_repository'):
        value=project.get(key)
        if isinstance(value,dict):add(value.get('host'))
    for directory in project.get('directories',[]):
        add(directory.get('host'))
        if not directory.get('host') and directory.get('exists') and ':' in directory.get('path',''):
            add(project.get('checked_on') or socket.gethostname())
    if not hosts and project.get('exists_here') and ':' in project.get('path',''):
        add(project.get('checked_on') or socket.gethostname())
    return sorted(hosts,key=str.casefold) or ['主机待确认']

def project_refs(value):
    if not value:return []
    if isinstance(value,str):return [v.strip() for v in value.replace('；',';').split(';') if v.strip()]
    if isinstance(value,dict):return [value.get('id') or value.get('project_id') or value.get('name') or value.get('project') or '']
    return [r for item in value for r in project_refs(item)] if isinstance(value,list) else []

def hierarchy(projects):
    by_id={p['id']:p for p in projects};names={p['name'].casefold():p['id'] for p in projects}
    parents={};relations={};cycles=set()
    def resolve(ref):return ref if ref in by_id else names.get(ref.casefold())
    for project in projects:
        pid=project['id'];explicit=project_refs(project.get('depends_on') or project.get('dependencies'))
        parent=project_refs(project.get('primary_project') or project.get('parent_project'))
        selected=parent or explicit
        if selected:
            target=resolve(selected[0])
            if target:parents[pid]=target
        if explicit:
            relations[pid]='依赖：'+'；'.join(by_id[resolve(r)]['name'] if resolve(r) else r+'（未登记）' for r in explicit)
        elif parent:
            basis=(project.get('parent_project') or {}).get('basis','') if isinstance(project.get('parent_project'),dict) else ''
            relations[pid]=('目录层级：' if '目录' in basis else '上级项目：')+(by_id[parents[pid]]['name'] if pid in parents else selected[0])
        elif project.get('relationship_status')=='independent_verified':relations[pid]='独立项目；无上级 / 项目依赖'
        else:relations[pid]='未登记依赖'
    # Cut a display edge in each cycle so every project remains reachable.
    done=set()
    for start in by_id:
        path=[];positions={};node=start
        while node in by_id and node not in done:
            if node in positions:
                cycle=path[positions[node]:];cycles.update(cycle);parents.pop(cycle[0],None);break
            positions[node]=len(path);path.append(node)
            if node not in parents:break
            node=parents[node]
        done.update(path)
    for pid in cycles:relations[pid]='关系成环（已展开为树）；'+relations[pid]
    return parents,relations,cycles


class App(tk.Tk):
    def __init__(self,server):
        super().__init__();self.server=server
        self.title('项目管理器');self.geometry(f'{min(1600,self.winfo_screenwidth()-80)}x760');self.minsize(1050,500)
        self.configure(bg='#f4f6fa');self.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f4f6fa');style.configure('TLabel',background='#f4f6fa',foreground='#25324a')
        style.configure('ProjectName.TButton',foreground='#135ab7',background='#edf4ff',padding=(5,3))
        style.configure('Treeview',indent=18,rowheight=34,background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',background='#e9eef6',padding=8)
        style.map('Treeview',background=[('selected','#dceaff')],foreground=[('selected','#152b4f')])
        main=ttk.Frame(self,padding=22);main.pack(fill='both',expand=True)
        ttk.Label(main,text='项目管理器',font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w')
        self.view_hint=tk.StringVar(value='项目概述 · 工作目录 · 项目内 Codex 会话')
        ttk.Label(main,textvariable=self.view_hint,foreground='#63718a').pack(anchor='w',pady=(4,6))
        backup=usage_context()['session_backup']
        ttk.Label(main,text='会话备份：'+backup['archive']+'  ｜  索引自 '+backup['indexed_from']+' 至 '+display_time(backup['indexed_last_activity'])+'（历史索引，未自动导入）',foreground='#63718a',wraplength=1400).pack(anchor='w',pady=(0,12))
        bar=ttk.Frame(main);bar.pack(fill='x',pady=(0,14))
        self.query=tk.StringVar();entry=ttk.Entry(bar,textvariable=self.query,font=('Microsoft YaHei UI',11))
        entry.pack(side='left',fill='x',expand=True,ipady=5);entry.focus_set()
        for label,fn in [('新增项目',lambda:self.editor()),('编辑',self.edit),('重新载入',self.reload)]:
            ttk.Button(bar,text=label,command=fn).pack(side='left',padx=(8,0),ipady=4)
        try:self.view_state=json.loads(VIEW_FILE.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.view_state={}
        if not isinstance(self.view_state,dict):self.view_state={}
        self.group_mode=tk.StringVar(value=self.view_state.get('group','加入顺序'));self.sort_mode=tk.StringVar(value=self.view_state.get('sort','加入顺序 ↓'))
        self.recent_count=tk.StringVar(value=str(self.view_state.get('recent_count','10')));self.show_recent=tk.BooleanVar(value=self.view_state.get('show_recent',True))
        if self.group_mode.get() not in GROUP_MODES:self.group_mode.set(GROUP_MODES[0])
        if self.sort_mode.get() not in SORT_MODES:self.sort_mode.set(SORT_MODES[0])
        if self.recent_count.get() not in ('5','10','20','全部'):self.recent_count.set('10')
        filters=ttk.Frame(main);filters.pack(fill='x',pady=(0,10))
        for label,var,values,size in [('分组',self.group_mode,GROUP_MODES,17),('组内排序',self.sort_mode,SORT_MODES,17),('最近加入',self.recent_count,('5','10','20','全部'),5)]:
            ttk.Label(filters,text=label).pack(side='left',padx=(0,6))
            box=ttk.Combobox(filters,textvariable=var,values=values,state='readonly',width=size);box.pack(side='left',padx=(0,16));box.bind('<<ComboboxSelected>>',self.change_view)
        ttk.Checkbutton(filters,text='顶部显示最近加入框',variable=self.show_recent,command=self.change_view).pack(side='left')
        ttk.Button(filters,text='展开分组',command=lambda:self.set_groups_open(True)).pack(side='right')
        ttk.Button(filters,text='收起分组',command=lambda:self.set_groups_open(False)).pack(side='right',padx=(0,6))
        grid=ttk.Frame(main);grid.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(grid,height=6,columns=('joined','activity','latest','summary','host','category','relation','index','session_id','sessions','source','other'),show='tree headings',selectmode='browse')
        self.tree.heading('#0',text='项目分组 / 主次树');self.tree.column('#0',width=360,minwidth=260,stretch=False)
        for key,label,width in [('joined','登记时间 / 顺序',145),('activity','最近活动',140),('latest','最近会话（历史索引）',170),('summary','一句话概述（悬停看完整概述）',260),('host','所属主机',180),('category','项目性质',110),('relation','主次 / 依赖关系',220),('index','Codex 会话索引 / 标题',240),('session_id','Codex 会话 ID / 全复制',360),('sessions','会话数',65),('source','源码 / 脚本目录',270),('other','运行时 / 其他目录',320)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=65,stretch=key in ('summary','source','other'))
        self.latest_desc=True;self.tree.heading('latest',command=self.toggle_latest_sort);self.tree.heading('joined',command=self.sort_by_added)
        self.actions=tk.Frame(grid,width=70,bg='white');self.actions.grid(row=0,column=1,sticky='ns');self.actions.grid_propagate(False)
        self.action_heading=tk.Label(self.actions,text='操作',bg='#e9eef6',fg='#25324a',font=('Microsoft YaHei UI',10),bd=0)
        self.action_heading.place(x=0,y=0,relwidth=1,height=38)
        vs=ttk.Scrollbar(grid,orient='vertical',command=self.tree.yview);hs=ttk.Scrollbar(grid,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=lambda *a:(vs.set(*a),self.after_idle(self.position_project_buttons)),xscrollcommand=lambda *a:(hs.set(*a),self.after_idle(self.position_project_buttons)))
        self.tree.grid(row=0,column=0,sticky='nsew');vs.grid(row=0,column=2,sticky='ns');hs.grid(row=1,column=0,sticky='ew')
        grid.rowconfigure(0,weight=1);grid.columnconfigure(0,weight=1)
        self.project_buttons={};self.pin_buttons={};self.delete_buttons={};self.copy_buttons={};self.group_lines={};self.tooltip=None;self.tooltip_after=None;self.tooltip_hide_after=None;self.tooltip_key=None
        self.tree.bind('<Configure>',lambda _:self.after_idle(self.position_project_buttons))
        self.tree.bind('<ButtonRelease-1>',lambda _:self.after_idle(self.position_project_buttons),add='+')
        self.tree.bind('<<TreeviewOpen>>',lambda _:self.after_idle(self.position_project_buttons))
        self.tree.bind('<<TreeviewClose>>',lambda _:self.after_idle(self.position_project_buttons))
        self.tree.bind('<Motion>',self.on_summary_hover)
        self.tree.bind('<Leave>',lambda _:self.defer_hide_tooltip())
        self.tree.tag_configure('odd',background='#f7f9fc');self.tree.tag_configure('group',background='#eaf0f8',foreground='#253f65',font=('Microsoft YaHei UI',10,'bold'))
        self.tree.bind('<<TreeviewSelect>>',self.selected);self.tree.bind('<Double-1>',self.main_double_click)
        self.detail=None;self.session_tree=None
        self.note=tk.StringVar(value='点击项目名按钮发送给已连接的云端 AI；左侧三角展开会话。')
        ttk.Label(main,textvariable=self.note,wraplength=1080).pack(anchor='w',pady=(12,10))
        self.handoff_state=tk.StringVar(value='正在检查云端接收连接…');self.last_delivery='';self.last_project_click=('',0)
        ttk.Label(main,textvariable=self.handoff_state,foreground='#135ab7').pack(anchor='w',pady=(0,8))
        buttons=ttk.Frame(main);buttons.pack(fill='x')
        for label,fn in [('复制本项目全部 ID',self.copy_project_ids),('复制选中会话 ID',self.copy_main_session_id),('打开选中会话',self.open_main_session),('项目详情',self.open_project),('打开文件夹',self.open_folder),('复制路径',self.copy_path),('下载程序包',lambda:webbrowser.open(f'http://127.0.0.1:{PORT}/download')),('删除条目',self.remove)]:
            ttk.Button(buttons,text=label,command=fn).pack(side='left',padx=(0,8))
        self.status=tk.StringVar();ttk.Label(buttons,textvariable=self.status).pack(side='right')
        api=ttk.Frame(main);api.pack(fill='x',pady=(15,0))
        ttk.Label(api,text=f'查询接口  http://127.0.0.1:{PORT}/api/lookup?name=项目名',foreground='#64738c').pack(side='left')
        ttk.Button(api,text='复制接口地址',command=self.copy_api).pack(side='right')
        self.query.trace_add('write',lambda *_:self.refresh());self.refresh();self.after(1000,self.update_handoff_status);self.after(1800,self.poll_projects)
    def sync_registration(self):
        ids=[p['id'] for p in PROJECTS];active=set(ids)
        order=[pid for pid in self.view_state.get('registration_order',[]) if pid in active]
        known=set(order);order.extend(pid for pid in ids if pid not in known)
        self.registration_order={pid:i for i,pid in enumerate(order)}
        self.view_state['registration_order']=order
    def save_view(self):
        self.view_state.update(group=self.group_mode.get(),sort=self.sort_mode.get(),recent_count=self.recent_count.get(),show_recent=self.show_recent.get())
        try:
            value=json.dumps(self.view_state,ensure_ascii=False,indent=2)
            if not VIEW_FILE.exists() or VIEW_FILE.read_text(encoding='utf-8')!=value:
                tmp=VIEW_FILE.with_suffix('.tmp');tmp.write_text(value,encoding='utf-8');tmp.replace(VIEW_FILE)
        except OSError as e:self.note.set('视图设置未保存：'+str(e))
    def change_view(self,event=None):
        self.refresh();self.tree.yview_moveto(0)
    def sort_projects(self,projects):
        mode=self.sort_mode.get()
        if mode.startswith(('最近会话','最近活动')):
            timestamp=(lambda p:session_timestamp(activity_time(p))) if mode.startswith('最近活动') else latest_activity
            return sorted(projects,key=lambda p:(timestamp(p)<=0,-timestamp(p) if mode.endswith('↓') else timestamp(p),p['name'].casefold()))
        if mode.startswith('项目名称'):return sorted(projects,key=lambda p:p['name'].casefold())
        return sorted(projects,key=lambda p:self.registration_order.get(p['id'],-1),reverse=mode.endswith('↓'))
    def poll_projects(self):
        try:
            stamp=DATA.stat().st_mtime_ns
            if stamp!=self.data_stamp:
                load();self.refresh();self.tree.yview_moveto(0)
                self.note.set('项目清单已更新，新加入项目显示在顶部最近加入框。')
        except (OSError,ValueError) as e:self.note.set('等待项目清单更新完成：'+str(e))
        self.after(1800,self.poll_projects)
    def refresh(self):
        self.hide_tooltip()
        for widget in [*self.project_buttons.values(),*self.copy_buttons.values(),*self.delete_buttons.values(),*[line for lines in self.group_lines.values() for line in lines]]:widget.destroy()
        self.project_buttons={};self.pin_buttons={};self.delete_buttons={};self.copy_buttons={};self.group_lines={};self.group_members={};self.item_projects={};self.item_depth={};self.main_sessions={};self.project_nodes={};self.group_titles={}
        self.sync_registration();self.rows=self.sort_projects(lookup(self.query.get()));self.tree.delete(*self.tree.get_children())
        self.newest_id=self.view_state['registration_order'][-1] if self.view_state['registration_order'] else None
        _,self.relationships,_=hierarchy(PROJECTS)
        recent=sorted(self.rows,key=lambda p:self.registration_order[p['id']],reverse=True)
        count=len(recent) if self.recent_count.get()=='全部' else int(self.recent_count.get())
        recent=recent[:count] if self.show_recent.get() else []
        pinned=sorted((p for p in self.rows if p.get('pinned_at')),key=lambda p:p['pinned_at'],reverse=True)
        if recent:
            group=self.add_group('recent','最近加入 · '+str(len(recent))+' 项'+('（快捷）' if self.group_mode.get()!='加入顺序' else ''), '#3979df')
            for p in recent:self.add_project(group,p)
        if pinned:
            group=self.add_group('pinned','已置顶 · '+str(len(pinned))+' 项','#a36500')
            for p in pinned:self.add_project(group,p)
        mode=self.group_mode.get()
        if mode=='加入顺序':
            shortcuts={p['id'] for p in recent+pinned};remaining=[p for p in self.rows if p['id'] not in shortcuts]
            if remaining:
                group=self.add_group('all','其他项目 · '+str(len(remaining))+' 项','#71829a')
                for p in remaining:self.add_project(group,p)
        elif mode in ('按主机','按项目性质'):
            groups={}
            for p in self.rows:
                label=' / '.join(project_hosts(p)) if mode=='按主机' else p.get('category') or '性质待分类'
                groups.setdefault(label,[]).append(p)
            # The group containing the most recently registered project appears first.
            ranked=self.sort_projects(self.rows);ranks={p['id']:i for i,p in enumerate(ranked)}
            labels=sorted(groups,key=lambda label:min(ranks[p['id']] for p in groups[label]))
            for i,label in enumerate(labels):
                group=self.add_group('kind'+str(i),label+' · '+str(len(groups[label]))+' 项','#6b879f')
                for p in groups[label]:self.add_project(group,p)
        else:
            parents,relations,cycles=hierarchy(self.rows);self.relationships.update(relations)
            by_id={p['id']:p for p in self.rows};children={pid:[] for pid in by_id}
            for pid,parent in parents.items():children[parent].append(by_id[pid])
            roots=[p for p in self.rows if p['id'] not in parents]
            independent=[p for p in roots if not children[p['id']] and p['id'] not in cycles]
            def branch(parent_key,project,group):
                key=self.add_project(parent_key,project,group=group,open_children=bool(children[project['id']]))
                for child in self.sort_projects(children[project['id']]):branch(key,child,group)
                holder=key+':sessions'
                if self.tree.exists(holder):self.tree.move(holder,key,'end')
            for i,p in enumerate(roots):
                if p in independent:continue
                group=self.add_group('tree'+str(i),'主次树 · '+p['name'],'#527b70')
                branch(group,p,group)
            if independent:
                group=self.add_group('independent','独立项目 / 未登记主次关系 · '+str(len(independent))+' 项','#71829a')
                for p in independent:self.add_project(group,p)
        direction='从新到旧' if self.sort_mode.get().endswith('↓') else '从旧到新'
        hint='按登记先后展示；最近会话是历史索引时间' if self.sort_mode.get().startswith('加入顺序') else '组内按'+self.sort_mode.get().split()[0]+direction
        if recent and self.group_mode.get()!='加入顺序':hint+='；顶部最近加入为登记顺序的快捷入口'
        if self.group_mode.get()=='主次 / 依赖树':hint+='；子项目在上级下面缩进'
        self.view_hint.set(hint)
        self.save_view();self.data_stamp=DATA.stat().st_mtime_ns
        self.after_idle(self.position_project_buttons)
        self.status.set(f'{len(self.rows)} / {len(PROJECTS)} 个项目')
        if self.project_buttons:
            key=next(iter(self.project_buttons));self.tree.selection_set(key);self.tree.focus(key)
    def add_group(self,suffix,title,color):
        key='group:'+suffix;self.tree.insert('','end',iid=key,text=title,values=('',)*len(self.tree['columns']),tags=('group',),open=True)
        self.item_depth[key]=0;self.group_members[key]=[];self.group_titles[key]=title
        self.group_lines[key]=[tk.Frame(self.tree,bg=color,bd=0) for _ in range(4)]
        return key
    def add_project(self,parent,project,group=None,open_children=False):
        key='project:'+str(len(self.project_buttons));p=project
        group=group or parent;self.group_members[group].append(key);self.item_depth[key]=self.item_depth[parent]+1
        sessions=sorted(project_sessions(p),key=lambda session:session_timestamp(session.get('last_seen','')),reverse=True);latest=sessions[0] if sessions else None
        values={'joined':display_time(registered_time(p)) or '未记录 · #'+str(self.registration_order[p['id']]+1),'activity':display_time(activity_time(p)) or '未记录','latest':(display_time(latest.get('last_seen','')) or ('当前会话·未归档' if latest.get('source_type')=='current-session-reference' else '时间未记录')) if latest else '', 'summary':p.get('summary','待补充'),'host':' / '.join(project_hosts(p)),'category':p.get('category','待分类'),'relation':self.relationships.get(p['id'],''),'index':'1. '+latest.get('title','未命名会话') if latest else '暂无会话','session_id':latest['id'] if latest else '', 'sessions':len(describe(p)['session_ids']),'source':directory_column(p,True),'other':directory_column(p,False)}
        self.tree.insert(parent,'end',iid=key,text='',values=tuple(values[c] for c in self.tree['columns']),tags=('odd',) if len(self.project_buttons)%2 else (),open=open_children)
        self.item_projects[key]=p;self.project_nodes.setdefault(p['id'],[]).append(key)
        if latest:self.main_sessions[key]=latest
        # Sessions stay folded separately, so expanding a project hierarchy does not flood it with session rows.
        if sessions:
            holder=key+':sessions';self.tree.insert(key,'end',iid=holder,text='Codex 会话 · '+str(len(sessions))+' 条',open=False);self.item_depth[holder]=self.item_depth[key]+1;self.item_projects[holder]=p
            for j,session in enumerate(sessions,1):
                child=key+':session:'+str(j);self.main_sessions[child]=session;self.item_projects[child]=p
                v={'latest':display_time(session.get('last_seen','')),'index':str(j)+'. '+session.get('title','未命名会话'),'session_id':session['id']}
                self.tree.insert(holder,'end',iid=child,text='会话 '+str(j),values=tuple(v.get(c,'') for c in self.tree['columns']))
        cell=tk.Frame(self.tree,bg='white',bd=0,highlightthickness=0)
        pin=tk.Button(cell,text='★' if p.get('pinned_at') else '☆',width=2,font=('Segoe UI Symbol',12),fg='#a36500' if p.get('pinned_at') else '#7c8798',bg='white',activebackground='#dceaff',bd=0,highlightthickness=0,command=lambda p=p:self.toggle_pin(p));pin.pack(side='right',fill='y',padx=(2,2))
        name=tk.Button(cell,text=p['name'],anchor='w',font=('Microsoft YaHei UI',10),fg='#135ab7',bg='white',activebackground='#dceaff',bd=0,highlightthickness=0,padx=3,command=lambda p=p,key=key:self.click_project_name(p,key));name.pack(side='left',fill='both',expand=True)
        self.project_buttons[key]=cell;self.pin_buttons[key]=pin
        self.delete_buttons[key]=tk.Button(self.actions,text='删除',font=('Microsoft YaHei UI',9),fg='#b13a3a',bg='white',activebackground='#fff0f0',bd=0,highlightthickness=0,command=lambda p=p:self.remove(p))
        return key
    def position_project_buttons(self):
        if not self.tree.winfo_exists():return
        height=self.tree.winfo_height();width=self.tree.winfo_width()
        header=next((y for y in range(min(90,height)) if self.tree.identify_region(4,y)=='tree'),38)
        self.action_heading.place_configure(height=header);self.action_heading.lift()
        for key,cell in self.project_buttons.items():
            box=self.tree.bbox(key,'#0')
            if box:
                x,y,w,h=box;left=x+20+self.item_depth[key]*18;right=min(x+w-3,width-2)
                if x>=0 and right-left>=70 and y+h<=height:cell.place(x=left,y=y+2,width=right-left,height=h-4)
                else:cell.place_forget()
                if y+h<=height:self.delete_buttons[key].place(x=5,y=y+3,width=60,height=h-6)
                else:self.delete_buttons[key].place_forget()
            else:cell.place_forget();self.delete_buttons[key].place_forget()
        visible=set()
        for y in range(header,height,16):
            key=self.tree.identify_row(y)
            if key:visible.add(key)
        for key,button in self.copy_buttons.items():
            if key not in visible:button.place_forget()
        for key in visible:
            if key not in self.item_projects or key.endswith(':sessions'):continue
            box=self.tree.bbox(key,'session_id')
            if not box:continue
            x,y,w,h=box;left=x+w-57
            if left<0 or left+53>width or y+h>height:
                if key in self.copy_buttons:self.copy_buttons[key].place_forget()
                continue
            if key not in self.copy_buttons:self.copy_buttons[key]=ttk.Button(self.tree,text='全复制',width=5,command=lambda item=key:self.copy_row_project_ids(item))
            self.copy_buttons[key].place(x=left,y=y+4,width=53,height=max(1,h-8))
        def descendants(item):
            result=[]
            for child in self.tree.get_children(item):
                result.append(child)
                if self.tree.item(child,'open'):result.extend(descendants(child))
            return result
        for group,lines in self.group_lines.items():
            candidates=[group]+(descendants(group) if self.tree.item(group,'open') else [])
            boxes=[self.tree.bbox(key,'#0') for key in candidates];boxes=[box for box in boxes if box]
            if not boxes:
                for line in lines:line.place_forget()
                continue
            x,_,w,_=boxes[0]
            if x<0 or x+w>width:
                for line in lines:line.place_forget()
                continue
            top=max(header,min(box[1] for box in boxes));bottom=min(height-1,max(box[1]+box[3] for box in boxes))
            if bottom<=top:
                for line in lines:line.place_forget()
                continue
            for line,geometry in zip(lines,[(x+2,top,1,bottom-top),(x+w-2,top,1,bottom-top),(x+2,top,w-3,1),(x+2,bottom-1,w-3,1)]):
                px,py,pw,ph=geometry
                if not line.winfo_ismapped() or getattr(line,'last_box',None)!=geometry:
                    line.place(x=px,y=py,width=pw,height=ph);line.last_box=geometry
    def toggle_pin(self,project):
        with LOCK:
            actual=next((p for p in PROJECTS if p['id']==project['id']),None)
            if actual is None:return
            previous=actual.get('pinned_at')
            if previous:actual.pop('pinned_at',None)
            else:actual['pinned_at']=datetime.now(timezone.utc).isoformat()
            try:save()
            except Exception as e:
                if previous:actual['pinned_at']=previous
                else:actual.pop('pinned_at',None)
                messagebox.showerror('保存失败',str(e),parent=self);return
        self.refresh()
        keys=self.project_nodes.get(project['id'],[])
        if keys:self.tree.selection_set(keys[0]);self.tree.focus(keys[0]);self.tree.see(keys[0])
    def toggle_latest_sort(self):
        self.latest_desc=not self.latest_desc;self.sort_mode.set('最近会话 '+('↓' if self.latest_desc else '↑'));self.change_view()
    def set_groups_open(self,value):
        for group in self.group_lines:self.tree.item(group,open=value)
        self.after_idle(self.position_project_buttons)
    def sort_by_added(self):
        self.sort_mode.set('加入顺序 ↑' if self.sort_mode.get()=='加入顺序 ↓' else '加入顺序 ↓');self.change_view()
    def copy_row_project_ids(self,key):
        self.tree.selection_set(key);self.tree.focus(key);self.copy_project_ids()
    def copy_project_ids(self):
        project=self.current()
        if not project:return
        ids=describe(project)['session_ids']
        if not ids:self.note.set(project['name']+' 暂无会话 ID');return
        self.copy('\n'.join(ids));self.note.set('已复制 '+project['name']+' 的全部 '+str(len(ids))+' 个会话 ID（每行一个，已去重）')
    def on_summary_hover(self,event):
        key=self.tree.identify_row(event.y);column=self.tree.identify_column(event.x)
        cols=self.tree['columns'];index=int(column[1:])-1 if column.startswith('#') else -1
        if key not in self.project_buttons or index<0 or index>=len(cols) or cols[index]!='summary':
            self.defer_hide_tooltip();return
        if self.tooltip_hide_after:
            self.after_cancel(self.tooltip_hide_after);self.tooltip_hide_after=None
        if self.tooltip_key==key:return
        self.hide_tooltip();self.tooltip_key=key
        project=self.item_projects[key];self.tooltip_after=self.after(450,lambda:self.show_project_tooltip(project))
    def show_project_tooltip(self,project):
        self.tooltip_after=None
        if not self.winfo_exists():return
        tip=tk.Toplevel(self);self.tooltip=tip;tip.overrideredirect(True);tip.attributes('-topmost',True)
        tip.configure(bg='#fffef7',bd=0,highlightthickness=0)
        width=min(560,self.winfo_screenwidth()-40)
        label=tk.Label(tip,text=project.get('summary') or '待补充概述',wraplength=width-28,justify='left',anchor='w',font=('Microsoft YaHei UI',10),bg='#fffef7',fg='#26344a',bd=0,highlightthickness=0,padx=14,pady=10)
        label.pack(fill='both',expand=True);tip.update_idletasks()
        width=label.winfo_reqwidth();height=label.winfo_reqheight()
        x=min(self.winfo_pointerx()+18,self.winfo_screenwidth()-width-10);y=min(self.winfo_pointery()+20,self.winfo_screenheight()-height-10)
        tip.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        tip.bind('<Enter>',lambda _:self.cancel_hide_tooltip());tip.bind('<Leave>',lambda _:self.defer_hide_tooltip())
    def cancel_hide_tooltip(self):
        if self.tooltip_hide_after:self.after_cancel(self.tooltip_hide_after);self.tooltip_hide_after=None
    def defer_hide_tooltip(self):
        if self.tooltip_hide_after:return
        self.tooltip_hide_after=self.after(220,self.hide_tooltip_if_outside)
    def hide_tooltip_if_outside(self):
        self.tooltip_hide_after=None
        if self.tooltip and self.tooltip.winfo_exists():
            x,y=self.winfo_pointerxy();t=self.tooltip
            if t.winfo_rootx()<=x<t.winfo_rootx()+t.winfo_width() and t.winfo_rooty()<=y<t.winfo_rooty()+t.winfo_height():return
        self.hide_tooltip()
    def hide_tooltip(self):
        for name in ('tooltip_after','tooltip_hide_after'):
            value=getattr(self,name,None)
            if value:
                try:self.after_cancel(value)
                except tk.TclError:pass
            setattr(self,name,None)
        if getattr(self,'tooltip',None):
            try:self.tooltip.destroy()
            except tk.TclError:pass
        self.tooltip=None;self.tooltip_key=None
    def click_project_name(self,project,key):
        self.tree.selection_set(key);self.tree.focus(key)
        if self.last_project_click[0]==project['name'] and time.monotonic()-self.last_project_click[1]<2:return
        self.last_project_click=(project['name'],time.monotonic())
        try:
            result=HANDOFF.send(project);self.last_delivery=result['delivery_id'];self.handoff_state.set('正在发送：'+project['name'])
        except (ValueError,OSError) as e:
            self.handoff_state.set(str(e));messagebox.showinfo('发送项目',str(e),parent=self)
    def update_handoff_status(self):
        state=HANDOFF.status(self.last_delivery);delivery=state.get('delivery')
        if delivery:
            self.handoff_state.set(('云端已接收：' if delivery['status']=='delivered' else '等待云端接收：')+delivery['project']+'  ·  '+delivery['receiver_name'])
        elif state['connected']:self.handoff_state.set('云端已连接：'+', '.join(r['name'] for r in state['receivers'])+'  ·  点击项目名即可发送')
        else:self.handoff_state.set('尚无云端接收连接  ·  连接后点击项目名发送')
        self.after(1000,self.update_handoff_status)
    def main_double_click(self,event=None):
        selected=self.tree.selection()
        if selected:
            key=selected[0]
            if ':session:' in key:self.open_main_session()
            else:self.tree.item(key,open=not self.tree.item(key,'open'))
        return 'break'
    def main_session(self):
        selected=self.tree.selection();session=self.main_sessions.get(selected[0]) if selected else None
        if not session:messagebox.showinfo('项目会话','请选中有会话的项目行或其所属会话。',parent=self)
        return session
    def copy_main_session_id(self):
        session=self.main_session()
        if session:self.copy(session['id']);self.note.set('已复制会话 ID：'+session['id'])
    def open_main_session(self):
        session=self.main_session()
        if session:
            try:os.startfile(session['url'])
            except OSError as e:messagebox.showinfo('打开会话','请确认 Codex 已安装并拥有此会话。\n'+session['id']+'\n'+str(e),parent=self)
    def open_project(self):
        project=self.current()
        if not project:return
        if self.detail is not None and self.detail.winfo_exists():self.detail.destroy()
        self.detail_project=project
        self.detail=tk.Toplevel(self);self.detail.title(project['name']+' · 项目详情');self.detail.geometry('1130x660');self.detail.minsize(900,500);self.detail.transient(self)
        frame=ttk.Frame(self.detail,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=project['name'],font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w')
        ttk.Label(frame,text=project.get('summary','待补充项目概述'),wraplength=1080,font=('Microsoft YaHei UI',11)).pack(anchor='w',pady=(8,10))
        ttk.Label(frame,text='源码 / 脚本目录：'+directory_column(project,True)+'\n运行时 / 其他目录：'+directory_column(project,False),wraplength=1080,foreground='#63718a').pack(anchor='w')
        backup=usage_context()['session_backup']
        ttk.Label(frame,text='会话备份：'+backup['archive']+'\n'+backup['scope'],wraplength=1080,foreground='#63718a').pack(anchor='w',pady=(6,0))
        toolbar=ttk.Frame(frame);toolbar.pack(fill='x',pady=(18,8))
        ttk.Label(toolbar,text='这个项目的 Codex 会话',font=('Microsoft YaHei UI',12,'bold')).pack(side='left')
        ttk.Button(toolbar,text='完整资料 / 分支目录',command=self.open_full_project_info).pack(side='left',padx=(12,0))
        self.session_query=tk.StringVar()
        ttk.Entry(toolbar,textvariable=self.session_query,width=32).pack(side='right')
        ttk.Label(toolbar,text='在本项目内搜索标题 / ID  ').pack(side='right')
        grid=ttk.Frame(frame);grid.pack(fill='both',expand=True)
        self.session_tree=ttk.Treeview(grid,columns=('title','date','id','basis'),show='headings',selectmode='browse')
        for key,label,width in [('title','会话标题',330),('date','最后活动（上海时间）',165),('id','会话 ID',295),('basis','项目关联依据',230)]:
            self.session_tree.heading(key,text=label);self.session_tree.column(key,width=width,minwidth=80)
        vs=ttk.Scrollbar(grid,orient='vertical',command=self.session_tree.yview);hs=ttk.Scrollbar(grid,orient='horizontal',command=self.session_tree.xview)
        self.session_tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        self.session_tree.grid(row=0,column=0,sticky='nsew');vs.grid(row=0,column=1,sticky='ns');hs.grid(row=1,column=0,sticky='ew');grid.columnconfigure(0,weight=1);grid.rowconfigure(0,weight=1)
        self.session_tree.bind('<<TreeviewSelect>>',self.selected_session);self.session_tree.bind('<Double-1>',lambda _:self.open_session())
        self.session_info=tk.StringVar()
        ttk.Label(frame,textvariable=self.session_info,wraplength=1070,foreground='#63718a').pack(anchor='w',pady=10)
        actions=ttk.Frame(frame);actions.pack(fill='x')
        for label,fn in [('在 Codex 打开',self.open_session),('复制会话 ID',self.copy_session_id),('复制备份位置',self.copy_session_location)]:ttk.Button(actions,text=label,command=fn).pack(side='left',padx=(0,8))
        self.session_count=tk.StringVar();ttk.Label(actions,textvariable=self.session_count).pack(side='right')
        self.session_query.trace_add('write',lambda *_:self.refresh_sessions())
        self.refresh_sessions()
    def open_full_project_info(self):
        project=getattr(self,'detail_project',None) or self.current()
        if not project:return
        content=full_project_info(project)
        win=tk.Toplevel(self);win.title(project['name']+' · 完整资料 / 分支目录');win.geometry('1000x650');win.transient(self)
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=(0,10))
        ttk.Label(bar,text='完整资料 · 源码 / 运行时版本与目录',font=('Microsoft YaHei UI',12,'bold')).pack(side='left')
        ttk.Button(bar,text='复制完整资料',command=lambda:self.copy(content)).pack(side='right')
        area=ttk.Frame(frame);area.pack(fill='both',expand=True)
        text=tk.Text(area,wrap='word',font=('Microsoft YaHei UI',10),background='white',foreground='#25324a',relief='flat',padx=12,pady=10)
        scroll=ttk.Scrollbar(area,orient='vertical',command=text.yview);text.configure(yscrollcommand=scroll.set)
        text.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        text.insert('1.0',content);text.configure(state='disabled')
    def refresh_sessions(self):
        if self.session_tree is None or not self.session_tree.winfo_exists():return
        project=self.detail_project
        self.session_rows=session_search(self.session_query.get(),project)
        self.session_tree.delete(*self.session_tree.get_children())
        for i,x in enumerate(self.session_rows):
            basis=' / '.join(next((p['evidence'] for p in x.get('projects',[]) if p['name']==project['name']),[]))
            self.session_tree.insert('','end',iid=str(i),values=(x.get('title','未命名会话'),display_time(x.get('last_seen','')),x['id'],basis))
        self.session_count.set(f'{len(self.session_rows)} / {len(project_sessions(project))} 个本项目会话')
        self.session_info.set('选中会话查看备份位置；双击尝试在 Codex 打开。' if self.session_rows else '这个项目暂无匹配的会话记录。')
    def selected_session(self,_=None):
        sel=self.session_tree.selection()
        if sel:
            x=self.session_rows[int(sel[0])]
            self.session_info.set(x['archive']+'  →  '+x['archive_members'][0]+('（另有分段）' if len(x['archive_members'])>1 else ''))
    def current_session(self):
        sel=self.session_tree.selection()
        if sel:return self.session_rows[int(sel[0])]
        messagebox.showinfo('会话索引','请先选中一个会话。',parent=self)
    def open_session(self):
        x=self.current_session()
        if x:
            try:os.startfile(x['url'])
            except OSError as e:messagebox.showinfo('打开会话','请确认本机已安装 Codex，并且已导入该会话。\n会话 ID：'+x['id']+'\n'+str(e),parent=self)
    def copy_session_id(self):
        x=self.current_session()
        if x:self.copy(x['id'])
    def copy_session_location(self):
        x=self.current_session()
        if x:self.copy(x['archive']+'\n'+'\n'.join(x['archive_members']))
    def current(self):
        s=self.tree.selection()
        if s and s[0] in self.item_projects:return self.item_projects[s[0]]
        messagebox.showinfo('项目管理器','请先选中一个项目。',parent=self)
    def selected(self,_=None):
        selected=self.tree.selection()
        if selected and selected[0] in self.item_projects:
            p=self.item_projects[selected[0]];session=self.main_sessions.get(selected[0]);self.note.set(('会话：'+session.get('title','未命名会话')+'    ID：'+session['id']+'    ' if session else '')+'目录：'+(p['path'] or '待确认')+'    会话备份：'+(session.get('archive','') if session else usage_context()['session_backup']['archive']))

    def copy(self,text):self.clipboard_clear();self.clipboard_append(text)
    def copy_path(self):
        p=self.current()
        if p:self.copy(p['path']);self.note.set('已复制：'+p['path'])
    def copy_api(self):
        s=self.tree.selection();name=self.item_projects[s[0]]['name'] if s and s[0] in self.item_projects else ''
        self.copy(f'http://127.0.0.1:{PORT}/api/lookup?name='+quote(name));self.note.set('已复制查询接口地址。')
    def open_folder(self):
        p=self.current()
        if p:
            if not p['path']:messagebox.showinfo('项目目录待确认','尚未核实此项目目录；可在编辑项目中补充。',parent=self)
            elif os.path.isdir(p['path']):os.startfile(p['path'])
            else:messagebox.showinfo('目录暂不可用','当前电脑未找到该历史或远端路径：\n\n'+p['path'],parent=self)
    def reload(self):
        try:load();self.refresh()
        except Exception as e:messagebox.showerror('载入失败',str(e),parent=self)
    def edit(self):
        p=self.current()
        if p:self.editor(p)
    def editor(self,old=None):
        win=tk.Toplevel(self);win.title('编辑项目' if old else '新增项目');win.geometry(f'920x{min(740,self.winfo_screenheight()-100)}');win.transient(self);win.grab_set()
        frame=ttk.Frame(win,padding=20);frame.pack(fill='both',expand=True);frame.columnconfigure(1,weight=1);fields={}
        for row,(key,title) in enumerate([('name','项目名称'),('summary','一句话概述'),('path','主目录路径（未确认可留空）'),('source_paths','源码目录（分号分隔）'),('runtime_paths','运行时目录（分号分隔）'),('aliases','别名（分号分隔）'),('category','项目性质'),('hosts','所属主机（分号分隔）'),('primary_project','上级项目（名称，可留空）'),('depends_on','依赖项目（名称，分号分隔）'),('notes','说明')]):
            value=(old or {}).get(key,'')
            if key=='hosts':value=';'.join(project_hosts(old)) if old else ''
            elif key=='primary_project':
                refs=project_refs(value or (old or {}).get('parent_project'));value=next((p['name'] for p in PROJECTS if refs and p['id']==refs[0]),refs[0] if refs else '')
            elif key=='depends_on':
                refs=project_refs(value);value=';'.join(next((p['name'] for p in PROJECTS if p['id']==r),r) for r in refs)
            elif isinstance(value,list):value=';'.join(str(x) for x in value)
            fields[key]=tk.StringVar(value=value);ttk.Label(frame,text=title).grid(row=row,column=0,sticky='w',pady=8)
            ttk.Entry(frame,textvariable=fields[key]).grid(row=row,column=1,sticky='ew',padx=(12,0),ipady=4)
        def commit():
            item={**(old or {}),**{k:v.get().strip() for k,v in fields.items()}}
            if not item['name']:messagebox.showwarning('信息不完整','请填写项目名称。',parent=win);return
            item['hosts']=[h.strip() for h in item['hosts'].replace('；',';').split(';') if h.strip() and h.strip()!='主机待确认']
            refs={p['name'].casefold():p['id'] for p in PROJECTS};refs.update({p['id']:p['id'] for p in PROJECTS})
            item['depends_on']=project_refs(item['depends_on'])
            requested=project_refs(item['primary_project'])+item['depends_on']
            if any(r.casefold() not in refs for r in requested):
                messagebox.showwarning('项目关系','请填写已登记的项目名称或 ID。',parent=win);return
            if any(refs[r.casefold()]==item.get('id') for r in requested):
                messagebox.showwarning('项目关系','项目不能以上级或依赖关系指向自身。',parent=win);return
            item['primary_project']=refs[item['primary_project'].casefold()] if item['primary_project'] else ''
            item['depends_on']=[refs[r.casefold()] for r in item['depends_on']]
            previous_parent=project_refs((old or {}).get('parent_project'))
            if previous_parent and item['primary_project'] in previous_parent:item['primary_project']=''
            elif previous_parent:item.pop('parent_project',None)
            item['path_status']='registered' if item['path'] else 'unconfirmed'
            for field in ('source_paths','runtime_paths'):
                item[field]=[v.strip() for v in item[field].replace('；',';').split(';') if v.strip()]
            item['primary_source_path']=item['source_paths'][0] if item['source_paths'] else None
            if not old or (item['source_paths']!=old.get('source_paths',[]) or item['runtime_paths']!=old.get('runtime_paths',[])):
                item['directories']=[r for r in (old or {}).get('directories',[]) if r['kind'] not in ('源码','运行/发布包','运行/依赖')]
                item['directories'] += [{'path':v,'kind':kind,'exists':os.path.isdir(v),'verified':False,'evidence':'手动修改，尚未核实目录角色'} for field,kind in [('source_paths','源码'),('runtime_paths','运行/发布包')] for v in item[field]]
                item['non_source_paths']=[{'path':r['path'],'kind':r['kind']} for r in item['directories'] if r['kind']!='源码']
            if not old:item['added_at']=datetime.now(timezone.utc).isoformat()
            item.setdefault('id',str(uuid.uuid4()));item['aliases']=[s.strip() for s in item['aliases'].replace('；',';').split(';') if s.strip()];item['evidence']=(old or {}).get('evidence','手动录入');item['exists_here']=os.path.isdir(item['path'])
            with LOCK:
                snapshot=PROJECTS.copy()
                if old:PROJECTS[next(i for i,p in enumerate(PROJECTS) if p['id']==old['id'])]=item
                else:PROJECTS.append(item)
                try:save()
                except Exception as e:PROJECTS[:]=snapshot;messagebox.showerror('保存失败',str(e),parent=win);return
            win.destroy();self.refresh()
        ttk.Button(frame,text='保存',command=commit).grid(row=12,column=1,sticky='e',pady=16)
    def remove(self,project=None):
        p=project if project is not None else self.current()
        if p and messagebox.askyesno('删除条目',f'从清单移除“{p["name"]}”？\n文件夹内容不会被删除。',parent=self):
            with LOCK:
                index=next(i for i,item in enumerate(PROJECTS) if item['id']==p['id']);PROJECTS.pop(index)
                try:save()
                except Exception as e:PROJECTS.insert(index,p);messagebox.showerror('保存失败',str(e),parent=self);return
            self.refresh()
    def close(self):self.hide_tooltip();self.server.shutdown();self.destroy()

def display_time(value):
    if not value:return ''
    try:
        from datetime import datetime,timezone,timedelta
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if len(value)==10:return parsed.strftime('%Y-%m-%d')
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone(timedelta(hours=8)))
        return parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    except ValueError:return value[:16]

def main():
    try:server=ThreadingHTTPServer(('127.0.0.1',PORT),API)
    except OSError:
        root=tk.Tk();root.withdraw();messagebox.showinfo('项目管理器',f'端口 {PORT} 已被占用。若管理器已打开，请使用现有窗口。');root.destroy();return
    try:
        load();threading.Thread(target=server.serve_forever,daemon=True).start();App(server).mainloop()
    finally:server.server_close()
if __name__=='__main__':main()
