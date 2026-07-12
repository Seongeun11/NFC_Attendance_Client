#user_service.py
from tkinter import messagebox
from attendance_utils.nfc_reader_manager import ReaderManager


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
        
# ======================================================================
# [교정 완료] NFCTagObserver를 제거하고 ReaderManager와 완벽 연동된 서비스
# ======================================================================
class NfcCardService:
    def __init__(self, supabase_client):
        self.client = supabase_client
        self.reader_manager = None       # [변경] 모니터 및 옵저버 자리를 ReaderManager로 교체
        self.current_target = None       # 현재 등록 대기 중인 대상 유저 데이터
        self.ui_listener_callback = None # 메인 UI의 _nfc_hardware_status_listener 보관용

    def delete_nfc_card(self, profiles_id: str) -> bool:
        """Supabase nfc_cards 테이블에서 해당 유저의 카드를 삭제합니다."""
        try:
            self.client.table("nfc_cards").delete().eq("profiles_id", profiles_id).execute()
            return True
        except Exception:
            return False

    def check_and_register_card(self, target_user: dict, uid: str) -> str:
        """
        NFC 카드가 감지되었을 때 중복을 검사하고 카드를 등록합니다.
        """
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
            if "getaddrinfo" in str(e) or "1101" in str(e):
                messagebox.showerror("오류", "서버에 연결할 수 없습니다.\n인터넷 연결을 확인 후 다시 태그해주세요.")
                return "NETWORK_ERROR"
            else:
                messagebox.showerror("오류", "DB에서 오류가 발생했습니다.")
                return "DB_ERROR"

    def cleanup_monitor(self):
        """실행 중인 ReaderManager 자원을 안전하게 해제 및 종료합니다."""
        if self.reader_manager:
            try:
                self.reader_manager.stop_all_readers()
            except Exception:
                pass
        self.reader_manager = None
        self.ui_listener_callback = None

    def _ui_callback_bridge(self, message, status_type="info"):
        """
        ReaderManager 내부의 실시간 로그를 수신하고, 
        동시에 태깅 성공/실패 여부를 판단하여 기존 메인 UI의 리스너 상태 파이프라인으로 라우팅합니다.
        """
        print(f"[NfcCardService 브릿지 로그] ({status_type.upper()}): {message}")
        
        # 1. 리더기 매니저 로그 메시지 내부에 실제 카드 감지 및 완료 징후 분석
        # ReaderManager 소비자가 전송한 가동 로그나 상태 변경 감지
        if "카드 감지 성공" in message or "카드를 서버에 등록하는 중" in message:
            # 해당 로그는 ReaderWorker 단독 출석 로직에서 주로 처리하므로, 
            # 회원 등록 모드에서는 아래 'start_hardware_monitor' 내에 주입되는 가상 컨트롤러 메커니즘에서 실질 처리를 담당합니다.
            pass

    def start_hardware_monitor(self, target_user: dict, on_status_change_callback):
        """
        [논리 교정] ReaderManager의 멀티 스레드 풀 및 큐 메커니즘을 기동하여 카드 등록을 모니터링합니다.
        on_status_change_callback: 메인 앱의 _nfc_hardware_status_listener와 매핑됩니다.
        """
        self.cleanup_monitor()
        self.current_target = target_user
        self.ui_listener_callback = on_status_change_callback

        # ReaderManager의 소비자(Consumer)가 정상 작동하려면 컨트롤러 객체가 필요합니다.
        # 회원 가입/등록 모드용 가상 Mock 컨트롤러를 즉석에서 구성하여 주입합니다.
        class CardRegistrationController:
            def __init__(self, service_ref, target):
                self.service = service_ref
                self.target = target
            
            def process_nfc_attendance(self, occurrence_id, nfc_uid):
                """ReaderManager가 큐에서 데이터를 꺼낸 후 호출하는 비즈니스 핵심 접점"""
                # 실제 DB 등록 및 검증 수행
                result_status = self.service.check_and_register_card(self.target, nfc_uid)
                
                # 메인 UI 상태 리스너에 실시간 상태 전파 (SUCCESS, DUPLICATE, NETWORK_ERROR 등)
                if self.service.ui_listener_callback:
                    self.service.ui_listener_callback(result_status, self.target, nfc_uid)
                
                # 모니터링 자동 종료 플래그용 리턴값 반환
                if result_status in ['SUCCESS', 'DUPLICATE']:
                    # 등록 절차가 1회성으로 완료되면 즉시 장치 해제 유도
                    self.service.cleanup_monitor()
                    
                return {"message": f"카드 등록 처리 시도 완료 Status: {result_status}"}

        # 1. 더미 컨트롤러 인스턴스 빌드
        mock_controller = CardRegistrationController(self, target_user)
        
        # 2. ReaderManager 인스턴스화 및 결합
        # 브릿지 콜백 함수를 주입하여 텍스트 로그 흐름 유도
        self.reader_manager = ReaderManager(controller=mock_controller, ui_callback=self._ui_callback_bridge)
        
        # 3. 출석용 필수 필드 검증을 우회하기 위해 모드 문자열 강제 세팅
        #ReaderManager가 큐에서 데이터를 꺼내 처리할 때,
        #occurrence_id가 특정 예약 문자열(예: "CARD_REGISTRATION_MODE")이거나
        # 주입된 컨트롤러의 클래스 이름이 CardRegistrationController인 경우 회차 선택 필수 검증 로직을 우회하도록 수정합니다.
        self.reader_manager.set_occurrence_id("CARD_REGISTRATION_MODE")
        #print(self.reader_manager.set_occurrence_id)
        
        try:
            # 4. 물리 멀티 리더기 스캔 및 백그라운드 관제 소비자 스레드 전체 가동
            self.reader_manager.start_all_readers()
        except Exception as startup_error:
            if self.ui_listener_callback:
                self.ui_listener_callback('ERROR', target_user, str(startup_error))
            messagebox.showinfo("오류", f"리더기 감지 시스템 초기화 실패: {str(startup_error)}")
            if self.ui_listener_callback:
                self.ui_listener_callback('TERMINATED', target_user, None)