from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def test_flow_separates_units_and_uses_sao_paulo_days(client,db):
    today=datetime.now(ZoneInfo('America/Sao_Paulo')).replace(hour=0,minute=0,second=0,microsecond=0)
    for timestamp,unit,kind,quantity in [(today,'un','ENTRADA',3),(today,'un','SAIDA',2),(today,'m','ENTRADA',1.5),(today-timedelta(minutes=1),'un','SAIDA',4),(today-timedelta(days=7),'un','ENTRADA',99)]:
        db.execute("INSERT INTO movements(product_id,type,quantity,unit_price,total_price,user_id,legacy,product_unit,timestamp) VALUES(1,%s,%s,0,0,1,true,%s,%s)",(kind,quantity,unit,timestamp))
    data=client.get('/api/dashboard/stats').json
    assert len(data['flow_days'])==7
    assert data['flow_days'][-1]==today.date().isoformat()
    values={(r['day'],r['unit'],r['type']):r['quantity'] for r in data['movement_flow']}
    assert values[(today.date().isoformat(),'un','ENTRADA')]=='3.000'
    assert values[(today.date().isoformat(),'un','SAIDA')]=='2.000'
    assert values[(today.date().isoformat(),'m','ENTRADA')]=='1.500'
    assert values[((today-timedelta(days=1)).date().isoformat(),'un','SAIDA')]=='4.000'
    assert len(values)==4
