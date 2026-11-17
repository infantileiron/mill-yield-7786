import hashlib,json
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Batch,Inspection,OfflinePackage
from src.utils.serialize import record
BATCH_FIELDS=('line','supplier','tonnes','received_date')
INSP_FIELDS=('flour_yield','moisture','inspector','batch_code')
FLOATS=('tonnes','flour_yield','moisture')
def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def package_key(site,baseline,payload):return hashlib.sha256(canonical({'site':site,'baseline':baseline,'payload':payload}).encode()).hexdigest()
def _eq(f,x,y):return abs(float(x)-float(y))<=1e-9 if f in FLOATS else str(x)==str(y)
def same_content(a,b,fields):return all(_eq(f,a.get(f),b.get(f)) for f in fields)
def diff_fields(a,b,fields):return [f for f in fields if not _eq(f,a.get(f),b.get(f))]
def export_baseline(db):
    batches=[{k:b[k] for k in ('code','line','supplier','tonnes','received_date')} for b in (record(x) for x in db.scalars(select(Batch).order_by(Batch.id)))]
    insps=[]
    for i,code in db.execute(select(Inspection,Batch.code).join(Batch,Batch.id==Inspection.batch_id).order_by(Inspection.id)):
        r=record(i);insps.append({k:r[k] for k in ('sample_code','flour_yield','moisture','inspector')}|{'batch_code':code})
    digest=hashlib.sha256(canonical({'batches':batches,'inspections':insps}).encode()).hexdigest()
    now=datetime.now(timezone.utc)
    return {'format':'mill-offline-package/1','baseline':f"BL-{now:%Y%m%d}-{digest[:12]}",'exported_at':now.isoformat(),'site':'','baseline_batches':batches,'baseline_inspections':insps,'added_batches':[],'added_inspections':[]}
def _dedupe(rows,key,fields,label):
    seen={}
    for r in rows:
        d=r.model_dump();k=d[key]
        if k in seen:
            if not same_content(seen[k],d,fields):raise HTTPException(422,f'工作包内同一{label}编号 {k} 存在不同内容，请先在分厂副本内核对')
            continue
        seen[k]=d
    return list(seen.values())
def normalize_payload(db,data):
    batches=_dedupe(data.added_batches,'code',BATCH_FIELDS,'批次')
    inspections=_dedupe(data.added_inspections,'sample_code',INSP_FIELDS,'检验')
    if not batches and not inspections:raise HTTPException(422,'工作包内没有新增批次或检验记录')
    known={b['code'] for b in batches}|{c for (c,) in db.execute(select(Batch.code))}
    missing=sorted({i['batch_code'] for i in inspections}-known)
    if missing:raise HTTPException(422,'检验记录指向不存在的批次编号：'+'、'.join(missing))
    return {'batches':batches,'inspections':inspections}
def compute_plan(db,payload,resolutions):
    resolutions=resolutions or {}
    online_b={b.code:record(b) for b in db.scalars(select(Batch))}
    online_i={}
    for i,code in db.execute(select(Inspection,Batch.code).join(Batch,Batch.id==Inspection.batch_id)):
        online_i[i.sample_code]={**record(i),'batch_code':code}
    batches=[];final_code={};taken=set(online_b)
    for b in payload['batches']:
        code=b['code'];res=resolutions.get('batch:'+code)
        item={'code':code,'content':b,'action':None,'rename_from':None,'online':online_b.get(code),'diff':[],'reason':None}
        if res and res['action']=='use_online':
            if code in online_b:item['action']='use_online'
            else:item.update(action='conflict',reason='裁定以在线为准，但在线已不存在该编号')
        elif res and res['action']=='rename':
            new=res.get('new_code')
            if not new or new in taken:item.update(action='conflict',reason=f'改号目标 {new or "（空）"} 已被占用，请换一个编号')
            else:item.update(action='add',code=new,rename_from=code);taken.add(new)
        elif code in online_b:
            if same_content(b,online_b[code],BATCH_FIELDS):item['action']='duplicate'
            else:item.update(action='conflict',diff=diff_fields(b,online_b[code],BATCH_FIELDS))
        elif code in taken:item.update(action='conflict',reason='编号与同包改号目标冲突，请调整')
        else:item['action']='add';taken.add(code)
        batches.append(item);final_code[code]=item['code']
    inspections=[];taken_i=set(online_i)
    for s in payload['inspections']:
        sc=s['sample_code'];eff_batch=final_code.get(s['batch_code'],s['batch_code'])
        res=resolutions.get('inspection:'+sc)
        item={'code':sc,'batch_code':eff_batch,'content':s,'action':None,'rename_from':None,'online':online_i.get(sc),'diff':[],'reason':None}
        if res and res['action']=='use_online':
            if sc in online_i:item['action']='use_online'
            else:item.update(action='conflict',reason='裁定以在线为准，但在线已不存在该编号')
        elif res and res['action']=='rename':
            new=res.get('new_code')
            if not new or new in taken_i:item.update(action='conflict',reason=f'改号目标 {new or "（空）"} 已被占用，请换一个编号')
            else:item.update(action='add',code=new,rename_from=sc);taken_i.add(new)
        elif sc in online_i:
            cmp={k:s[k] for k in INSP_FIELDS}|{'batch_code':eff_batch}
            ref={k:online_i[sc][k] for k in INSP_FIELDS}
            if same_content(cmp,ref,INSP_FIELDS):item['action']='duplicate'
            else:item.update(action='conflict',diff=diff_fields(cmp,ref,INSP_FIELDS))
        elif sc in taken_i:item.update(action='conflict',reason='编号与同包改号目标冲突，请调整')
        else:item['action']='add';taken_i.add(sc)
        inspections.append(item)
    conflicts=[{'type':kind,'code':it['content']['code' if kind=='batch' else 'sample_code'],'offline':it['content'],'online':it['online'],'diff':it['diff'],'reason':it['reason'] or '同号异内容'} for kind,items in (('batch',batches),('inspection',inspections)) for it in items if it['action']=='conflict']
    count=lambda items,*acts:sum(1 for x in items if x['action'] in acts)
    summary={'batches_add':count(batches,'add'),'batches_merged':count(batches,'duplicate','use_online'),'inspections_add':count(inspections,'add'),'inspections_merged':count(inspections,'duplicate','use_online'),'conflicts':len(conflicts)}
    return {'computed_at':datetime.now(timezone.utc).isoformat(),'batches':batches,'inspections':inspections,'conflicts':conflicts,'summary':summary}
def apply_plan(db,plan):
    ids={b.code:b.id for b in db.scalars(select(Batch))}
    res={'batches_added':0,'inspections_added':0,'batches_merged':0,'inspections_merged':0,'renames':[]}
    for b in plan['batches']:
        c=b['content']
        if b['action']=='add':
            obj=Batch(code=b['code'],line=c['line'],supplier=c['supplier'],tonnes=c['tonnes'],received_date=c['received_date'])
            db.add(obj);db.flush();ids[b['code']]=obj.id;res['batches_added']+=1
            if b['rename_from']:res['renames'].append({'type':'batch','from':b['rename_from'],'to':b['code']})
        else:res['batches_merged']+=1
    for i in plan['inspections']:
        c=i['content']
        if i['action']=='add':
            db.add(Inspection(sample_code=i['code'],batch_id=ids[i['batch_code']],flour_yield=c['flour_yield'],moisture=c['moisture'],inspector=c['inspector']));db.flush()
            res['inspections_added']+=1
            if i['rename_from']:res['renames'].append({'type':'inspection','from':i['rename_from'],'to':i['code']})
        else:res['inspections_merged']+=1
    res['batches_total']=len(plan['batches']);res['inspections_total']=len(plan['inspections'])
    return res
def attempt_accept(db,pkg_id):
    pkg=db.scalar(select(OfflinePackage).where(OfflinePackage.id==pkg_id).with_for_update())
    if not pkg:raise HTTPException(404,'工作包不存在')
    if pkg.status=='accepted':return pkg
    for _ in range(2):
        plan=compute_plan(db,pkg.payload,pkg.resolutions)
        pkg.plan=plan
        if plan['conflicts']:
            pkg.status='pending';pkg.note='存在未裁定的编号冲突，整包暂不进入台账';db.commit();return pkg
        try:
            result=apply_plan(db,plan)
            pkg.status='accepted';pkg.result={**result,'accepted_at':datetime.now(timezone.utc).isoformat()};pkg.accepted_at=datetime.now(timezone.utc);pkg.note=''
            db.commit();return pkg
        except IntegrityError:
            db.rollback();pkg=db.get(OfflinePackage,pkg_id)
    pkg.status='pending';pkg.note='接纳时与在线新增写入冲突，包内容已保留，请重试'
    db.commit();return pkg
def upload(db,data,user):
    payload=normalize_payload(db,data)
    key=package_key(data.site,data.baseline,payload)
    existing=db.scalar(select(OfflinePackage).where(OfflinePackage.package_key==key))
    if existing:return existing,False
    pkg=OfflinePackage(package_key=key,site=data.site,baseline=data.baseline,payload=payload,created_by=user.email)
    db.add(pkg)
    try:db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(OfflinePackage).where(OfflinePackage.package_key==key)),False
    return attempt_accept(db,pkg.id),True
def resolve(db,pkg_id,data):
    pkg=db.get(OfflinePackage,pkg_id)
    if not pkg:raise HTTPException(404,'工作包不存在')
    if pkg.status=='accepted':raise HTTPException(409,'工作包已接纳，无需再裁定')
    current={c['type']+':'+c['code'] for c in (pkg.plan or {}).get('conflicts',[])}
    if not data.resolutions and current:raise HTTPException(422,'请先对本包冲突作出裁定')
    merged=dict(pkg.resolutions or {})
    for r in data.resolutions:
        key=r.type+':'+r.code
        if key not in current:raise HTTPException(422,f'编号 {r.code} 当前没有待裁定的冲突')
        if r.action=='rename' and not r.new_code:raise HTTPException(422,f'编号 {r.code} 选择改号入库时必须提供新编号')
        merged[key]={'action':r.action,'new_code':r.new_code}
    pkg.resolutions=merged;db.commit()
    return attempt_accept(db,pkg_id)
def packages(db):
    out=[]
    for p in db.scalars(select(OfflinePackage).order_by(OfflinePackage.id.desc())):
        d=record(p);d['summary']=(p.plan or {}).get('summary') or {}
        for k in ('payload','plan','resolutions'):d.pop(k,None)
        out.append(d)
    return out
