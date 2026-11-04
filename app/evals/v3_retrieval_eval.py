"""Real offline embeddings over synthetic labelled retrieval cases; not field evidence."""
import json
from pathlib import Path
from factory_v3.service import FactoryService
from cim.records import uid
from cim.registry import digest

CASES=[
 ('负载缩放','合成点表：D100 为电机负载，原始数值乘以 0.1 后得到百分比。','电机负载原始值如何换算为百分比'),
 ('温度符号','合成点表：D200 为有符号温度，负温度不能作为无符号数解释。','温度数据出现极大正数应检查什么类型'),
 ('数据有效','合成接口：M500 是本周期数据有效位，未置位时接收侧不得使用该周期测量值。','采样值是否可以使用由哪个有效信号决定'),
 ('采样周期','合成接口：负载上报采样间隔为 500 毫秒，此数值仅作评测假设。','合成案例中负载多久采集一次'),
 ('序号去重','合成接口：同一消息序号重复到达时只记录一条，不重复累计。','重发消息重复计数如何处理'),
 ('超时恢复','合成握手：请求发出后超过约定时间未收到 ACK，进入超时故障并等待复位。','对端一直不应答握手应该走哪个异常路径'),
 ('上下报分离','合成设计：通讯上报缓存与 PLC 控制输出分开，不允许接收侧直接改写执行输出。','上报数据区为什么不能直接驱动机构输出'),
 ('时区口径','合成日志：所有时间戳统一为 Asia/Shanghai，并同时保留原始时区。','两份日志时间对不上先统一什么'),
 ('并行设备','合成 TT：两台并行设备分别统计处理时间，不能把重叠运行时间直接相加。','并行机台的重叠时间怎样避免重复计算'),
 ('计划停机','合成口径：计划停机从可生产窗口中单列，改善前后必须使用相同规则。','改善前后的计划停机扣除口径如何保持可比'),
 ('玻璃去重','合成日志：以玻璃 ID 和工序组合去重，同一玻璃重试不视为新产出。','同一片玻璃反复进站如何防止产量虚高'),
 ('末站产出','合成 TT：完成数量以指定末站完成事件计，不以首站开始数量替代。','产线最终产量应读取首站还是末站事件'),
 ('缺结束事件','合成质量检查：有开始没有结束的动作属于不完整事件，不能补造结束时间。','日志动作只有开始没有结束应怎样处理'),
 ('缓存满载','合成搬送：下游缓存满时记录 blocking，不将其直接归因于本机动作慢。','下游放不进去造成的等待属于哪种损失'),
 ('上游缺料','合成搬送：等待上游供料属于 starvation，与下游堵塞分开。','设备空闲等待来料和下游堵塞如何区分'),
 ('配方比较','合成效果对照：比较 TT 时固定产品和配方，不混合不同工艺条件。','产能改善比较为什么要锁定产品配方'),
 ('功率保持','合成程序审查：掉电保持寄存器须明确上电状态，不能默认断电自动清零。','重启后状态还在应检查哪类寄存器'),
 ('输出多写','合成 PLC 审查：同一扫描多个程序写同一输出时检查最后写入及所有权冲突。','一个输出在多处线圈写入有什么扫描风险'),
 ('边沿触发','合成 PLC：上升沿只在信号由零变一时触发，保持高电平不应每周期重复。','信号一直为高为什么不该连续触发上升沿动作'),
 ('复位清理','合成恢复：故障复位必须清理临时动作请求并重新确认机构和物料状态。','按下故障复位前后要核对哪些动作残留'),
 ('暂停恢复','合成顺控：暂停后恢复需要重新检查当前联锁，不能盲目继续下一动作。','暂停恢复时为什么还要重查联锁'),
 ('真空确认','合成约束：真空吸附到位与玻璃存在共同作为搬送前提，不能单看定时结束。','吸附搬送启动前应确认哪些反馈'),
 ('配方一致','合成工艺：PLC 当前执行配方号与上位机要求配方号应一致，否则列为待确认。','设备实际执行配方与上位要求不一致怎么检查'),
 ('工艺窗口','合成工艺：烘烤停留时间的上下界来自确认的工艺窗口，不能仅为缩短 TT 改小。','为了提速能否随意缩短烘烤停留时间'),
 ('品质守护','合成收益：TT 降低同时检查不良率和故障频次，不能只看速度。','提速方案还必须对照哪些质量与可靠性指标'),
 ('电气余量','合成改造：新增电磁阀须核对输出通道、供电容量和接线图变更。','加一个电磁阀需要核对哪些电气条件'),
 ('回退基线','合成发布：回退包绑定原工程版本、来源哈希和恢复步骤。','改造失败时回退包必须包含什么版本依据'),
 ('证据区别','合成验证：静态 CSV 对照只证明源码差异，不代表 GX 编译成功。','CSV 静态检查通过能证明工程已编译吗'),
 ('现场区分','合成验证：模拟测试与真实现场行为分别记录，模拟通过不能代替现场验收。','模拟成功是否可以直接算现场验收通过'),
 ('范围排除','合成范围：历史未改通道原因未知时保留排除项，不自动扩大改造范围。','历史有几个通道没改能否自动补改')]

def main():
    root=Path(__file__).resolve().parents[2]
    s=FactoryService(root/'.qa/retrieval-eval'/uid())
    cfg=s.knowledge.configure(str(root/'.embedding-venv/Scripts/python.exe'),str(root/'.models/bge-small-zh-v1.5'))
    p=s.create_project('合成检索评测',cpu='Q26UDV',equipment='synthetic-LUL',classification='public',requirements='仅检索评测')
    module=s.detail(p['id'])['modules'][0]
    texts=[text for _,text,_ in CASES]+[query for _,_,query in CASES]
    vectors=s.knowledge.encode(texts,cfg)
    ids=[]
    with s.connect(True) as db:
        for i,(title,text,query) in enumerate(CASES):
            kid=uid();ids.append(kid)
            k={'id':kid,'project_id':p['id'],'module_id':module['id'],'module_version':module['version'],'deliverable_id':'synthetic-fixture',
               'title':title,'cpu':p['cpu'],'area':p['area'],'equipment':p['equipment'],'classification':'public','sources':[],'knowledge_ids':[],
               'status':'accepted','accepted_by':'synthetic-fixture','verification':[],'chunks':[{'location':'line:1','text':text}],
               'sha256':digest(text),'index_status':'semantic','vectors':[vectors[i]],'embedding_fingerprint':cfg['fingerprint'],'synthetic':True}
            s._put(db,'knowledge',k)
    # Reuse the ACTUAL embeddings computed above, without loading the model 30 more times.
    query_vectors={query:vectors[len(CASES)+i] for i,(_,_,query) in enumerate(CASES)}
    s.knowledge.encode=lambda queries,cfg=None:[query_vectors[q] for q in queries]
    results=[]
    for i,(title,text,query) in enumerate(CASES):
        hits=s.knowledge.search(p['id'],query)['hits'];rank=next((j+1 for j,h in enumerate(hits) if h['knowledge_id']==ids[i]),None)
        results.append({'case':title,'rank':rank,'top5':rank is not None and rank<=5})
    report={'synthetic':True,'actual_local_embedding':True,'cases':len(CASES),'recall_at_5':sum(r['top5'] for r in results)/len(results),'model_fingerprint':cfg['fingerprint'],'results':results,'field_validation':False}
    output=root/'app/.qa/v3-retrieval-results.json';output.parent.mkdir(exist_ok=True,parents=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=True))
    if report['recall_at_5']<.8: raise SystemExit(1)
if __name__=='__main__':main()
