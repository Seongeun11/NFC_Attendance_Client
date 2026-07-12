# main_ui.py
import tkinter as tk
import tkinter.ttk as ttk
import threading
from typing import Optional, Callable  # 타입 힌팅을 위해 임포트
from attendance_utils.today_operations_app import TodayOperationsApp
from attendance_utils.nfc_reader_manager import ReaderManager # <- 실제 경로에 맞게 확인해주세요.
class MainFrame(tk.Frame):
    def __init__(self, parent, on_search_click, on_register_click, on_delete_click):
        super().__init__(parent)
        self.parent = parent
        self.controller = None  # app.py 등에서 동적으로 바인딩받을 변수

        # 💡 [Pylance 에러 치유 1] reader_manager가 ReaderManager 객체 혹은 None을 가질 수 있음을 명시
        self.reader_manager: Optional[ReaderManager] = None
        # 주입받은 콜백 함수들을 인스턴스 변수로 저장하여 내부에서 유연하게 호출할 수 있도록 함
        self.on_search_click = on_search_click
        self.on_register_click = on_register_click
        self.on_delete_click = on_delete_click
        self.reader_manager = None # NfcApp에서 주입받을 변수 명시
        
        # 출석 대시보드 전체 UI프레임이 내장되므로 가로/세로를 충분히 넓혀줍니다.
        self.parent.title("NFC 관리자 통합 대시보드")
        self.parent.geometry("750x860")  # 콤보박스 배치를 위해 가로 너비 소폭 확장 

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        # [탭 1] 등록 및 해지용 내부 구성 정의
        frame1 = tk.Frame(self)
        self.notebook.add(frame1, text="등록 및 해지")
        
        # --- 기존 등록 UI 요소 배치부 ---
        top_bar = tk.Frame(frame1)
        top_bar.pack(fill="x", padx=10, pady=10)
        
        tk.Label(top_bar, text="사용자 검색:").pack(side="left", padx=5)
        self.search_entry = tk.Entry(top_bar)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)

        # 💡 [추가] 소속 필터 콤보박스 위젯 배치
        tk.Label(top_bar, text="소속 필터:").pack(side="left", padx=5)
        self.dept_combobox = ttk.Combobox(top_bar, state="readonly", width=12)
        self.dept_combobox.set("전체")
        self.dept_combobox.pack(side="left", padx=5)


        self.only_reg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top_bar, text="등록된 사용자만", variable=self.only_reg_var).pack(side="left", padx=5)
        
        # 재학생만 보기 변수 및 체크박스
        self.only_active_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top_bar, text="재학생만", variable=self.only_active_var).pack(side="left", padx=5)

        # 💡 검색 버튼 클릭 시 self.dept_combobox.get() 인자까지 함께 전달하도록 확장 [cite: 139]
        tk.Button(
            top_bar, 
            text="검색", 
            command=lambda: threading.Thread(
                target=on_search_click, 
                args=(self.search_entry.get(), self.only_reg_var.get(), self.only_active_var.get(), self.dept_combobox.get()), 
                daemon=True
            ).start()
        ).pack(side="left", padx=5)

        list_frame = tk.Frame(frame1)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        self.listbox.pack(fill="both", expand=True, side="left")
        scrollbar.config(command=self.listbox.yview)

        # 사용자가 리스트박스 항목을 클릭(선택 변경)하면 등록 모드를 취소합니다.
        self.listbox.bind("<<ListboxSelect>>", self.on_listbox_selection_changed)
        # 더블클릭 및 엔터 입력 시 즉시 등록 함수 연동
        self.listbox.bind("<Double-1>", lambda event: on_register_click())
        self.listbox.bind("<Return>", lambda event: on_register_click())


        btn_bar = tk.Frame(frame1)
        btn_bar.pack(fill="x", padx=10, pady=10)
        
        self.status = tk.Label(btn_bar, text="사용자를 선택하고 발급 프로세스를 진행하세요.\n더블클릭을 하거나 엔터를 누르면 등록을 시작합니다.\n방향키로 리스트를 선택할수 있습니다.", fg="blue")
        self.status.pack(side="left", padx=5)
        self.status_log = tk.Label(frame1, text="", fg="orange")
        self.status_log.pack(fill="x", side="bottom")

        tk.Button(btn_bar, text="NFC 카드 삭제", command=lambda: threading.Thread(target=on_delete_click, daemon=True).start()).pack(side="right", padx=5)
        tk.Button(btn_bar, text="NFC 카드 등록", command=on_register_click).pack(side="right", padx=5)

        # -------------------------------------------------------------------------
        # [탭 2] 출석 탭 내부에 dashboard_ui 전체(TodayOperationsApp) 임포트 연동
        # -------------------------------------------------------------------------
        frame2 = tk.Frame(self, bg="#f9fafb")
        self.notebook.add(frame2, text="출석 현황 대시보드")
        
        # [핵심 처리]: TodayOperationsApp을 인스턴스화하되, frame2를 부모(parent)로 주입합니다.
        # 독립형 창이 아닌 '내장 프레임 위젯'으로 안정적으로 가두기 위한 바인딩입니다.
        self.attendance_app_frame = TodayOperationsApp(parent=frame2)
        self.attendance_app_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 탭이 클릭되어 전환될 때 실시간 동기화 호출용 바인딩
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_switched)

    # 💡 [핵심 에러 해결]: unknown 오류가 났던 메서드를 명시적으로 구현합니다.
    def update_reader_manager_status(self, message: str, status_type: str = "info"):
        """ ReaderManager(백그라운드 스레드)에서 전달된 하드웨어 통신 로그 및 
            서버 응답 결과를 메인 UI 스레드에서 안전하게 새로고침합니다. """
        color = "blue"
        if status_type == "error": 
            color = "#b91c1c"  # 빨간색 (에러)
        elif status_type == "success": 
            color = "green"    # 초록색 (성공)
        elif status_type == "info":
            color = "blue"     # 파란색 (진행 중)

        # Tkinter는 메인 스레드가 아닌 곳에서 위젯을 직접 건드리면 깨지므로 after() 사용
        if hasattr(self, 'status_log') and self.status_log.winfo_exists():
            self.parent.after(0, lambda: self.status_log.config(text=message, fg=color))    
    # 카드 등록 모드를 명시적으로 취소하는 메서드
    def cancel_registration_mode(self, reason_text=""):
        # 컨트롤러(NfcApp) 측에 등록 대기 중인 사용자 타겟 정보를 리셋 요청
        if self.controller and hasattr(self.controller, 'current_target'):
            self.controller.current_target = None
        if self.controller and hasattr(self.controller, 'is_registering'):
            self.controller.is_registering = False
            
        # UI 문구 복구
        self.status.config(text="사용자를 선택하고 발급 프로세스를 진행하세요.", fg="blue")
        if reason_text:
            self.status_log.config(text=f"🛑 {reason_text}", fg="#b91c1c")

    def on_listbox_selection_changed(self, event):
        """리스트박스에서 다른 대상을 선택하면 등록 대기 상태를 무조건 해제합니다."""
        # 선택이 완전히 비어있지 않은지 검증 후 취소 처리
        if self.listbox.curselection():
            self.cancel_registration_mode("다른 사용자가 선택되어 카드 등록 프로세스가 취소되었습니다.")

    # 💡 엔터키나 다른 동작을 정의한 핸들러 메서드 내부에도 인자 개수 동기화 처리 [cite: 147]
    def handle_search_action(self):
        """검색 버튼 클릭 시 기존 등록 작업을 취소한 후 조회를 시작합니다."""
        self.cancel_registration_mode("새로운 검색 조회가 시작되어 등록 프로세스가 취소되었습니다.")
        threading.Thread(
            target=self.on_search_click, 
            args=(self.search_entry.get(), self.only_reg_var.get(), self.only_active_var.get(), self.dept_combobox.get()), 
            daemon=True
        ).start()

    def handle_delete_action(self):
        """삭제 버튼 작동 시 기존 등록 진행 상태를 먼저 철회합니다."""
        self.cancel_registration_mode("카드 삭제 작업이 요청되어 등록 프로세스가 취소되었습니다.")
        threading.Thread(target=self.on_delete_click, daemon=True).start()

    def handle_register_action(self):
        """NFC 카드 등록 버튼을 클릭했을 때의 트리거"""
        # 기존 등록 로직 실행 (NfcApp.register)
        if self.on_register_click:
            
            self.on_register_click()

    def link_controller(self, controller):
        """외부 비즈니스 DB 컨트롤러 자원을 내장된 출석 전체 프레임에 전파 연결합니다."""
        self.controller = controller
        
        # TodayOperationsApp 프레임에 컨트롤러 주입
        if hasattr(self.attendance_frame_layout_check(), "controller"):
            self.attendance_frame_layout_check().controller = controller
            #print("[시스템] attendance_UI 전체 프레임에 DB 컨트롤러 주입 완료.")
            
            # 초기 로드 시 대시보드 새로고침 유도
            self.safe_refresh_dashboard()

    def attendance_frame_layout_check(self):
        """TodayOperationsApp 내부 또는 하단에 상주하는 인스턴스 타겟을 안전하게 추적하는 헬퍼"""
        return self.attendance_app_frame

    def safe_refresh_dashboard(self):
        """화면 깨짐 및 스레드 락을 방지하며 출석 리스트를 리프레시하는 내부 함수"""
        target = self.attendance_frame_layout_check()
        if hasattr(target, "refresh_today_dashboard"):
            try:
                target.refresh_today_dashboard()
            except Exception as e:
                #print(f"[대시보드 경고] 새로고침 중 오류 발생: {e}")
                pass

    def on_tab_switched(self, event):
        """ 사용자가 탭을 전환할 때 각 탭의 기능을 분리하고 하드웨어 모드를 스위칭합니다 """
        try:
            selected_tab_index = self.notebook.index(self.notebook.select())
            attendance_frame = getattr(self, 'attendance_app_frame', None)
            
            # 이제 명확하게 인스턴스가 주입되므로 정상 참조됩니다.
            main_reader_mgr = self.reader_manager 
            attendance_reader_mgr = getattr(attendance_frame, 'reader_manager', None) if attendance_frame else None
            
            if selected_tab_index == 0:
                # [A] 등록 및 해지 탭 활성화
                if main_reader_mgr is not None:
                    main_reader_mgr.set_active_mode("REGISTRATION")
                if attendance_reader_mgr is not None:
                    attendance_reader_mgr.set_active_mode("NONE")
                
                self.status_log.config(text="카드 등록 모드가 활성화되었습니다. 리스트 선택 후 카드를 태그해주세요.", fg="blue")

            elif selected_tab_index == 1:
                # [B] 출석 현황 대시보드 탭 활성화
                if main_reader_mgr is not None:
                    main_reader_mgr.set_active_mode("NONE")
                
                if hasattr(self, 'cancel_registration_mode'):
                    self.cancel_registration_mode("출석 대시보드로 이동하여 카드 등록 프로세스가 종료되었습니다.")
                
                # 대시보드 내부 리더 매니저 혹은 통합 매니저를 ATTENDANCE 모드로 전환
                if main_reader_mgr is not None:
                    main_reader_mgr.set_active_mode("ATTENDANCE")
                if attendance_reader_mgr is not None:
                    attendance_reader_mgr.set_active_mode("ATTENDANCE")
                
                if hasattr(self, 'safe_refresh_dashboard'):
                    threading.Thread(target=self.safe_refresh_dashboard, daemon=True).start()
                    
                self.status_log.config(text="출석 관리 모드가 활성화되었습니다.", fg="green")
                
        except Exception as e:
            print(f"[탭 전환 오류 고유번호 점검] {e}", flush=True)