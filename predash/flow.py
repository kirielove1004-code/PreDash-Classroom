"""Validated KIS investor flow; net-buy quantity, not trading value."""
from datetime import datetime

def summarize_flow(rows,today):
    valid=[];seen=set()
    for row in rows:
        stamp=str(row.get('stck_bsop_date',''))
        try:
            day=datetime.strptime(stamp,'%Y%m%d').date()
            if day>today:continue
            values={key:int(str(row[field]).replace(',','')) for key,field in (
                ('individual','prsn_ntby_qty'),('foreign','frgn_ntby_qty'),('institution','orgn_ntby_qty'))}
        except (ValueError,TypeError,KeyError):continue
        if day in seen:continue
        seen.add(day);valid.append((day,values))
    valid.sort(key=lambda x:x[0],reverse=True)
    if not valid or (today-valid[0][0]).days>5:return None
    latest=valid[0]
    totals={k:0 for k in latest[1]};history=[]
    for day,values in reversed(valid[:20]):
        totals={k:totals[k]+values[k] for k in totals}
        history.append({'date':day.isoformat(),'daily':values,'cumulative':dict(totals)})
    selected=valid[:5]
    return {'date':latest[0].isoformat(),'daily':latest[1],
            'five_day':{key:sum(row[key] for _,row in selected) for key in latest[1]},
            'history':history,'sessions':len(selected),'from':selected[-1][0].isoformat()}



def public_investor_flow(code,today):
    """Fallback investor net-buy quantity from KRX data via pykrx.

    Returns the same shape as Kiwoom investor_flow so the dashboard can keep
    showing foreign/institution/individual flow when broker authentication is
    unavailable. This is a read-only public-data fallback, not account data.
    """
    try:
        from pykrx import stock
        start=(today.replace(day=1) if today.day>20 else today)
        # Ask for enough calendar history to cover at least ~20 sessions.
        from datetime import timedelta
        from_day=(today-timedelta(days=45)).strftime('%Y%m%d')
        to_day=today.strftime('%Y%m%d')
        frame=stock.get_market_trading_volume_by_date(
            from_day,to_day,str(code),on='순매수',detail=False,freq='d'
        )
    except Exception as exc:
        raise ValueError('KRX 보조 수급 조회에 실패했습니다.') from exc
    if frame is None or getattr(frame,'empty',True):
        return None
    rows=[]
    for idx,row in frame.iterrows():
        try:
            stamp=idx.strftime('%Y%m%d')
            individual=row.get('개인')
            foreign=row.get('외국인합계')
            institution=row.get('기관합계')
            if individual is None or foreign is None or institution is None:
                continue
            rows.append({
                'stck_bsop_date':stamp,
                'prsn_ntby_qty':int(individual),
                'frgn_ntby_qty':int(foreign),
                'orgn_ntby_qty':int(institution),
            })
        except Exception:
            continue
    result=summarize_flow(rows,today)
    if result:
        result['source']='KRX 공개자료 보조조회(pykrx)'
        result['fallback']=True
    return result
