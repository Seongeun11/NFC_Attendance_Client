#dashboard_controller.py

from datetime import datetime, timedelta, timezone
# KST (UTC+9) 시간대 정의
KST = timezone(timedelta(hours=9))

# ==========================================
# 1. 기능 및 DB 통신 클래스 (Supabase Direct)
# Apply Local cache
# ==========================================
class AttendanceController:
    # 💡 수정: 외부에서 연동 성공한 supabase_client를 넘겨받도록 설계합니다.
    def __init__(self,supabase_client):
        self.client = supabase_client
    
    #Local Chaching
    # 💡 [대책 3] 고속 NFC 처리를 위한 로컬 메모리 캐시 아키텍처 선언
        self._cache_initialized = False
        self._user_card_cache = {}    # { nfc_uid: { "user_id": ..., "full_name": ..., "student_id": ... } }
        self._attended_user_ids = set() # { user_id1, user_id2, ... } 오늘 출석 완료된 유저 ID 셋
        self._last_processed_uid = None
        self._last_processed_time = datetime.min

    # === [교정 완료] 프로그램 재시작 시 신규 카드 실시간 유실 완벽 차단 버전 ===
    def initialize_local_cache(self, occurrence_id):
        """
        [스키마 정합성 100% 매핑] 프로그램 시작 또는 회차 변경 시 
        DB 스키마(profiles_id, 소문자 active) 기준 최신 상태를 로컬 메모리에 영속화하여 빌드합니다.
        """
        print("🔄 [로컬 캐시] DB 스키마 동기화 및 유효 NFC 카드 목록 전체 로드 중...", flush=True)
        try:
            # 1. DDL에 명시된 nfc_cards(profiles_id)와 profiles(id, enrollment_status='active') 구조 일치 조인
            # DDL에 따라 enrollment_status의 제약조건인 소문자 'active' 기준 필터링 안전 보장
            cards_res = self.client.table("nfc_cards")\
                .select("nfc_id, nfc_status, profiles_id, profiles!inner(id, full_name, student_id, enrollment_status)")\
                .eq("profiles.enrollment_status", "active")\
                .eq("nfc_status", "ACTIVE")\
                .execute()
            
            new_card_cache = {}
            if cards_res.data:
                for row in cards_res.data:
                    uid = row.get("nfc_id")
                    profile = row.get("profiles")
                    # DDL 제약조건 상 profiles_id 또는 profile 제약 id 추출
                    profiles_id = row.get("profiles_id") or (profile.get("id") if profile else None)
                    
                    if uid and profiles_id and profile:
                        cleaned_uid = str(uid).strip().upper()
                        # 시스템 전반에서 유저 식별자로 쓰이는 'user_id' 키에 profiles_id를 완벽 바인딩
                        new_card_cache[cleaned_uid] = {
                            "user_id": profiles_id,
                            "full_name": profile.get("full_name", "-"),
                            "student_id": profile.get("student_id", "-")
                        }
            
            self._user_card_cache = new_card_cache

            # 2. 오늘 해당 회차에 이미 출석체크 완료된 유저 목록 동기화 (attendance 테이블 스키마 기준)
            # DDL 스키마 상 attendance 테이블의 회원 식별 컬럼명은 'user_id' 임을 반영
            attended_res = self.client.table("attendance")\
                .select("user_id")\
                .eq("occurrence_id", occurrence_id)\
                .execute()
            
            self._attended_user_ids = {row["user_id"] for row in attended_res.data} if attended_res.data else set()
            
            self._cache_initialized = True
            print(f"✅ [로컬 캐시 완료] DB 재시작 영속화 성공! 로드된 총 카드 수: {len(self._user_card_cache)}개, 출석 완료자: {len(self._attended_user_ids)}명", flush=True)
            return True
            
        except Exception as e:
            print(f"🛑 [캐시 초기화 치명적 오류] DDL 매핑 실패 (서버 직접 조회로 우회됩니다): {str(e)}", flush=True)
            self._cache_initialized = False
            return False
           
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

    # === [NFC 출석 처리 및 실시간 캐시미스 자가치유 구역] ===
    def process_nfc_attendance(self, occurrence_id, nfc_uid):
        """
        [로컬 캐시 선행 필터링 + 캐시미스 자가치유(DDL 스키마 일치) + DB RPC 결합 버전]
        """
        cleaned_uid = str(nfc_uid).strip().upper()  # 공백 제거 및 대문자 일치
        now = datetime.now(KST)

        # 1. 캐시 비활성화 상태 시 최초 1회 전체 빌드 시도
        if not self._cache_initialized:
            self.initialize_local_cache(occurrence_id)

        # 💡 [자가 치유]: 운영 중 새로 등록되어 메모리(딕셔너리)에 없는 카드 실시간 동기화
        if self._cache_initialized and (cleaned_uid not in self._user_card_cache):
            print(f"🔍 [캐시 미스] 새로 등록된 카드 감지: {cleaned_uid}. DB('nfc_cards')에서 즉시 조회합니다...")
            try:
                # DDL 제약조건 반영: user_id 대신 profiles_id 선택 및 관계형 inner join 적용
                new_card_res = self.client.table("nfc_cards")\
                    .select("profiles_id, nfc_id, nfc_status, profiles!inner(full_name, student_id, enrollment_status)")\
                    .eq("nfc_id", cleaned_uid)\
                    .eq("nfc_status", "ACTIVE")\
                    .eq("profiles.enrollment_status", "active")\
                    .execute()
                
                if new_card_res.data:
                    card_data = new_card_res.data[0]
                    profile = card_data.get("profiles", {})
                    full_name = profile.get("full_name", "신규회원") if profile else "신규회원"
                    student_id = profile.get("student_id", "-") if profile else "-"
                    
                    # 로컬 메모리 캐시에 실시간 동적 적재 (profiles_id를 user_id에 매핑)
                    self._user_card_cache[cleaned_uid] = {
                        "user_id": card_data.get("profiles_id"),  
                        "full_name": full_name,
                        "student_id": student_id
                    }
                    current_total = len(self._user_card_cache)
                    print(f"✅ [자가 치유 완료] 신규 카드 캐시 실시간 적재 성공: {full_name} ({cleaned_uid}) | 현재 총 메모리 카드 수: {current_total}개")
                else:
                    print(f"❌ [검증 실패] DB에 존재하지 않거나 비활성화(INACTIVE) 상태인 카드 차단: {cleaned_uid}")
                    return {
                        "success": False, 
                        "message": f"❌ 등록되지 않았거나 비활성화된 카드입니다. (UID: {cleaned_uid})"
                    }
            except Exception as cache_fetch_err:
                print(f"⚠️ 신규 카드 실시간 캐시 보강 실패 (서버 RPC 통신 모드로 안전 우회): {cache_fetch_err}")

        # 2. 안전하게 캐시에서 데이터를 꺼내 중복 출석 판별 (get() 활용으로 KeyError 완전 방어)
        if self._cache_initialized:
            card_info = self._user_card_cache.get(cleaned_uid)
            if card_info:
                user_id = card_info.get("user_id")
                user_name = card_info.get("full_name", "Unknown")
                
                # [로컬 검증 단계 2] 이미 성공한 출석 대상자인지 판별 (0ms 차단)
                if user_id in self._attended_user_ids:
                    return {"success": True, "message": f"⚠️ [{user_name}]님은 이미 출석 체크가 완료되었습니다."}

        # 3. [원격 서버 RPC 실행 절차]
        try:
            rpc_res = self.client.rpc(
                "process_nfc_attendance_rpc",
                {
                    "p_occurrence_id": occurrence_id,
                    "p_nfc_uid": cleaned_uid
                }
            ).execute()

            if not rpc_res.data:
                raise Exception("서버로부터 응답 데이터를 받지 못했습니다.")

            result_row = rpc_res.data[0]
            is_success = result_row.get("success", result_row.get("p_status", False))
            message = result_row.get("message", result_row.get("p_msg", "처리 완료"))

            # [로컬 캐시 사후 업데이트] 성공 시 완료자 set에 ID 등록
            if self._cache_initialized and cleaned_uid in self._user_card_cache:
                target_id = self._user_card_cache[cleaned_uid].get("user_id")
                if target_id and (is_success or "이미" in message):
                    self._attended_user_ids.add(target_id)

            return {
                "success": is_success,
                "message": message
            }

        except Exception as e:
            print(f"⚠️ [RPC 통신 구역 예외 발생]: {str(e)}")
            return {
                "success": False,
                "message": f"서버 통신 오류가 발생했습니다: {str(e)}"
            }