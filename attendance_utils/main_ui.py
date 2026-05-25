# main_ui.py
import tkinter as tk
import tkinter.ttk as ttk
import threading

from attendance_utils.dashboard_ui import TodayOperationsApp

class MainFrame(tk.Frame):
    def __init__(self, parent, on_search_click, on_register_click, on_delete_click):
        super().__init__(parent)
        self.parent = parent
        self.controller = None  # app.py 등에서 동적으로 바인딩받을 변수
        
        # 출석 대시보드 전체 UI프레임이 내장되므로 가로/세로를 충분히 넓혀줍니다.
        self.parent.title("NFC 관리자 통합 대시보드")
        self.parent.geometry("620x860")  

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
        
        self.only_reg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top_bar, text="등록된 사용자만", variable=self.only_reg_var).pack(side="left", padx=5)
        
        # [추가] 재학생만 보기 변수 및 체크박스
        self.only_active_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top_bar, text="재학생만", variable=self.only_active_var).pack(side="left", padx=5)

        # [추가] 검색 버튼 클릭 시 on_search_click에 self.only_active_var.get() 인자 추가 전달
        tk.Button(
            top_bar, 
            text="검색", 
            command=lambda: threading.Thread(
                target=on_search_click, 
                args=(self.search_entry.get(), self.only_reg_var.get(), self.only_active_var.get()), 
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

        btn_bar = tk.Frame(frame1)
        btn_bar.pack(fill="x", padx=10, pady=10)
        
        self.status = tk.Label(btn_bar, text="사용자를 선택하고 발급 프로세스를 진행하세요.", fg="gray")
        self.status.pack(side="left", padx=5)
        self.status_log = tk.Label(frame1, text="", fg="orange")
        self.status_log.pack(fill="x", side="bottom")

        tk.Button(btn_bar, text="NFC 카드 삭제", command=lambda: threading.Thread(target=on_delete_click, daemon=True).start()).pack(side="right", padx=5)
        tk.Button(btn_bar, text="NFC 카드 등록", command=on_register_click).pack(side="right", padx=5)

        # -------------------------------------------------------------------------
        # [탭 2] 출석 탭 내부에 attendance_UI 전체(TodayOperationsApp) 임포트 연동
        # -------------------------------------------------------------------------
        frame2 = tk.Frame(self, bg="#f9fafb")
        self.notebook.add(frame2, text="출석 현황 대시보드")
        
        # [핵심 처리]: TodayOperationsApp을 인스턴스화하되, frame2를 부모(parent)로 주입합니다.
        # 독립형 창이 아닌 '내장 프레임 위젯'으로 안정적으로 가두기 위한 바인딩입니다.
        self.attendance_app_frame = TodayOperationsApp(parent=frame2)
        self.attendance_app_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 탭이 클릭되어 전환될 때 실시간 동기화 호출용 바인딩
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_switched)
        

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
        """사용자가 '출석 현황 대시보드' 탭을 활성화할 때마다 최신 출석 리스트를 백엔드와 강제 동기화"""
        try:
            selected_title = self.notebook.tab(self.notebook.select(), "text").strip()
            if "출석" in selected_title:
                #print("[이벤트] 출석 대시보드 탭 감지 - 최신 DB 동기화 스레드 가동")
                # 무거운 Supabase 통신으로 인한 UI 멈춤 방지를 위해 데몬 스레드로 새로고침 처리
                threading.Thread(target=self.safe_refresh_dashboard, daemon=True).start()
        except Exception:
            pass