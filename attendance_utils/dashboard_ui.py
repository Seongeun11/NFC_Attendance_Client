#dashboard_ui.py
import tkinter as tk
from tkinter import ttk
from datetime import datetime
import threading
from typing import Any # 타입 안정성 보강용

# NFC 모니터링 모듈 연결
from smartcard.CardMonitoring import CardMonitor
from attendance_utils.nfc_tag_observer import NFCTagObserver

# ==========================================
# 2. UI 헬퍼 및 포맷터 함수
# ==========================================
def format_status(status):
    mapping = {'scheduled': '대기 중', 'open': '진행 중', 'closed': '종료됨', 'archived': '기록 보관됨'}
    return mapping.get(status, status)

def format_recurrence(days, rec_type):
    if rec_type == 'none' or not days:
        return '없음(단발성)'
    ko_map = {'mon': '월', 'tue': '화', 'wed': '수', 'thu': '목', 'fri': '금', 'sat': '토', 'sun': '일'}
    # [교정]: join 내부에 완벽한 str 리스트만 전달되도록 정제 필터링 수행
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


# ==========================================
# 4. 개별 회차 아코디언/카드 패널 클래스
# ==========================================
class OccurrenceCardUi(tk.LabelFrame):
    def __init__(self, parent, item, controller, global_noti_cb):
        super().__init__(parent, text=f" {item.get('events', {}).get('name', '알 수 없는 행사')} ", font=("Arial", 11, "bold"))
        self.item = item
        self.id = item.get('id')
        self.controller = controller
        self.set_global_noti = global_noti_cb
        #[에러 수정]: 미선언 속성 에러(Unknown Attribute) 해결을 위한 초기 정의 추가
        self.expire_unit_var: Any = None
        self.expire_val_var: Any = None
        self.entry_val: Any = None
        # 내부 상태
        self.attendance_summary = {"total_checked_count": 0, "present_count": 0, "late_count": 0, "absent_count": 0}
        self.attendance_items = []
        self.missing_count = 0
        self.missing_items = []
        self.is_active = False  # 현재 이 카드가 NFC 활성 대상인지 여부

        self.init_ui()
        self.refresh_card_data()

    def init_ui(self):
        # 카드 프레임 자체나 하위 요소를 클릭해도 동작할 수 있게 기존 바인딩 유지
        self.bind("<Button-1>", self.on_card_selected)
        
        info_frame = tk.Frame(self)
        info_frame.pack(fill="x", side="top", pady=5, padx=5)

        ev = self.item.get('events') or {}
        # 외부 함수(parse_iso_time 등)의 예외 동작 방지용 안전 바인딩 처리
        start_t = self.item.get('start_time')
        if 'parse_iso_time' in globals():
            start_t = parse_iso_time(start_t)
            
        fmt_status_val = format_status(self.item.get('status')) if 'format_status' in globals() else self.item.get('status')
        fmt_rec_val = format_recurrence(ev.get('recurrence_days'), ev.get('recurrence_type')) if 'format_recurrence' in globals() else "데이터 없음"

        info_text = (
            f"회차 날짜: {self.item.get('occurrence_date')}  |  "
            f"시작 시간: {start_t}\n"
            f"상태: {fmt_status_val}  |  "
            f"반복 요일: {fmt_rec_val}\n"
            f"특별 행사: {'예' if ev.get('is_special_event') else '아니오'}  |  "
            f"지각 기준: {ev.get('late_threshold_min', 5)}분"
        )
        self.lbl_info = tk.Label(info_frame, text=info_text, justify="left", anchor="w")
        self.lbl_info.pack(side="left", fill="x", expand=True)
        self.lbl_info.bind("<Button-1>", self.on_card_selected)

        # 미출석 경고 및 결석 처리 버튼 영역 (우측 정렬)
        self.right_action_frame = tk.Frame(info_frame)
        self.right_action_frame.pack(side="right", anchor="ne", padx=5)
        
        self.lbl_missing_alert = tk.Label(self.right_action_frame, text="", fg="#b91c1c", font=("Arial", 9, "bold"))
        self.lbl_missing_alert.pack(pady=(0, 4))

        # -------------------------------------------------------------------------
        # 대상 회차 NFC 태그 선택 전용 버튼
        # -------------------------------------------------------------------------
        if self.item.get('status') == 'open':
            self.btn_select_tag = tk.Button(
                self.right_action_frame,
                text="NFC 태그",
                font=("Arial", 10, "bold"),
                bg="#3b82f6",
                fg="white",
                activebackground="#2563eb",
                activeforeground="white",
                relief="raised",
                padx=10,
                pady=4,
                command=self.on_card_selected
            )
            self.btn_select_tag.pack(side="right", padx=5)
        else:
            self.btn_select_tag = tk.Button(
                self.right_action_frame,
                text="선택 불가능",
                font=("Arial", 10),
                bg="#cbd5e1",
                fg="#94a3b8",
                state="disabled",
                relief="flat",
                padx=10,
                pady=4
            )
            self.btn_select_tag.pack(side="right", padx=5)
  
        # --- 출석 통계 대시보드 ---
        self.stat_frame = tk.LabelFrame(self, text="출석 현황 통계")
        self.stat_frame.pack(fill="x", pady=5)
        
        self.stat_labels = {}
        titles = [("present", "출석 인원"), ("late", "지각 인원"), ("absent", "결석 인원"), ("missing", "미출석 인원"), ("total", "전체 체크 인원")]
        for i, (key, title) in enumerate(titles):
            f = tk.Frame(self.stat_frame, relief="groove", bd=1)
            f.grid(row=0, column=i, padx=5, sticky="ew")
            self.stat_frame.columnconfigure(i, weight=1)
            tk.Label(f, text=title, font=("Arial", 9), fg="#666666").pack()
            lbl_val = tk.Label(f, text="0", font=("Arial", 11, "bold"))
            lbl_val.pack()
            self.stat_labels[key] = lbl_val

        # 통계 제어 버튼 컨트롤러
        btn_ctrl_frame = tk.Frame(self)
        btn_ctrl_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_ctrl_frame, text="출석 현황 새로고침", command=self.fetch_attendance_data).pack(side="left", padx=2)
        self.btn_toggle_att = ttk.Button(btn_ctrl_frame, text="출석 상세 보기", command=self.toggle_attendance_table)
        self.btn_toggle_att.pack(side="left", padx=2)
        
        ttk.Button(btn_ctrl_frame, text="미출석 목록 새로고침", command=self.fetch_missing_data).pack(side="left", padx=2)
        self.btn_toggle_mis = ttk.Button(btn_ctrl_frame, text="미출석 목록 보기", command=self.toggle_missing_table)
        self.btn_toggle_mis.pack(side="left", padx=2)

        # 확장 데이터 테이블 영역
        self.table_container = tk.Frame(self)
        self.table_container.pack(fill="x", pady=5)
        self.current_expanded = None

    def on_card_selected(self, event=None):
        """카드가 클릭되거나 전용 버튼이 눌리면 활성화 상태를 안전하게 바인딩합니다."""
        if not self.winfo_exists(): return
        if self.item.get('status') != 'open':
            self.set_global_noti("진행 중인 회차만 출석 태그 대상으로 지정할 수 있습니다.", "error")
            return

        if self.master and self.master.winfo_exists():
            for child in self.master.winfo_children():
                if isinstance(child, OccurrenceCardUi) and child.winfo_exists():
                    child.set_inactive_style()

        self.set_active_style()

        root_app = self.winfo_toplevel()
        target_app = self.find_today_operations_app()
        
        # Pylance 속성 할당 오류 방지를 위해 hasattr 검증 후 setattr로 안전 우회 처리
        if target_app and hasattr(target_app, 'selected_occurrence_id'):
            setattr(target_app, 'selected_occurrence_id', self.id)
        elif root_app:
            setattr(root_app, 'selected_occurrence_id', self.id)

        self.set_global_noti(f"🎯 선택 완료: [{self.item.get('events', {}).get('name', '')}] 회차가 지정되었습니다. NFC 카드를 태그해 주세요.", "success")

    def set_active_style(self):
        """카드가 선택되었을 때의 시각적 피드백 (존재 여부 안전 확인 추가)"""
        if not self.winfo_exists(): return
        self.config(relief="solid", bd=2)
        if hasattr(self, 'btn_select_tag') and self.btn_select_tag.winfo_exists():
            self.btn_select_tag.config(text="● 태그 대기 중", bg="#10b981", activebackground="#059669")

    def set_inactive_style(self):
        """다른 카드가 선택되어 원래 상태로 되돌릴 때 (존재 여부 안전 확인 추가)"""
        if not self.winfo_exists(): return
        self.config(relief="solid", bd=1)
        if hasattr(self, 'btn_select_tag') and self.btn_select_tag.winfo_exists():
            if self.item.get('status') == 'open':
                self.btn_select_tag.config(text="NFC 태그 대상 선택", bg="#3b82f6", activebackground="#2563eb")
            else:
                self.btn_select_tag.config(text="선택 불가능", bg="#cbd5e1")

    def find_today_operations_app(self):
        if not self.winfo_exists(): return None
        curr = self.master
        while curr:
            if curr.__class__.__name__ == "TodayOperationsApp":
                return curr
            curr = curr.master
        return None

    def on_unit_change(self, event=None):
        if not self.winfo_exists(): return
        # 정의되지 않은 컴포넌트 변수들에 대해 hasattr 안전 검사기 도입해 크래시 및 경고 차단
        if not (hasattr(self, 'expire_unit_var') and hasattr(self, 'expire_val_var') and hasattr(self, 'entry_val')):
            return
        
        unit = self.expire_unit_var.get()
        if unit == "unlimited":
            self.expire_val_var.set("0")
            self.entry_val.state(["disabled"])
        else:
            self.expire_val_var.set("1")
            self.entry_val.state(["!disabled"])

    def refresh_card_data(self):
        """외부 혹은 내부 태그 완료 시 독립적으로 실행하여 이 상자 데이터만 리프레시합니다."""
        threading.Thread(target=self._bg_refresh, daemon=True).start()

    def _bg_refresh(self):
        self.fetch_attendance_data()
        self.fetch_missing_data()

    def fetch_attendance_data(self):
        def task():
            # 비동기 구간 내 controller 존재 확인 방어 코드
            if not self.controller: return
            try:
                data = self.controller.fetch_attendance(self.id)
                self.attendance_summary = data.get("summary", self.attendance_summary)
                self.attendance_items = data.get("items", [])
                if self.winfo_exists() and self.master and self.master.winfo_exists():
                    self.master.after(0, self.update_stat_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.set_global_noti(msg, "error"))
        threading.Thread(target=task, daemon=True).start()
        
    def fetch_missing_data(self):
        def task():
            if not self.controller: return
            try:
                data = self.controller.fetch_missing(self.id)
                self.missing_count = data.get("count", 0)
                self.missing_items = data.get("items", [])
                if self.winfo_exists() and self.master and self.master.winfo_exists():
                    self.master.after(0, self.update_stat_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.set_global_noti(msg, "error"))
                    
        threading.Thread(target=task, daemon=True).start()

    def update_stat_ui(self):
        """방어적 코드 커스텀: 위젯 및 자식 컴포넌트 라벨 레이아웃 생존 여부 강제 필터링 검사"""
        if not self.winfo_exists(): return
       
        # 모든 내부 스태틱 라벨 컴포넌트의 가용성 전수 검사
        for key in ["present", "late", "absent", "missing", "total"]:
            if key not in self.stat_labels or not self.stat_labels[key].winfo_exists():
                return

        self.stat_labels["present"].config(text=str(self.attendance_summary.get("present_count", 0)))
        self.stat_labels["late"].config(text=str(self.attendance_summary.get("late_count", 0)))
        self.stat_labels["absent"].config(text=str(self.attendance_summary.get("absent_count", 0)))
        self.stat_labels["missing"].config(text=str(self.missing_count))
        self.stat_labels["total"].config(text=str(self.attendance_summary.get("total_checked_count", 0)))

        if self.lbl_missing_alert.winfo_exists():
            if self.missing_count > 0:
                self.lbl_missing_alert.config(text=f"미출석 인원 {self.missing_count}명이 남아 있습니다.")
            else:
                self.lbl_missing_alert.config(text="")
        
        # 만약 데이터 테이블 상세가 열려 있는 상태라면 테이블도 동시 갱신
        if self.current_expanded == 'attendance':
            self.render_attendance_table()
        elif self.current_expanded == 'missing':
            self.render_missing_table()
            
    def toggle_attendance_table(self):
        if not self.winfo_exists() or not self.table_container.winfo_exists(): return
        if self.current_expanded == 'attendance':
            self.clear_expanded_table()
        else:
            self.clear_expanded_table()
            self.current_expanded = 'attendance'
            self.btn_toggle_att.config(text="출석 상세 닫기")
            self.render_attendance_table()

    def toggle_missing_table(self):
        if not self.winfo_exists() or not self.table_container.winfo_exists(): return
        if self.current_expanded == 'missing':
            self.clear_expanded_table()
        else:
            self.clear_expanded_table()
            self.current_expanded = 'missing'
            self.btn_toggle_mis.config(text="미출석 목록 닫기")
            self.render_missing_table()

    def clear_expanded_table(self):
        if not self.winfo_exists() or not self.table_container.winfo_exists(): return
        for w in self.table_container.winfo_children():
            if w.winfo_exists(): w.destroy()
        if self.btn_toggle_att.winfo_exists(): self.btn_toggle_att.config(text="출석 상세 보기")
        if self.btn_toggle_mis.winfo_exists(): self.btn_toggle_mis.config(text="미출석 목록 보기")
        self.table_container.pack_forget()
        self.current_expanded = None
        self.update_idletasks()

    def render_attendance_table(self):
        if not self.winfo_exists() or not self.table_container.winfo_exists(): return

        # 기존에 그려져 있던 테이블 위젯 청소 (중복 생성 방지)
        for w in self.table_container.winfo_children():
            if w.winfo_exists(): w.destroy()

        self.table_container.pack(fill="x", pady=5)
        if not self.attendance_items:
            tk.Label(self.table_container, text="출석 상세 데이터가 없습니다.", fg="#94a3b8").pack()
            return
        
        columns = ("name", "student_id", "status", "method", "check_time")
        tree = ttk.Treeview(self.table_container, columns=columns, show="headings", height=6)
        tree.heading("name", text="이름")
        tree.heading("student_id", text="학번")
        tree.heading("status", text="상태")
        tree.heading("method", text="방식")
        tree.heading("check_time", text="체크 시각")
        
        tree.column("name", width=80, anchor="center")
        tree.column("student_id", width=90, anchor="center")
        tree.column("status", width=80, anchor="center")
        tree.column("method", width=80, anchor="center")
        tree.column("check_time", width=150, anchor="center")

        for att in self.attendance_items:
            profiles = att.get("profiles") or {}
            full_name = profiles.get("full_name", "-")
            student_id = profiles.get("student_id", "-")

            fmt_as = format_att_status(att.get("status")) if 'format_att_status' in globals() else att.get("status")
            
            raw_check_time = att.get("check_time")
            if raw_check_time and 'parse_iso_time' in globals():
                fmt_ct = parse_iso_time(raw_check_time)
            else:
                fmt_ct = raw_check_time or "-"

            tree.insert("", "end", values=(
                full_name,
                student_id,
                fmt_as,
                att.get("method") or "-",
                fmt_ct
            ))
        tree.pack(fill="x")

    def render_missing_table(self):
        if not self.winfo_exists() or not self.table_container.winfo_exists(): return
        
        # 기존에 그려져 있던 테이블 위젯 청소 (중복 생성 방지)
        for w in self.table_container.winfo_children():
            if w.winfo_exists(): w.destroy()

        self.table_container.pack(fill="x", pady=5)
        if not self.missing_items:
            tk.Label(self.table_container, text="미출석 인원이 없습니다.", fg="#94a3b8").pack()
            return
        
        columns = ("name", "student_id")
        tree = ttk.Treeview(self.table_container, columns=columns, show="headings", height=5)
        tree.heading("name", text="이름")
        tree.heading("student_id", text="학번")
        tree.column("name", width=150, anchor="center")
        tree.column("student_id", width=150, anchor="center")

        for mis in self.missing_items:
            tree.insert("", "end", values=(mis.get("full_name"), mis.get("student_id")))
        tree.pack(fill="x")


# ==========================================
# 5. 메인 최상위 뷰 클래스 (Main Application)
# ==========================================
class TodayOperationsApp(tk.Frame):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent
        
        self.controller = None
        self.operation_date = ""
        self.occurrence_items = []
        self.card_widgets = []
        
        self.nfc_monitor = None
        self.nfc_observer = None
        self.selected_occurrence_id = None 
        
        self.init_ui()
        self.start_nfc_service()
        try:
            if hasattr(self, "protocol"):
                getattr(self, "protocol")("WM_DELETE_WINDOW", self.on_close_window)
        except Exception:
            pass
            
    def init_ui(self):
        # [교정]: 전체 창 스크롤을 완전히 없애고 상하 고정 분할 구조로 변경
        main_container = tk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=15, pady=15)

        # ---------------------------------------------------------
        # 1. 상단 고정 영역 (운영 대시보드 정보 및 제어 패널)
        # ---------------------------------------------------------
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
        
        self.btn_sync = ttk.Button(action_panel, text="오늘 회차 동기화", command=self.handle_sync_today)
        self.btn_sync.pack(side="left", padx=3)
        
        self.btn_refresh = ttk.Button(action_panel, text="새로고침", command=self.refresh_today_dashboard)
        self.btn_refresh.pack(side="left", padx=3)

        self.noti_frame = tk.Frame(self.fixed_top_frame)
        self.noti_label = tk.Label(self.noti_frame, text="", wraplength=750, justify="left", font=("Arial", 10))
        self.noti_label.pack(fill="x")

        self.list_title_lbl = tk.Label(self.fixed_top_frame, text="오늘 회차 목록 (버튼을 클릭하면 NFC 대상으로 지정됩니다)", font=("Arial", 12, "bold"), fg="#1e3a8a")
        self.list_title_lbl.pack(anchor="w", pady=(15, 5))

        # ---------------------------------------------------------
        # 2. 하단 독립 스크롤 영역 (오늘회차 목록 컨테이너)
        # ---------------------------------------------------------
        scroll_outer_frame = tk.Frame(main_container)
        scroll_outer_frame.pack(fill="both", expand=True)

        self.list_canvas = tk.Canvas(scroll_outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_outer_frame, orient="vertical", command=self.list_canvas.yview)
        
        # 실제 내부 아이템 카드 박스들이 배치될 내부 프레임 컨테이너
        self.cards_container = tk.Frame(self.list_canvas)
        
        # 내부 컨테이너 내부 크기 변화 감지 시 스크롤바 바운더리 실시간 연동 업데이트
        self.cards_container.bind(
            "<Configure>", 
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        )
        self.canvas_window = self.list_canvas.create_window((0, 0), window=self.cards_container, anchor="nw")
        
        # 윈도우 창 크기가 늘어날 때 내부 카드들의 가로폭도 캔버스 크기에 딱 맞춤
        self.list_canvas.bind(
            "<Configure>", 
            lambda e: self.list_canvas.itemconfig(self.canvas_window, width=e.width)
        )
        
        self.list_canvas.configure(yscrollcommand=scrollbar.set)

        self.list_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 마우스 포인터가 오늘회차목록컨테이너 내부 영역에 들어와 있을 때만 휠 연동 기능 작동
        def _on_mousewheel(e):
            self.list_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            
        self.list_canvas.bind("<Enter>", lambda _: self.list_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.list_canvas.bind("<Leave>", lambda _: self.list_canvas.unbind_all("<MouseWheel>"))

    def start_nfc_service(self):
        try:
            self.nfc_observer = NFCTagObserver(
                on_uuid_detected=self.handle_nfc_signal_received, 
                on_error_detected=self.handle_nfc_error_received
            )
            self.nfc_monitor = CardMonitor()
            self.nfc_monitor.addObserver(self.nfc_observer)
            self.set_global_noti("NFC 리더기 서비스 작동 중. 대상 회차를 선택하고 태그하세요.", "success")
        except Exception as e:
            err_msg = str(e)
            self.after(0, lambda msg=err_msg: self.set_global_noti(f"NFC 서비스 초기화 실패 (리더기 연결 확인): {msg}", "error"))
     
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
                # 전체 대시보드 리셋 대신 선택된 카드만 표적 리프레시 호출
                self.after(0, self.refresh_selected_card_data)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.set_global_noti(msg, "error"))
        threading.Thread(target=task, daemon=True).start()

    def refresh_selected_card_data(self):
        """전체 UI 카드를 재생성하지 않고 선택된 박스의 위젯 내부만 갱신합니다."""
        if not self.selected_occurrence_id:
            return
            
        # 1. 렌더링되어 관리 중인 카드 위젯 배열을 전수 조사합니다.
        for card in self.card_widgets:
            if card.winfo_exists() and card.id == self.selected_occurrence_id:
                # 2. 해당 박스 컴포넌트의 독자 리프레시를 가동합니다. (트리뷰 렌더러까지 내부 포함)
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
        """새로고침 버튼 클릭 시에만 상단을 초기화하고 전체 카드를 받아와 동기화 빌드합니다."""
        self.clear_global_notification()
        if hasattr(self, 'btn_refresh') and self.btn_refresh:
            self.btn_refresh.config(state="disabled")
        
        def task():
            if not self.controller: return
            try:
                self.controller.ensure_today_occurrences()
                res = self.controller.fetch_today_occurrences()
                
                self.operation_date = res.get("date", "-")
                self.occurrence_items = res.get("items", [])
                
                self.after(0, self.render_dashboard_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.after(0, lambda: self.set_global_notification(msg, "error")))
                
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
                res = self.controller.fetch_today_occurrences()
                self.operation_date = res.get("date", "-")
                self.occurrence_items = res.get("items", [])
                msg = f"오늘 회차 동기화 완료: 생성 {data.get('created_count', 0)}건, 실패 {data.get('failed_count', 0)}건"
                self.after(0, lambda: self.set_global_notification(msg, "success"))
                self.after(0, self.render_dashboard_ui)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.after(0, lambda: self.set_global_notification(msg, "error")))
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
            tk.Label(self.cards_container, text="오늘 생성된 회차가 없습니다.", fg="#94a3b8", font=("Arial", 11), relief="solid", bd=1).pack(fill="x", pady=10)
            return
            
        self.card_widgets = []
        for item in self.occurrence_items:
            card = OccurrenceCardUi(self.cards_container, item, self.controller, self.set_global_notification)
            card.pack(fill="x", pady=8)
            
            # 이전 선택 아이디가 유효하게 남아있다면 스타일 복원 타겟팅
            if self.selected_occurrence_id and item.get('id') == self.selected_occurrence_id:
                card.set_active_style()
                
            self.card_widgets.append(card)
        # [교정]: 아이템 동적 재생성 후 스크롤 캔버스 바운더리 즉시 재계산 강제 적용
        self.list_canvas.update_idletasks()
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))

    def on_close_window(self):
        try:
            if self.nfc_monitor and self.nfc_observer:
                self.nfc_monitor.deleteObserver(self.nfc_observer)
        except:
            pass
        self.destroy()