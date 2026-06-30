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
    def process_nfc_attendance(self, occurrence_id: str, nfc_uid: str) -> dict:
        """
        [교정 버전] 
        인자 순서 뒤틀림을 방어하고, 잘못된 UUID 입력('o4b9fc9d4f6180') 시 크래시 없이 
        안전한 실패 처리를 보장하는 초고속 단일 트랜잭션 RPC 프로세서입니다.
        """
        try:
            # 💡 논리오류 원천 봉쇄: 인자가 비어있거나 타입 가드가 필요한 경우 사전 필터링
            if not occurrence_id or len(occurrence_id) < 30: # 정상 UUID는 36자입니다.
                return {
                    "success": False,
                    "message": f"올바르지 않은 회차 정보(UUID) 형태입니다. 입력값: {occurrence_id}"
                }
            
            if not nfc_uid:
                return {"success": False, "message": "NFC 카드 데이터를 읽지 못했습니다."}

            # 안전하게 파라미터 이름을 명시(Named Parameter)하여 Supabase rpc 호출
            response = self.client.rpc(
                "process_nfc_attendance_rpc",
                {
                    "p_occurrence_id": str(occurrence_id),  # 확실하게 String/UUID 캐스팅
                    "p_nfc_uid": str(nfc_uid)
                }
            ).execute()

            # 응답 가용성 전수 검사
            if not response.data or len(response.data) == 0:
                return {"success": False, "message": "데이터베이스로부터 결과를 받지 못했습니다."}

            result = response.data[0]
            return {
                "success": result.get("success", False),
                "message": result.get("message", "알 수 없는 응답 형식입니다.")
            }

        except Exception as e:
            raise Exception(f"NFC 출석 통신 트랜잭션 에러 백트랙: {str(e)}")
            