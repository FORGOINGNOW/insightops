from datetime import datetime
import pytest
from insightops.real_data import ingest, summarize, normalize, SCALE


def test_real_data_keeps_unknown_customer_and_precise_money(tmp_path):
    rows=[("1","SKU","A",2,datetime(2011,1,1),0.0015,None,"UK"),
          ("2","SKU","A",1,datetime(2011,1,2),10,100,"UK"),
          ("2","SKU","A",1,datetime(2011,1,2),10,100,"UK"),
          ("C2","SKU","A",-1,datetime(2011,2,1),10,100,"UK"),
          ("3","SKU","A",1,datetime(2011,2,2),20,100,"UK"),
          ("4","SKU","A",1,datetime(2011,3,9),30,200,"UK")]
    db=tmp_path/"retail.sqlite"
    ledger=ingest(rows,db)
    report=summarize(db,ledger)
    sensitivity=report["sensitivity"]
    assert sensitivity["all_sales_micropounds"]==70*SCALE+3000
    assert sensitivity["all_sales_micropounds"]-sensitivity["known_customer_sales_micropounds"]==3000
    assert sensitivity["all_sales_micropounds"]-sensitivity["deduplicated_sales_micropounds"]==10*SCALE
    assert report["source_ledger_reconciled"]
    assert report["observed_customer_cohorts"][0]["m1_rate"]==1
    assert report["observed_customer_cohorts"][-1]["m1_rate"] is None
    assert report["monthly"][-1]["boundary_incomplete"]


def test_real_data_fails_if_source_ledger_is_wrong(tmp_path):
    db=tmp_path/"retail.sqlite"
    ledger=ingest([("1","SKU","A",1,datetime(2011,1,1),5,None,"UK")],db)
    ledger["sale_value_micropounds"]+=1
    with pytest.raises(ValueError,match="money reconciliation"):
        summarize(db,ledger)


@pytest.mark.parametrize("quantity,price",[(1,float('nan')),(0.5,1),(1,0.00000001),(10**30,1)])
def test_invalid_source_numerics_are_quarantined(quantity,price):
    record=normalize(("1","SKU","A",quantity,datetime(2011,1,1),price,None,"UK"),2)
    assert record[10]=="invalid"


def test_no_eligible_sales_fails_with_clear_message(tmp_path):
    db=tmp_path/"empty.sqlite"
    ledger=ingest([("1","SKU","A",0,datetime(2011,1,1),5,None,"UK")],db)
    with pytest.raises(ValueError,match="No eligible"):
        summarize(db,ledger)
