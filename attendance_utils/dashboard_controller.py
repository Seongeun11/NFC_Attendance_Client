#dashboard_controller.py

from datetime import datetime, timedelta, timezone

# KST (UTC+9) 시간대 정의
KST = timezone(timedelta(hours=9))

# ==========================================
# 1. 기능 및 DB 통신 클래스 (Supabase Direct)
# ==========================================
class AttendanceController:
    # 💡 수정: 외부에서 연동 성공한 supabase_client를 넘겨받도록 설계합니다.
    def __init__(self,supabase_client):
        self.client = supabase_client
    
    def ensure_today_occurrences(self):
        """오늘 회차 동기화/보장 로직."""
        # KST 기준으로 현재 시간을 가져옵니다.
        now = datetime.now(KST)
        today_str = now.strftime("%Y-%m-%d")
        weekday_map = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
        current_weekday = weekday_map[int(now.strftime("%w"))]

        try:
            # 1. 활성화된 이벤트 목록 조회
            events_res = self.client.table("events")\
                .select("*")\
                .eq("is_active", True)\
                .is_("deleted_at", "null")\
                .execute()
            
            active_events = events_res.data
            created_count = 0

            for event in active_events:
                r_type = event.get("recurrence_type")
                r_days = event.get("recurrence_days", [])

                should_create = False
                if r_type == "daily" and current_weekday in r_days:
                    should_create = True
                elif r_type == "none":
                    should_create = True

                if should_create:
                    # 2. 중복 검사
                    exist_res = self.client.table("event_occurrences")\
                        .select("id")\
                        .eq("event_id", event["id"])\
                        .eq("occurrence_date", today_str)\
                        .execute()

                    if not exist_res.data:
                        # KST 기준 오늘 오전 9시로 설정한 뒤 ISO 포맷(뒤에 +09:00이 붙음)으로 변경합니다.
                        # Supabase의 timestamptz 컬럼이 이 시간대를 자동으로 인식하여 저장합니다.
                        start_time_iso = now.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()


                        insert_data = {
                            "event_id": event["id"],
                            "occurrence_date": today_str,
                            "start_time": start_time_iso,
                            "end_time": None,
                            "status": "scheduled"
                        }
                        self.client.table("event_occurrences").insert(insert_data).execute()
                        created_count += 1

            return {"created_count": created_count, "failed_count": 0}
        except Exception as e:
            raise Exception(f"오늘 회차 생성 실패: {str(e)}")

    def fetch_today_occurrences(self, affiliation_id=None):
        """오늘 기준 회차 목록 및 이벤트 정보 조회 (소속 데이터 3중 조인 스펙 추가)"""
        today_str = datetime.now(KST).strftime("%Y-%m-%d")
        try:
            query = self.client.table("event_occurrences")
            
            # [논리 교정]: events 테이블 뒤에 (, affiliations(name))을 추가하여 소속 텍스트 이름을 동시 포획합니다.
            if affiliation_id and affiliation_id != "all":
                res = query.select("*, events!inner(*, affiliations(name))").eq("occurrence_date", today_str).eq("events.affiliations_id", affiliation_id).execute()
            else:
                res = query.select("*, events(*, affiliations(name))").eq("occurrence_date", today_str).execute()
                
            items = res.data if res.data else [] 
        
            # (이하 기존 시간대 파싱 로직 동일...)
            for item in items:
                if item.get("start_time"): 
                    utc_dt = datetime.fromisoformat(item["start_time"].replace("Z", "+00:00"))
                    item["start_time"] = utc_dt.astimezone(KST).isoformat() 
                if item.get("end_time"): 
                    utc_dt = datetime.fromisoformat(item["end_time"].replace("Z", "+00:00")) 
                    item["end_time"] = utc_dt.astimezone(KST).isoformat() 
            return {"date": today_str, "items": items} 
        except Exception as e:
            raise Exception(f"오늘 회차 조회 실패: {str(e)}")

    # ==========================================
    # 💡 [추가] 행사 소속(affiliations) 관리 헬퍼 메서드
    # ==========================================

    def fetch_affiliations(self) -> list:
        """
        데이터베이스의 public.affiliations 테이블에서 전체 소속 목록을 조회합니다.
        ID 역순(최신순) 또는 ID 순으로 정렬하여 반환합니다.
        """
        try:
            # 안전하게 데이터베이스 조회를 실행합니다. (id 기준 오름차순 정렬)
            res = self.client.table("affiliations")\
                .select("id, name")\
                .order("id", ascending=True)\
                .execute()
                
            # 데이터 무결성을 위해 변환 타입 검사 후 리스트 형태로 확실히 반환합니다.
            if res and hasattr(res, 'data') and isinstance(res.data, list):
                return res.data
            return []
        except Exception as e:
            raise Exception(f"소속 데이터 목록을 불러오지 못했습니다: {str(e)}")

    def add_affiliation(self, name: str) -> dict:
        """
        데이터베이스 public.affiliations 테이블에 새로운 행사 소속을 추가합니다.
        name: 추가할 소속 이름 (예: '새로운 수련회')
        """
        # 앞뒤 공백 제거 데이터 정제
        clean_name = name.strip() if name else ""
        if not clean_name:
            raise ValueError("소속 이름은 빈 값일 수 없습니다.")

        try:
            # 1. 중복 데이터 선제 방어 검사 (Unique 제약조건 위반 전 체크)
            check_res = self.client.table("affiliations")\
                .select("id")\
                .eq("name", clean_name)\
                .execute()
                
            if check_res and check_res.data:
                raise Exception(f"이미 존재하는 소속 이름입니다: '{clean_name}'")

            # 2. 데이터 삽입 실행
            insert_data = {"name": clean_name}
            res = self.client.table("affiliations").insert(insert_data).execute()
            
            if res and res.data:
                return {
                    "success": True, 
                    "message": f"소속 '{clean_name}'이(가) 성공적으로 추가되었습니다.",
                    "data": res.data[0]
                }
            raise Exception("서버에서 결과 데이터를 반환받지 못했습니다.")
            
        except Exception as e:
            # 중복 제약 조건이나 RLS 권한 거부 시 UI단으로 에러 전파
            raise Exception(f"소속 추가 실패: {str(e)}")
        
    def fetch_attendance(self, occurrence_id):
        """출석 완료 인원 목록 및 통계 (profiles 조인 포함)"""
        try:
            res = self.client.table("attendance")\
                .select("*, profiles(full_name, student_id)")\
                .eq("occurrence_id", occurrence_id)\
                .execute()
            
            items = res.data or []
            
            present_count = sum(1 for i in items if i.get("status") == "present")
            late_count = sum(1 for i in items if i.get("status") == "late")
            absent_count = sum(1 for i in items if i.get("status") == "absent")

            summary = {
                "total_checked_count": len(items),
                "present_count": present_count,
                "late_count": late_count,
                "absent_count": absent_count
            }

            return {"summary": summary, "items": items}
        except Exception as e:
            raise Exception(f"출석 정보 조회 실패: {str(e)}")

    def fetch_missing(self, occurrence_id):
        """미출석 인원 조회 (전체 활성 수련생 기준 차집합 연산)"""
        try:
            # 1. 재학 중인 전체 프로필 목록 가져오기
            users_res = self.client.table("profiles")\
                .select("id, full_name, student_id")\
                .eq("enrollment_status", "active")\
                .execute()
            all_users = users_res.data or []

            # 2. 이미 출석체크 기록이 있는 유저 ID 목록 조회
            attended_res = self.client.table("attendance")\
                .select("user_id")\
                .eq("occurrence_id", occurrence_id)\
                .execute()
            attended_ids = {row["user_id"] for row in attended_res.data} if attended_res.data else set()

            # 3. 미출석자 추출
            missing_items = []
            for user in all_users:
                if user["id"] not in attended_ids:
                    missing_items.append({
                        "id": user["id"],
                        "full_name": user.get("full_name", "-"),
                        "student_id": user.get("student_id", "-")
                    })

            return {
                "count": len(missing_items),
                "items": missing_items
            }
        except Exception as e:
            raise Exception(f"미출석 정보 조회 실패: {str(e)}")

   

    

    def mark_absent(self, occurrence_id):
        """미출석 유저 전원을 정해진 DB 테이블 구조 양식에 맞게 벌크 결석 처리"""
        try:
            occ_res = self.client.table("event_occurrences").select("event_id").eq("id", occurrence_id).execute()
            if not occ_res.data:
                raise Exception("해당 회차 정보를 찾을 수 없습니다.")
            event_id = occ_res.data[0].get("event_id")

            missing_data = self.fetch_missing(occurrence_id)
            missing_users = missing_data.get("items", [])
            
            if not missing_users:
                return {"message": "결석 처리할 대상이 없습니다.", "marked_absent_count": 0}

            # KST 기준으로 오늘 날짜 문자열 생성
            today_str = datetime.now(KST).strftime("%Y-%m-%d")
            bulk_insert_data = []
            
            for user in missing_users:
                bulk_insert_data.append({
                    "occurrence_id": occurrence_id,
                    "event_id": event_id,
                    "user_id": user["id"],
                    "status": "absent",
                    "method": "manual",
                    "attendance_date": today_str
                })

            self.client.table("attendance").insert(bulk_insert_data).execute()
            return {
                "message": "결석 처리가 완료되었습니다.",
                "marked_absent_count": len(bulk_insert_data)
            }
        except Exception as e:
            raise Exception(f"결석 처리에 실패했습니다: {str(e)}")

    # === [NFC 출석 - 기존 컬럼명(nfc_id) 복구 및 코에스 에러 방어 버전] ===
    def process_nfc_attendance(self, occurrence_id, nfc_uid):
        """
        NFC 카드 UID를 조회하여 소유자를 식별하고 지각 시간을 판별하여 출석 테이블에 반영합니다.
        """
        try:
            # KST 기준으로 현재 시각을 생성하여 날짜 뒤틀림 방지
            now = datetime.now(KST)
            attendance_date = now.strftime("%Y-%m-%d")

            # 원상 복구: 기존 스펙 그대로 .eq("nfc_id", nfc_uid) 조회 사용
            # 단, single()을 지우고 execute()를 사용하여 데이터가 없을 때의 'cannot coerce' 크래시를 원천 방지합니다.
            nfc_res = self.client.table("nfc_cards")\
                .select("profiles_id, nfc_status")\
                .eq("nfc_id", nfc_uid)\
                .execute()
            
            # 중요 처리: 카드가 아예 등록 안 되어 빈 배열([])이 반환되면 커스텀 에러 발생
            if not nfc_res.data:
                raise Exception("등록되지 않은 카드입니다.")
            
            card_info = nfc_res.data[0]
            if card_info.get("nfc_status") != "ACTIVE":
                raise Exception("비활성화된 NFC 카드입니다. 관리자에게 문의하세요.")
            
            user_id = card_info.get("profiles_id")

            # 2. 해당 유저의 상세 이름/학번 프로필 추가 확보
            user_res = self.client.table("profiles")\
                .select("full_name, student_id")\
                .eq("id", user_id)\
                .execute()
                
            if not user_res.data:
                raise Exception("등록되지 않은 카드입니다.")
                
            full_name = user_res.data[0].get("full_name", "미상 수련생")

            # 3. 현재 출석 대상 회차 정보 획득
            occ_res = self.client.table("event_occurrences")\
                .select("*, events(*)")\
                .eq("id", occurrence_id)\
                .execute()
            
            if not occ_res.data:
                raise Exception("유효하지 않은 회차 정보입니다.")
            
            occ_data = occ_res.data[0]
            if occ_data.get("status") in ["closed", "archived"]:
                raise Exception("이미 마감되었거나 기록 보관된 회차이므로 출석 처리가 불가합니다.")

            event_id = occ_data.get("event_id")
            start_time_str = occ_data.get("start_time")
            
            # 지각 기준 계산
            # Supabase에서 넘어온 문자열(보통 Z나 타임존이 포함됨)을 시간대 정보를 포함한 datetime 객체로 파싱합니다.
            start_dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            event_meta = occ_data.get("events") or {}
            late_threshold = event_meta.get("late_threshold_min", 5)
            
            time_diff_mins = (now - start_dt).total_seconds() / 60.0
            
            if time_diff_mins <= late_threshold:
                status = "present"
                status_kor = "출석"
            else:
                status = "late"
                status_kor = "지각"

            # 4. 기존 출석부 중복 체크
            att_check = self.client.table("attendance")\
                .select("id, status")\
                .eq("occurrence_id", occurrence_id)\
                .eq("user_id", user_id)\
                .execute()
            
            if att_check.data:
                existing_record = att_check.data[0]
                if existing_record.get("status") == "absent":
                    raise Exception(f"[{full_name}]님은 관리자에 의해 결석 처리되어 출석 변경이 불가능합니다.")
                raise Exception(f"[{full_name}]님은 이미 출석 체크가 완료되었습니다.")

            # 5. 출석 데이터 삽입 실행
            insert_data = {
                "user_id": user_id,
                "event_id": event_id,
                "occurrence_id": occurrence_id,
                "status": status,
                "method": "nfc",
                "attendance_date": attendance_date,
                "check_time": now.isoformat()  # KST 기준 타임존 문자열(+09:00) 포함되어 저장됨
            }
            
            self.client.table("attendance").insert(insert_data).execute()
            
            return {
                "success": True,
                "message": f"[{full_name}]님 {status_kor} 처리 완료 (방식: NFC)"
            }
            
        except Exception as e:
            # 혹시라도 걸러지지 않은 coerce 등의 예외 메시지가 섞여 나오면 강제로 한 번 더 걸러서 내보냅니다.
            err_text = str(e)
            if "cannot coerce" in err_text or "0 rows" in err_text:
                raise Exception("등록되지 않은 카드입니다.")
            raise Exception(err_text)
        
    