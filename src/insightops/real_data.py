"""Read-only extraction of UCI's workbook; outputs SQLite and aggregate evidence.

Can run standalone with the bundled spreadsheet Python runtime:
python src/insightops/real_data.py --download
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import sqlite3
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCALE = 1_000_000  # Preserve sub-penny unit prices; round only for presentation.


def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def fetch(root=ROOT):
    metadata=json.loads((root/"data/sources/uci-online-retail.json").read_text(encoding="utf-8"))
    folder=root/"data/raw/uci-online-retail"
    folder.mkdir(parents=True,exist_ok=True)
    archive=folder/"online-retail.zip"
    if not archive.exists():
        partial=archive.with_suffix(".part")
        try:
            with urllib.request.urlopen(metadata["download_url"],timeout=60) as source, partial.open("wb") as target:
                size=0
                while chunk:=source.read(1024*1024):
                    size+=len(chunk)
                    if size>100*1024*1024:
                        raise ValueError("Unexpected download size (>100 MiB)")
                    target.write(chunk)
            partial.replace(archive)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    fingerprint=sha256(archive)
    if metadata.get("archive_sha256") and metadata["archive_sha256"]!=fingerprint:
        raise ValueError("UCI archive fingerprint changed; review upstream data before proceeding")
    workbook=folder/"Online Retail.xlsx"
    with zipfile.ZipFile(archive) as zipped:
        names=[name for name in zipped.namelist() if Path(name).name==workbook.name]
        if len(names)!=1:
            raise ValueError("Expected exactly one Online Retail.xlsx archive member")
        # Extract named contents only, never arbitrary archive paths.
        with zipped.open(names[0]) as source,workbook.open("wb") as target:
            while chunk:=source.read(1024*1024):
                target.write(chunk)
    return workbook,metadata,fingerprint


def text(value):
    if value is None:
        return ""
    if isinstance(value,(int,float)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def normalize(row, source_row):
    invoice,stock,description,quantity,at,price,customer,country=row
    invoice,stock,description,customer,country=map(text,[invoice,stock,description,customer,country])
    timestamp=at.isoformat() if isinstance(at,datetime) else ""
    valid=True
    try:
        q,p=Decimal(str(quantity)),Decimal(str(price))
        if not q.is_finite() or not p.is_finite() or q!=q.to_integral_value() or p*SCALE!=(p*SCALE).to_integral_value():
            raise ValueError("Non-integral quantity or price precision > 6 decimals")
        q,p=int(q),int(p*SCALE)
        if abs(q*p)>=2**63 or abs(q)>=2**63 or abs(p)>=2**63:
            raise ValueError("Value outside SQLite integer range")
    except (InvalidOperation,ValueError,TypeError,OverflowError):
        valid=False; q=p=None
    if not timestamp or not invoice or not stock or not valid:
        bucket="invalid"
    elif invoice.upper().startswith("C") and q<0 and p>0:
        bucket="cancellation"
    elif not invoice.upper().startswith("C") and q>0 and p>0:
        bucket="sale"
    else:
        bucket="other_non_sale"
    value=q*p if valid else None
    identity=json.dumps([invoice,stock,description,q,timestamp,p,customer,country],ensure_ascii=False)
    fingerprint=hashlib.sha256(identity.encode()).hexdigest()
    return (source_row,invoice,stock,description,q,timestamp,p,customer or None,country,value,bucket,fingerprint)


def ingest(rows, db):
    db.parent.mkdir(parents=True,exist_ok=True)
    db.unlink(missing_ok=True)
    con=sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE lines(source_row INTEGER PRIMARY KEY,invoice TEXT,stock TEXT,description TEXT,
      quantity INTEGER,at TEXT,unit_micropounds INTEGER,customer TEXT,country TEXT,
      value_micropounds INTEGER,bucket TEXT,fingerprint TEXT,duplicate_candidate INTEGER);
    """)
    seen=set(); batch=[]; ledger=Counter()
    for index,row in enumerate(rows,2):
        if len(row)!=8:
            raise ValueError(f"Unexpected column count at source row {index}")
        record=normalize(row,index)
        duplicate=int(record[-1] in seen)
        seen.add(record[-1])
        ledger["rows"]+=1; ledger[record[10]+"_rows"]+=1
        ledger["duplicate_candidates"]+=duplicate
        ledger["missing_customer_rows"]+=int(record[7] is None)
        ledger["missing_description_rows"]+=int(not record[3])
        if record[10] in ("sale","cancellation"):
            ledger[record[10]+"_value_micropounds"]+=record[9]
        batch.append(record+(duplicate,))
        if len(batch)>=5000:
            con.executemany("INSERT INTO lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",batch); batch=[]
    if batch:
        con.executemany("INSERT INTO lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",batch)
    con.executescript("CREATE INDEX idx_lines_customer_time ON lines(customer,at); CREATE INDEX idx_lines_bucket_time ON lines(bucket,at);")
    con.commit();con.close()
    return dict(ledger)


def summarize(db, ledger):
    con=sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    def rows(query):
        return [dict(r) for r in con.execute(query)]
    counts=rows("SELECT bucket,COUNT(*) AS rows,SUM(value_micropounds) AS value_micropounds FROM lines GROUP BY bucket")
    for r in counts:
        if r["rows"]!=ledger.get(r["bucket"]+"_rows",0):
            raise ValueError("Source ledger row reconciliation failed")
        if r["bucket"] in ("sale","cancellation") and r["value_micropounds"]!=ledger.get(r["bucket"]+"_value_micropounds",0):
            raise ValueError("Source ledger money reconciliation failed")
    dates=rows("SELECT MIN(at) AS first,MAX(at) AS last FROM lines WHERE bucket IN ('sale','cancellation')")[0]
    if not dates["first"] or not dates["last"]:
        con.close()
        raise ValueError("No eligible dated sales or cancellations to analyze")
    monthly=rows("""SELECT substr(at,1,7) AS month,
        SUM(CASE WHEN bucket='sale' THEN value_micropounds ELSE 0 END) AS gross_micropounds,
        SUM(CASE WHEN bucket='cancellation' THEN value_micropounds ELSE 0 END) AS cancellation_micropounds,
        COUNT(DISTINCT CASE WHEN bucket='sale' THEN invoice END) AS sales_invoices
        FROM lines WHERE bucket IN ('sale','cancellation') GROUP BY month ORDER BY month""")
    last=datetime.fromisoformat(dates["last"])
    first=datetime.fromisoformat(dates["first"])
    for r in monthly:
        y,m=map(int,r["month"].split("-"))
        r["boundary_incomplete"]=(r["month"]==last.strftime("%Y-%m") and last.day<calendar.monthrange(y,m)[1]) or (r["month"]==first.strftime("%Y-%m") and first.day>1)
        r["signed_flow_micropounds"]=r["gross_micropounds"]+r["cancellation_micropounds"]
    sensitivity=rows("""SELECT SUM(value_micropounds) AS all_sales_micropounds,
        SUM(CASE WHEN customer IS NOT NULL THEN value_micropounds ELSE 0 END) AS known_customer_sales_micropounds,
        SUM(CASE WHEN duplicate_candidate=0 THEN value_micropounds ELSE 0 END) AS deduplicated_sales_micropounds
        FROM lines WHERE bucket='sale'""")[0]
    countries=rows("SELECT country,SUM(value_micropounds) AS gross_micropounds FROM lines WHERE bucket='sale' GROUP BY country ORDER BY gross_micropounds DESC LIMIT 5")
    # One active row/customer/month, first observed positive-sale month as cohort.
    cohort=rows("""WITH active AS (
        SELECT DISTINCT customer,substr(at,1,7) AS month FROM lines WHERE bucket='sale' AND customer IS NOT NULL
      ), firsts AS (SELECT customer,MIN(month) AS cohort FROM active GROUP BY customer),
      sizes AS (SELECT cohort,COUNT(*) AS customers FROM firsts GROUP BY cohort)
      SELECT s.cohort,s.customers,
        (SELECT COUNT(*) FROM firsts f JOIN active a ON f.customer=a.customer
          WHERE f.cohort=s.cohort AND a.month=strftime('%Y-%m',date(s.cohort||'-01','+1 month'))) AS m1_returning
      FROM sizes s ORDER BY s.cohort""")
    complete_months={r["month"] for r in monthly if not r["boundary_incomplete"]}
    for r in cohort:
        y,m=map(int,r["cohort"].split("-")); next_month=f"{y+(m==12):04d}-{m%12+1:02d}"
        r["m1_observable"]=next_month in complete_months
        r["m1_rate"]=r["m1_returning"]/r["customers"] if r["m1_observable"] else None
        if not r["m1_observable"]:
            r["m1_returning"]=None
    con.close()
    return {"synthetic":False,"ledger":ledger,"bucket_totals":counts,"date_range":dates,
            "monthly":monthly,"sensitivity":sensitivity,"top_countries":countries,
            "observed_customer_cohorts":cohort,"source_ledger_reconciled":True,
            "definitions":{"currency":"GBP","integer_money_scale":SCALE,
              "sales":"non-C invoice, positive quantity and price; unknown customers retained",
              "cancellations":"C invoice, negative quantity, positive price; not matched to original invoices",
              "duplicates":"Identical normalized eight-field candidates retained in baseline; exclusion only as sensitivity",
              "cohort":"First observed positive-sales month, not acquisition month; known IDs only"},
            "limitations":["Invoice data has no visit/exposure denominator: conversion and causal product effects are unavailable.",
              "Gross line value and signed cancellation flow are not recognized accounting revenue, profit or matched refund rates.",
              "Missing customer IDs remain in monetary totals, but cannot enter identifiable customer cohorts.",
              "Boundary months are flagged; missing M1 observation is null, not zero.",
              "Identical rows may be legitimate repeated lines; no ingestion duplicate assertion is made."]}


def render_report(result):
    s=result["sensitivity"]; money=lambda v:f"£{v/SCALE:,.2f}"
    report=f"""# 真实数据案例：UCI Online Retail

来源：[UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online-retail)。Chen, D. (2015)，[DOI](https://doi.org/10.24432/C5BW33)，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。本项目对原数据做分类、聚合和敏感性分析，未改写原工作簿。

## 结论与口径

读取 {result['ledger']['rows']:,} 行发票明细，时间覆盖 {result['date_range']['first']} 至 {result['date_range']['last']}。原始读取账本与 SQL 聚合金额及分类行数核对通过。

客户 ID 缺失 {result['ledger'].get('missing_customer_rows',0):,} 行，描述缺失 {result['ledger'].get('missing_description_rows',0):,} 行。来源页面的元数据标记无缺失，与工作簿检查不一致；本报告以原文件的逐行验证为依据，保留这一来源矛盾。

正向销售行金额为 **{money(s['all_sales_micropounds'])}**。若直接删除客户 ID 缺失行，会遗漏 **{money(s['all_sales_micropounds']-s['known_customer_sales_micropounds'])}** 的正向销售金额。货币计算保留百万分之一英镑整数精度，展示时才舍入。

发现 {result['ledger'].get('duplicate_candidates',0):,} 行八字段相同的候选记录，但没有事件主键证明它们是错误重复。基线保留这些记录；若剔除候选重复，正向销售金额变为 {money(s['deduplicated_sales_micropounds'])}，差额为 {money(s['all_sales_micropounds']-s['deduplicated_sales_micropounds'])}。

取消单单独作为负向记录流展示。未将取消单匹配到原始订单，因此不能把行数比例称为退款率。发票数据没有访问分母，也不能回答支付转化率或改版的因果影响。

## 月度金额（GBP）

| 月份 | 正向销售行金额 | 取消单行金额 | 两类记录净额 | 正向销售发票数 | 边界月份不完整 |
|---|---:|---:|---:|---:|---|
"""
    for r in result["monthly"]:
        report+=f"| {r['month']} | {money(r['gross_micropounds'])} | {money(r['cancellation_micropounds'])} | {money(r['signed_flow_micropounds'])} | {r['sales_invoices']:,} | {'是' if r['boundary_incomplete'] else '否'} |\n"
    report+="\n边界月份不完整只根据数据首末日期识别，不证明其余月份没有漏数。2011 年 12 月不能与完整的 11 月直接比较。净额不等同于会计收入。\n\n## 已识别客户的次月复购\n\n| 首次观察购买月份 | 客户数 | 次月再次购买客户数 | 次月复购比例 |\n|---|---:|---:|---:|\n"
    for r in result["observed_customer_cohorts"]:
        report+=f"| {r['cohort']} | {r['customers']:,} | {r['m1_returning'] if r['m1_returning'] is not None else '未完整观察'} | {format(r['m1_rate'],'.1%') if r['m1_rate'] is not None else '不估计'} |\n"
    report+="\n首个样本月存在左截断，首次观察购买不等于真实获客；客户缺失可能导致选择偏差。未完整观察的次月指标保留为空。\n\n## 建议与后续验证\n\n1. 财务金额与客户行为使用不同纳入条件：未知客户仍计入金额，但不进入可识别客户队列。\n2. 获取源系统行 ID 后再决定是否去重，先报告敏感性差异。\n3. 对取消单补充原单关联和成熟窗口，再评估真实退款指标。\n4. 对完整月份进行销售变化分解；先核对覆盖完整性，再讨论经营原因。\n5. 本案例是历史公开数据分析，未声称改善真实业务指标。\n"
    return report


def run(root=ROOT, download=False):
    import openpyxl  # Read-only extraction; no workbook authoring.
    metadata=json.loads((root/"data/sources/uci-online-retail.json").read_text(encoding="utf-8"))
    workbook=root/"data/raw/uci-online-retail/Online Retail.xlsx"
    archive_hash=None
    if download:
        workbook,metadata,archive_hash=fetch(root)
    if not workbook.exists():
        raise ValueError("Source workbook missing; run with --download")
    if metadata.get("workbook_sha256") and sha256(workbook)!=metadata["workbook_sha256"]:
        raise ValueError("Workbook fingerprint changed; review source before proceeding")
    if archive_hash is None and (workbook.parent/"online-retail.zip").exists():
        archive_hash=sha256(workbook.parent/"online-retail.zip")
    book=openpyxl.load_workbook(workbook,read_only=True,data_only=True)
    try:
        if len(book.worksheets)!=1:
            raise ValueError("Expected one worksheet")
        rows=book.worksheets[0].iter_rows(values_only=True)
        columns=list(next(rows))
        if columns!=metadata["expected_columns"]:
            raise ValueError("Source schema changed")
        db=root/"data/processed/uci-retail.sqlite"
        ledger=ingest(rows,db)
    finally:
        book.close()
    result=summarize(db,ledger)
    result["provenance"]={"source":metadata,"workbook_sha256":sha256(workbook),"archive_sha256":archive_hash,
                          "pipeline_sha256":sha256(Path(__file__)),"retrieved_at":datetime.now(timezone.utc).isoformat(),
                          "reader_version":openpyxl.__version__}
    out=root/"artifacts/real-data";out.mkdir(parents=True,exist_ok=True)
    (out/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"report.md").write_text(render_report(result),encoding="utf-8")
    print(json.dumps({"rows":ledger["rows"],"source_ledger_reconciled":True,"archive_sha256":archive_hash,"workbook_sha256":result["provenance"]["workbook_sha256"]},indent=2))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--download",action="store_true");parser.add_argument("--root",type=Path,default=ROOT)
    arguments=parser.parse_args();run(arguments.root,arguments.download)
