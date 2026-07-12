#login_controller.py
from tkinter import messagebox

from attendance_utils.login_ui import LoginFrame
from attendance_utils.auth_config import SupabaseAuthManager,SupabaseGlobalContext

# -------------------------------------------------------------------------
# [컨트롤러 레이어] 독립형 LoginApp 클래스
# -------------------------------------------------------------------------
class LoginApp:
    def __init__(self, root, on_success=None): # 기본값 지정을 통해 매개변수가 안 들어와도 안전하게 방어
        self.root = root
        # 외부 콜백이 전달되지 않으면 자체 내부 성공 함수(_default_success_action)를 사용하도록 유연성 확보
        self.on_success = on_success if on_success else self._default_success_action
        self.current_frame = None
        self.client = None  # 요청하신 SUPABASEAUTH 객체 바인딩
        self.auth_manager = SupabaseAuthManager()

        # 최초 로그인 화면 로드 
        self.show_login_frame()

    def show_login_frame(self):
        """기존 프레임을 제거하고 로그인 프레임을 화면에 배치"""
        #if self.current_frame: 
        #    self.current_frame.destroy()
            
        # LoginFrame 생성 시 클릭 이벤트를 본 클래스의 login 메서드로 직접 연결
        self.current_frame = LoginFrame(self.root, on_login_click=self.login)
        self.current_frame.pack(fill="both", expand=True)

    def login(self, admin_id, pw):
        """백그라운드 스레드에서 Supabase 실제 인증을 수행하는 핵심 함수"""
        # 공백 제거 처리로 사용자 입력 오류 방지
        admin_id = admin_id.strip() if admin_id else ""
        pw = pw.strip() if pw else ""

        # 1. UI 스레드를 통해 실시간으로 상태 변경 알림 
        # 1. UI 시작 시 버튼 비활성화 및 상태 업데이트 (연타 차단)
        # [방어 조치] 프레임이 유효할 때만 비활성화 및 텍스트 변경
        # UI 제어 함수 안전성 보강 (객체 유무 및 None 여부 더블 체크)
        def disable_ui():
            if self.current_frame and hasattr(self.current_frame, "login_btn") and self.current_frame.login_btn:
                self.current_frame.login_btn.config(state="disabled")
            if self.current_frame and hasattr(self.current_frame, "status") and self.current_frame.status:
                self.current_frame.status.config(text="웹 서버에 로그인을 시도합니다...")

        def enable_ui(msg=None):
            if self.current_frame and hasattr(self.current_frame, "login_btn") and self.current_frame.login_btn:
                self.current_frame.login_btn.config(state="normal")
            if self.current_frame and hasattr(self.current_frame, "status") and self.current_frame.status and msg:
                self.current_frame.status.config(text=msg)

        # 2. 입력값 유효성 기본 검사
        if not admin_id or not pw:
            self.root.after(0, lambda: self.current_frame.status.config(text="ID와 비밀번호를 모두 입력해주세요.") if self.current_frame and hasattr(self.current_frame, "status") and self.current_frame.status else None)
            self.root.after(0, enable_ui)
            return
        # UI 비활성화 실행
        self.root.after(0, disable_ui)

        try:
            self.auth_manager.login_and_get_client(admin_id, pw)
            # 필요할 때 언제든 최신 연결 정보가 포함된 클라이언트 로드 가능
            self.client = SupabaseGlobalContext.get_client()
      
            
            # 응답 객체 및 세션 유효성 검증
            is_success = self.client is not None
            
            if is_success:
                #print(f"[인증 성공] 세션 확보 완료: ")#{email})
                # [수정 부분 2] self.current_frame 유효성 검사 추가 (Line 81 에러 해결)
                if self.current_frame and hasattr(self.current_frame, "status") and self.current_frame.status:
                    self.current_frame.status.config(text="웹 서버에 로그인을 성공했습니다.")
                # 성공 시 메인 UI 스레드에서 다음 화면(성공 콜백)으로 전환 
                self.root.after(0, self.on_success)
            else:
                
                #print("[인증 실패] 세션 정보가 존재하지 않음")
                self.root.after(0, enable_ui)
                self.root.after(0, lambda: self.current_frame.status.config(text="로그인 실패: 아이디 또는 비밀번호가 올바르지 않습니다.") 
                                if self.current_frame and hasattr(self.current_frame, "status") and self.current_frame.status else None)
        except Exception as e:
            # Supabase API 호출 중 ID/PW 불일치, 네트워크 단절 등의 에러 처리
            #print(f"[인증 에러] {e}")
            
            error_msg = str(e)
            # Supabase 에러 메시지에 따른 한국어 다국어 처리
            if "Invalid login credentials" in error_msg:
                ui_msg = "로그인 실패: ID 또는 비밀번호가 올바르지 않습니다."
                self.root.after(0, enable_ui, "ID와 비밀번호를 모두 입력해주세요.")
            else:
                ui_msg = f"오류 발생: 서버에 연결 할 수 없습니다.\n인터넷 연결을 확인 후 다시 태그해주세요."
                self.root.after(0, enable_ui)
            self.root.after(0, lambda msg=ui_msg: enable_ui(msg))

    def _default_success_action(self):
        """외부에서 별도의 메인 화면(on_success)을 주입하지 않았을 때 실행되는 독립형 엔딩 함수"""
        messagebox.showinfo("오류", "메인화면이 생성되지 않았습니다.\n확인을 누르면 프로그램이 종료됩니다.")
        self.root.quit()