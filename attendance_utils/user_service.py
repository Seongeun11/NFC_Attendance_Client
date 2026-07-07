#user_service.py
import time
from tkinter import messagebox
from smartcard.CardMonitoring import CardMonitor
from attendance_utils.nfc_tag_observer import NFCTagObserver

class AuthService:
    def __init__(self,supabase_client):
        #supabase_client=None
        self.client = supabase_client

        pass

    def execute_login(self, admin_id: str, pw: str) -> bool:
        """Supabase를 이용해 관리자 로그인을 수행합니다."""
        
        try:
            # 이메일 도메인 매핑 로직 포함
            email = f"{admin_id}@club.local"
            result = self.client.auth.sign_in_with_password({
                "email": email,
                "password": pw
            })
            if result.user:
                #supabase_client = auth_manager.login_to_web(result)
                #print("관리자 인증 완료", flush=True)
                return True
            return False
        except Exception as e:
            #print(f"로그인 실패 레벨 에러: {str(e)}", flush=True)
            return False
        
class UserSearchService:
    def __init__(self, supabase_client):
        self.client = supabase_client

    def execute_search(self, keyword: str, only_registered: bool = False, only_active: bool = False) -> list:
        """조건에 맞춰 Supabase에서 회원 목록을 조회하고 필터링된 데이터 리스트를 반환합니다."""
        try:
            # 1. 기본 쿼리 빌드 (affiliations 관계형 테이블에서 name 추가 추출하도록 수정)
            query = (
                self.client
                .table("profiles")
                .select("id, full_name, student_id, enrollment_status, "
                        "affiliations(name), "  # 💡 소속명(name)을 함께 들고 오도록 연동
                        "nfc_cards!profiles_id(profiles_id, nfc_id, nfc_status)")
                .or_(f"full_name.ilike.%{keyword}%,student_id.ilike.%{keyword}%")
                .order("student_id")
            )
            
            # 2. 재학생 필터 추가
            if only_active:
                query = query.eq("enrollment_status", "active")
            
            result = query.execute()
            raw_users = result.data or []
            
            filtered_users = []
            for u in raw_users:
                if not isinstance(u, dict): 
                    continue
                    
                nfc_data = u.get("nfc_cards")
                has_card = False

                # NFC 카드 정보 파싱 검증
                if isinstance(nfc_data, dict):
                    has_card = True
                elif isinstance(nfc_data, list) and nfc_data:
                    has_card = True

                # '등록된 사용자만 보기' 필터링
                if only_registered and not has_card:
                    continue

                filtered_users.append(u)
                
            return filtered_users

        except Exception as e:
            raise e
        
# [새로 분리 완료] NFC 카드 데이터 처리 및 리더기 모니터링 전담 클래스
class NfcCardService:
    def __init__(self, supabase_client):
        self.client = supabase_client
        self.active_monitor = None
        self.active_observer = None
        self.current_target = None  # 현재 등록 대기 중인 대상 유저 데이터

    def delete_nfc_card(self, profiles_id: str) -> bool:
        """Supabase nfc_cards 테이블에서 해당 유저의 카드를 삭제합니다."""
        try:
            self.client.table("nfc_cards").delete().eq("profiles_id", profiles_id).execute()
            return True
        except Exception as e:
            #print(f"[NfcCardService] 카드 삭제 에러: {e}", flush=True)
            return False

    def check_and_register_card(self, target_user: dict, uid: str) -> str:
        """
        NFC 카드가 감지되었을 때 중복을 검사하고 카드를 등록합니다.
        반환값: 'SUCCESS' (성공), 'DUPLICATE' (이미 등록된 카드), 'FAILED' (기타 실패)
        """
        # 안전장치: 현재 세팅된 타겟 유저와 카드 태깅 시점의 유저가 다른 스레드 산물이면 무시
        if self.current_target is None or self.current_target.get("id") != target_user.get("id"):
            return 'IGNORE'
            
        try:
            # 1. 중복 카드인지 조회
            check = self.client.table("nfc_cards").select("profiles_id").eq("nfc_id", uid).execute()
            if check.data:
                return 'DUPLICATE'

            # 2. 카드 신규 등록
            self.client.table("nfc_cards").insert({
                "profiles_id": target_user["id"],
                "nfc_id": uid,
                "nfc_status": "ACTIVE"
            }).execute()

            self.current_target = None # 등록 완료 후 타겟 초기화
            return 'SUCCESS'
        except Exception as e:
            # 에러 메시지에 'getaddrinfo'나 '1101'이 포함되어 있다면 네트워크 끊김으로 판단
            if "getaddrinfo" in str(e) or "1101" in str(e):
                messagebox.showerror("오류","서버에 연결 할 수 없습니다.\n인터넷 연결을 확인 후 다시 태그해주세요.")
                return "NETWORK_ERROR" # 메인 UI에 네트워크 에러 상태를 전달
            else:
                messagebox.showerror("오류","dB에서 오루가 발생했습니다.")
                return "DB_ERROR"
        
        

    def cleanup_monitor(self):
        """실행 중인 백그라운드 리더기 자원을 안전하게 해제합니다."""
        if self.active_monitor and self.active_observer:
            try:
                #print("[시스템] 백그라운드 NFC 모니터링 옵저버를 제거합니다.")
                self.active_monitor.deleteObserver(self.active_observer)
            except Exception:
                pass
        self.active_monitor = None
        self.active_observer = None

    # [완벽 수정 복구] 진짜 하드웨어 가동 루프를 가동시키는 핵심 비즈니스 로직입니다.
    def start_hardware_monitor(self, target_user: dict, on_status_change_callback):
        """
        스마트카드 리더기를 가동하여 백그라운드에서 태깅을 감시합니다.
        on_status_change_callback: 메인 앱의 _nfc_hardware_status_listener와 매핑됩니다.
        """
        self.cleanup_monitor()
        self.current_target = target_user

        keep_running = [True]
        monitor = CardMonitor()
        self.active_monitor = monitor

        # 정상적으로 UUID 카드가 인식되었을 때의 처리 콜백 함수
        def handle_uuid_detected(uid):
            try:
                result_status = self.check_and_register_card(target_user, uid)
                # 메인 UI 리스너로 결과 상태(SUCCESS, DUPLICATE 등) 전달
                on_status_change_callback(result_status, target_user, uid)
                
                if result_status in ['SUCCESS', 'DUPLICATE']:
                    keep_running[0] = False
            

            except Exception as e:
                messagebox.showinfo("Error", "서버와 연결이 끊어졌습니다. 인터넷 연결을 확인 후 다시 태그해주세요.")

        # 카드 통신 및 하드웨어단 에러 발생 시 처리 콜백 함수
        def handle_hardware_error(error_msg):
            # 메인 UI 리스너의 elif status == 'ERROR' 분기를 직접 타도록 신호를 송신합니다.
            on_status_change_callback('ERROR', target_user, error_msg)

        # 옵저버 생성 시 정상 콜백과 에러 콜백을 함께 주입합니다.
        observer = NFCTagObserver(
            on_uuid_detected=handle_uuid_detected, 
            on_error_detected=handle_hardware_error
        )
        self.active_observer = observer
        
        try:
            monitor.addObserver(observer)
            # 대기 스레드 루프 활성화
            while keep_running[0] and self.active_observer == observer:
                time.sleep(1)
        except Exception as startup_error:
            # 리더기 시작 자체에서 에러 발생 시 처리 (예: 드라이버 다운 등)
            on_status_change_callback('ERROR', target_user, str(startup_error))
            messagebox.showinfo("오류", "서버에 연결 할 수 없습니다.\n인터넷 연결을 확인 후 다시 태그해주세요.")
        finally:
            try:
                monitor.deleteObserver(observer)
            except Exception:
                pass
            on_status_change_callback('TERMINATED', target_user, None)