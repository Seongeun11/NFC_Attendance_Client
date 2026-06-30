#attendance_utils\ui_utils.py
from datetime import datetime

def format_status(status):
    mapping = {'scheduled': '대기 중', 'open': '진행 중', 'closed': '종료됨', 'archived': '기록 보관됨'}
    return mapping.get(status, status)

def format_recurrence(days, rec_type):
    if rec_type == 'none' or not days:
        return '없음(단발성)'
    ko_map = {'mon': '월', 'tue': '화', 'wed': '수', 'thu': '목', 'fri': '금', 'sat': '토', 'sun': '일'}
    return ", ".join([str(ko_map.get(d, d)) for d in days if d is not None])

def format_att_status(status):
    mapping = {'present': '✅ 출석', 'late': '⚠️ 지각', 'absent': '❌ 결석'}
    return mapping.get(status, status)

def parse_iso_time(iso_str):
    if not iso_str: return "-"
    try:
        iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return iso_str