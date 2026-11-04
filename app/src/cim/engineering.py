"""Read adapters reuse GXWorks services; never rewrite source CSV or native files."""
from __future__ import annotations
import csv
import difflib
import hashlib
import io
import tempfile
from pathlib import Path
from .documents import decode


def csv_compare(before,after):
    from gxworks2.csv_importer import diff_gxworks2_programs
    from gxworks2.csv_manager import CSVManager
    def records(raw):
        rows=list(csv.reader(io.StringIO(decode(raw)),delimiter="\t"))
        header=next((i for i,r in enumerate(rows) if "步号" in r and "指令" in r),None)
        if header is None:
            raise ValueError("不是已识别的 GX Works2 TAB CSV")
        return rows,header
    left,lh=records(before)
    right,rh=records(after)
    if left[lh]!=right[rh]:
        raise ValueError("两个文件的列定义不同")
    # Preserve all non-step columns, including comments and declarations, in the detailed diff.
    def normalized(rows,h):
        return [tuple(r[1:]) for r in rows[h+1:]]
    a,b=normalized(left,lh),normalized(right,rh)
    changes=[]
    for tag,i,j,k,l in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes():
        if tag!="equal":
            changes.append({"kind":tag,"before_rows":[lh+i+2,lh+j+1],"after_rows":[rh+k+2,rh+l+1],
                            "before":a[i:min(j,i+5)],"after":b[k:min(l,k+5)]})
    with tempfile.TemporaryDirectory(prefix="cim-csv-") as folder:
        x,y=Path(folder)/"before.csv",Path(folder)/"after.csv"
        x.write_bytes(before)
        y.write_bytes(after)
        manager=CSVManager()
        validations=[manager.validate(p) for p in [x,y]]
        result=diff_gxworks2_programs(x,y)
    return {"evidence_type":"static_source_comparison","upstream":result,
            "sha256_before":hashlib.sha256(before).hexdigest(),"sha256_after":hashlib.sha256(after).hexdigest(),
            "record_counts":[len(left),len(right)],"non_step_change_blocks":changes[:200],"diff_truncated":len(changes)>200,
            "format_valid":[v.valid for v in validations],"compile_verified":False,"runtime_verified":False,"field_verified":False,
            "known_scope_question":"PHL10 历史 R11540/R11544/R11548 未改原因未知；不能自动判为漏改",
            "notes":["步号差异与逻辑/声明/注释差异分开；输入字节未写回","上游按序号差异摘要可能因插入产生后续位移，以块级对照辅助审查"]}


def inspect_csv(raw, cpu="Q26UDV",comment_raw=None):
    from gxworks2.csv_importer import inspect_gxworks2_csv
    with tempfile.TemporaryDirectory(prefix="cim-inspect-") as folder:
        path=Path(folder)/"source.csv"
        path.write_bytes(raw)
        comments=Path(folder)/"COMMENT.csv"
        comments.write_bytes(comment_raw if comment_raw is not None else "COMMENT - unavailable\r\n软元件名\t注释\r\n".encode("utf-16"))
        result=inspect_gxworks2_csv(path,comments,plc_model=cpu)
        result["factory_notes"]={"device_comments_provided":comment_raw is not None,
                                  "warning":None if comment_raw is not None else "未提供软元件注释 CSV；不能推定地址业务含义"}
        return result
