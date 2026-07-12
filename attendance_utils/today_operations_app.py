#attendance_utils\today_operations_app.py
import tkinter as tk
from tkinter import ttk
import threading

# NFC 모니터링 모듈 연결
from attendance_utils.nfc_reader_manager import ReaderManager

# 분리해 낸 개별 컴포넌트 클래스 명시적 임포트
from attendance_utils.occurrence_card_ui import OccurrenceCardUi

class TodayOperationsApp(tk.Frame):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent
        
        self.affiliation_map = {"전체 보기": "all"}
        self.selected_affiliation_id = "all"
        
        self.controller = None
        self.operation_date = ""
        self.occurrence_items = []
        self.card_widgets = []
        
        #self.nfc_monitor = None
        #self.nfc_observer = None
        self.selected_occurrence_id = None 
        self.reader_manager = None
       
        self.init_ui()
        self.start_nfc_service()
        try:
            if hasattr(self, "protocol"):
                getattr(self, "protocol")("WM_DELETE_WINDOW", self.on_close_window)
        except Exception as e:
            self.set_global_noti(f"초기화 실패: {e}", "error")
            pass
            
    def init_ui(self):
        main_container = tk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # 1. 상단 고정 영역
        self.fixed_top_frame = tk.Frame(main_container)
        self.fixed_top_frame.pack(fill="x", side="top")

        header_frame = tk.Frame(self.fixed_top_frame)
        header_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(header_frame, text="오늘 출석 운영 (NFC)", font=("Arial", 16, "bold")).pack(anchor="w")
        desc_text = (
            "오늘 날짜 기준 회차 조회,  실시간 NFC 카드 리더 인식을 관리하는 화면입니다.\n"
            "NFC 태깅 출석을 진행하려면 아래 목록에서 원하시는 [회차 카드]를 먼저 클릭해 활성화해 주세요.\n"
            "출석: 시작 1시간전 + 시작시간 + 지각 분 이내 |\n"
            "지각: 시작시간 + 지각 분 이후"
        )
        tk.Label(header_frame, text=desc_text, fg="#666666", justify="left", anchor="w", font=("Arial", 9)).pack(anchor="w", pady=5)

        self.lbl_noti = tk.Label(self.fixed_top_frame, width=40, text="NFC 카드를 태그해주세요.", font=("Arial", 11, "bold"), fg="blue", bg="#f0fdf4", height=2, relief="solid")
        self.lbl_noti.pack(fill="x", pady=5)

        self.summary_frame = tk.LabelFrame(self.fixed_top_frame, text="운영 현황 요약")
        self.summary_frame.pack(fill="x", pady=10)
        
        self.summary_labels = {}
        dash_cards = [
            ("date", "운영 날짜"), ("total_occ", "오늘 회차 수"), ("open_occ", "진행 중 회차"),
            ("closed_occ", "종료 회차")
        ]
        for i, (key, title) in enumerate(dash_cards):
            f = tk.Frame(self.summary_frame, relief="groove", bd=1)
            f.grid(row=0, column=i, padx=4, sticky="ew")
            self.summary_frame.columnconfigure(i, weight=1)
            tk.Label(f, text=title, font=("Arial", 9), fg="#555555").pack()
            lbl_v = tk.Label(f, text="-", font=("Arial", 12, "bold"))
            lbl_v.pack(pady=(2, 0))
            self.summary_labels[key] = lbl_v

        action_panel = tk.Frame(self.fixed_top_frame)
        action_panel.pack(fill="x", pady=5)
        
        tk.Label(action_panel, text="행사 소속:", font=("Arial", 10, "bold")).pack(side="left", padx=(5, 2))
        self.combo_affiliation = ttk.Combobox(action_panel, state="readonly", width=18)
        self.combo_affiliation.pack(side="left", padx=3)
        self.combo_affiliation.bind("<<ComboboxSelected>>", self.on_affiliation_changed)

        self.btn_sync = ttk.Button(action_panel, text="오늘 회차 동기화", command=self.handle_sync_today)
        self.btn_sync.pack(side="left", padx=3)
        
        self.btn_refresh = ttk.Button(action_panel, text="새로고침", command=self.refresh_today_dashboard)
        self.btn_refresh.pack(side="left", padx=3)

        self.noti_frame = tk.Frame(self.fixed_top_frame)
        self.noti_label = tk.Label(self.noti_frame, text="", wraplength=750, justify="left", font=("Arial", 10))
        self.noti_label.pack(fill="x")

        self.list_title_lbl = tk.Label(self.fixed_top_frame, text="오늘 회차 목록 (버튼을 클릭하면 NFC 대상으로 지정됩니다)", font=("Arial", 12, "bold"), fg="#1e3a8a")
        self.list_title_lbl.pack(anchor="w", pady=(15, 5))

        # 2. 하단 독립 스크롤 영역
        scroll_outer_frame = tk.Frame(main_container)
        scroll_outer_frame.pack(fill="both", expand=True)

        self.list_canvas = tk.Canvas(scroll_outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_outer_frame, orient="vertical", command=self.list_canvas.yview)
        
        self.cards_container = tk.Frame(self.list_canvas)
        self.cards_container.bind(
            "<Configure>", 
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        )
        self.canvas_window = self.list_canvas.create_window((0, 0), window=self.cards_container, anchor="nw")
        
        self.list_canvas.bind(
            "<Configure>", 
            lambda e: self.list_canvas.itemconfig(self.canvas_window, width=e.width)
        )
        
        self.list_canvas.configure(yscrollcommand=scrollbar.set)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        def _on_mousewheel(e):
            self.list_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            
        self.list_canvas.bind("<Enter>", lambda _: self.list_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.list_canvas.bind("<Leave>", lambda _: self.list_canvas.unbind_all("<MouseWheel>"))

    def load_affiliation_list(self):
        if not self.controller or not hasattr(self.controller, 'client'):
            return
            
        try:
            res = self.controller.client.table("affiliations").select("id, name").order("id").execute()
            db_items = res.data if res and hasattr(res, 'data') else []
            
            self.affiliation_map = {} 
            combo_values = ["전체 보기"]
            
            for item in db_items:
                name_str = item.get("name")
                id_val = item.get("id")
                if name_str and id_val is not None:
                    combo_values.append(name_str)
                    self.affiliation_map[name_str] = id_val
            
            def update_combo():
                if hasattr(self, 'combo_affiliation') and self.combo_affiliation:
                    self.combo_affiliation['values'] = combo_values
                    if self.selected_affiliation_id == "all":
                        self.combo_affiliation.set("전체 보기")
                    else:
                        reverse_map = {v: k for k, v in self.affiliation_map.items()}
                        self.combo_affiliation.set(reverse_map.get(self.selected_affiliation_id, "전체 보기"))
            
            self.after(0, update_combo)
            
        except Exception as e:
            err_msg = f"소속 목록 연동 실패: {str(e)}"
            self.after(0, lambda: self.set_global_notification(err_msg, "error"))

    def on_affiliation_changed(self, event):
        selected_text = self.combo_affiliation.get()
        if selected_text == "전체 보기":
            self.selected_affiliation_id = "all"
        else:
            self.selected_affiliation_id = self.affiliation_map.get(selected_text, "all")
        self.refresh_today_dashboard()

    def start_nfc_service(self):
        try:
            #self.nfc_observer = NFCTagObserver(
            #    on_uuid_detected=self.handle_nfc_signal_received, 
            #    on_error_detected=self.handle_nfc_error_received
            #)
            #self.nfc_monitor = CardMonitor()
            #self.nfc_monitor.addObserver(self.nfc_observer)
            #self.set_global_noti("NFC 리더기 서비스 작동 중. 대상 회차를 선택하고 태그하세요.", "success")

            
            #self.reader_manager = ReaderManager(self.controller, ui_callback=self.set_global_noti("NFC 멀티 서비스 작동 시작"))
            #self.reader_manager.start_all_readers()
            # ==================================================================
            # [🔥 치명적 교정]: 함수의 실행 결과(None)가 아니라, 함수 주소(참조) 자체를 전달해야 합니다.
            # ==================================================================
            self.reader_manager = ReaderManager(controller=self.controller, ui_callback=self.set_global_noti)
            
            # 초기 기동 성공 알림 알리기
            self.set_global_noti("NFC 멀티 관제 서비스가 성공적으로 작동 시작되었습니다.", "success")
            self.reader_manager.start_all_readers()

        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda msg=err_msg: self.set_global_noti(f"NFC 서비스 초기화 실패 (리더기 연결 확인): {msg}", "error"))
            print((f"NFC 서비스 초기화 실패 (리더기 연결 확인): {err_msg}", "error"))
    def handle_nfc_error_received(self, error_msg):
        self.after(0, lambda msg=error_msg: self.set_global_noti(f"⚠️ 하드웨어 에러: {msg}", "error") )      

    def handle_nfc_signal_received(self, nfc_uid):
        self.after(0, lambda: self.execute_nfc_attendance_logic(nfc_uid))

    def execute_nfc_attendance_logic(self, nfc_uid):
        if not self.selected_occurrence_id:
            self.set_global_noti(f"감지된 UID: {nfc_uid} | 출석할 회차 카드를 먼저 마우스로 선택해주세요.", "error")
            return
            
        self.set_global_noti(f"NFC 카드 감지 (UID: {nfc_uid}). 처리 중...", "info")
        
        def task():
            if not self.controller: return
            try:
                res = self.controller.process_nfc_attendance(self.selected_occurrence_id, nfc_uid)
                msg = res.get("message", "NFC 출석 완료")
                self.after(0, lambda: self.set_global_noti(msg, "success"))
                self.after(0, self.refresh_selected_card_data)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.set_global_noti(msg, "error"))
        threading.Thread(target=task, daemon=True).start()

    def refresh_selected_card_data(self):
        if not self.selected_occurrence_id: return
        for card in self.card_widgets:
            if card.winfo_exists() and card.id == self.selected_occurrence_id:
                card.refresh_card_data()
                break

    def set_global_noti(self, text, status_type="info"):
        color, bg = "black", "#f3f4f6"
        if status_type == "success":
            color, bg = "#15803d", "#dcfce7"
        elif status_type == "error":
            color, bg = "#b91c1c", "#fef2f2"
        elif status_type == "info":
            color, bg = "#1d4ed8", "#dbeafe"
        self.lbl_noti.config(text=text, fg=color, bg=bg)

    def set_global_notification(self, message, noti_type="success"):
        self.noti_frame.pack(fill="x", pady=5)
        if noti_type == "error":
            self.noti_frame.config(bg="#fef2f2")
            self.noti_label.config(text=f"🛑 {message}", bg="#fef2f2", fg="#b91c1c")
        else:
            self.noti_frame.config(bg="#f0fdf4")
            self.noti_label.config(text=f"✅ {message}", bg="#f0fdf4", fg="#16a34a")

    def clear_global_notification(self):
        if hasattr(self, 'noti_label') and self.noti_label:
            self.noti_label.config(text="", bg="#ffffff")
        self.noti_frame.pack_forget()

    def refresh_today_dashboard(self):
        self.clear_global_notification()
        if hasattr(self, 'btn_refresh') and self.btn_refresh:
            self.btn_refresh.config(state="disabled")
        
        def task():
            if not self.controller: return
            try:
                self.after(0, self.load_affiliation_list)
                self.controller.ensure_today_occurrences()
                res = self.controller.fetch_today_occurrences(self.selected_affiliation_id)
                
                self.operation_date = res.get("date", "-")
                self.occurrence_items = res.get("items", [])
                
                self.after(0, self.render_dashboard_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self.set_global_notification(err_msg, "error"))
            finally:
                if hasattr(self, 'btn_refresh') and self.btn_refresh:
                    self.after(0, lambda: self.btn_refresh.config(state="normal"))
        threading.Thread(target=task, daemon=True).start()

    def handle_sync_today(self):
        if hasattr(self, 'btn_sync') and self.btn_sync:
            self.btn_sync.config(state="disabled")
        self.clear_global_notification()
        
        def task():
            if not self.controller: return
            try:
                data = self.controller.ensure_today_occurrences()
                res = self.controller.fetch_today_occurrences(self.selected_affiliation_id)
                self.operation_date = res.get("date", "-")
                self.occurrence_items = res.get("items", [])
                msg = f"오늘 회차 동기화 완료: 생성 {data.get('created_count', 0)}건, 실패 {data.get('failed_count', 0)}건"
                self.after(0, lambda: self.set_global_notification(msg, "success"))
                self.after(0, self.render_dashboard_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self.set_global_notification(err_msg, "error"))
            finally:
                if hasattr(self, 'btn_sync') and self.btn_sync:
                    self.after(0, lambda: self.btn_sync.config(state="normal"))
        threading.Thread(target=task, daemon=True).start()

    def render_dashboard_ui(self):
        self.summary_labels["date"].config(text=self.operation_date or "-")
        self.summary_labels["total_occ"].config(text=str(len(self.occurrence_items)))
        open_cnt = sum(1 for item in self.occurrence_items if item.get('status') == 'open')
        closed_cnt = sum(1 for item in self.occurrence_items if item.get('status') == 'closed')
        self.summary_labels["open_occ"].config(text=str(open_cnt))
        self.summary_labels["closed_occ"].config(text=str(closed_cnt))
        
        for widget in self.cards_container.winfo_children():
            widget.destroy()
            
        if not self.occurrence_items:
            tk.Label(self.cards_container, text="조회 범위 내 오늘 생성되거나 조건에 맞는 회차가 없습니다.", fg="#94a3b8", font=("Arial", 11), relief="solid", bd=1).pack(fill="x", pady=10)
            return
            
        self.card_widgets = []
        for item in self.occurrence_items:
            # 외부 모듈에서 인스턴스화하여 주입
            card = OccurrenceCardUi(self.cards_container, item, self.controller, self.set_global_notification)
            card.pack(fill="x", pady=8)
            
            if self.selected_occurrence_id and item.get('id') == self.selected_occurrence_id:
                card.set_active_style()
                
            self.card_widgets.append(card)
        self.list_canvas.update_idletasks()
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))

    def on_close_window(self):
        try:
            if self.reader_manager:
                self.reader_manager.stop_all_readers()
        except:
            pass
        self.destroy()