#attendance_utils\occurrence_card_ui.py
import tkinter as tk
from tkinter import ttk
import threading
from typing import Any

# 유틸리티 함수 명시적 임포트
from attendance_utils.ui_utils import format_status, format_recurrence, format_att_status, parse_iso_time

class OccurrenceCardUi(tk.LabelFrame):
    def __init__(self, parent, item, controller, global_noti_cb):
        super().__init__(parent, text=f" {item.get('events', {}).get('name', '알 수 없는 행사')} ", font=("Arial", 11, "bold"))
        self.item = item
        self.id = item.get('id')
        self.controller = controller
        self.set_global_noti = global_noti_cb
        
        # 속성 에러 방지를 위한 변수 선언 초기화
        self.expire_unit_var: Any = tk.StringVar(value="unlimited")
        self.expire_val_var: Any = tk.StringVar(value="0")
        self.entry_val: Any = None
        
        # 내부 상태
        self.attendance_summary = {"total_checked_count": 0, "present_count": 0, "late_count": 0, "absent_count": 0}
        self.attendance_items = []
        self.missing_count = 0
        self.missing_items = []
        self.is_active = False 

        self.init_ui()
        self.refresh_card_data()

    def init_ui(self):
        self.bind("<Button-1>", self.on_card_selected)
        
        info_frame = tk.Frame(self)
        info_frame.pack(fill="x", side="top", pady=5, padx=5)

        ev = self.item.get('events') or {}
        aff_data = ev.get('affiliations') or {}
        
        affiliation_name = aff_data.get('name') or "소속 없음"
        start_t = parse_iso_time(self.item.get('start_time'))
            
        fmt_status_val = format_status(self.item.get('status'))
        fmt_rec_val = format_recurrence(ev.get('recurrence_days'), ev.get('recurrence_type'))
        
        # 세로 프레임 컨테이너
        text_container = tk.Frame(info_frame)
        text_container.pack(side="left", fill="x", expand=True)
        text_container.bind("<Button-1>", self.on_card_selected)

        # 소속 라벨 파란색 강조
        aff_text = f"행사 소속: [{affiliation_name}]"
        self.lbl_aff = tk.Label(
            text_container, 
            text=aff_text, 
            justify="left", 
            anchor="w", 
            fg="#1d4ed8",          
            font=("Arial", 10, "bold")
        )
        self.lbl_aff.pack(side="top", fill="x", anchor="w")
        self.lbl_aff.bind("<Button-1>", self.on_card_selected)

        # 상세 안내 텍스트
        info_text = (
            f"회차 날짜: {self.item.get('occurrence_date')}\n"
            f"시작 시간: {start_t}  |  상태: {fmt_status_val}\n"
            f"반복 요일: {fmt_rec_val}\n"
            f"특별 행사: {'예' if ev.get('is_special_event') else '아니오'}  |  지각 기준: {ev.get('late_threshold_min', 5)}분"
        )
        self.lbl_info = tk.Label(text_container, text=info_text, justify="left", anchor="w")
        self.lbl_info.pack(side="top", fill="x", expand=True)
        self.lbl_info.bind("<Button-1>", self.on_card_selected)

        # 우측 액션 레이아웃
        self.right_action_frame = tk.Frame(info_frame)
        self.right_action_frame.pack(side="right", anchor="ne", padx=5)
        
        self.lbl_missing_alert = tk.Label(self.right_action_frame, text="", fg="#b91c1c", font=("Arial", 9, "bold"))
        self.lbl_missing_alert.pack(pady=(0, 4))

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

        btn_ctrl_frame = tk.Frame(self)
        btn_ctrl_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_ctrl_frame, text="출석 현황 새로고침", command=self.fetch_attendance_data).pack(side="left", padx=2)
        self.btn_toggle_att = ttk.Button(btn_ctrl_frame, text="출석 상세 보기", command=self.toggle_attendance_table)
        self.btn_toggle_att.pack(side="left", padx=2)
        
        ttk.Button(btn_ctrl_frame, text="미출석 목록 새로고침", command=self.fetch_missing_data).pack(side="left", padx=2)
        self.btn_toggle_mis = ttk.Button(btn_ctrl_frame, text="미출석 목록 보기", command=self.toggle_missing_table)
        self.btn_toggle_mis.pack(side="left", padx=2)

        self.table_container = tk.Frame(self)
        self.table_container.pack(fill="x", pady=5)
        self.current_expanded = None

    def on_card_selected(self, event=None):
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
        
        if target_app and hasattr(target_app, 'selected_occurrence_id'):
            setattr(target_app, 'selected_occurrence_id', self.id)
        elif root_app:
            setattr(root_app, 'selected_occurrence_id', self.id)

        self.set_global_noti(f"🎯 선택 완료: [{self.item.get('events', {}).get('name', '')}] 회차가 지정되었습니다. NFC 카드를 태그해 주세요.", "success")

    def set_active_style(self):
        if not self.winfo_exists(): return
        self.config(relief="solid", bd=2)
        if hasattr(self, 'btn_select_tag') and self.btn_select_tag.winfo_exists():
            self.btn_select_tag.config(text="● 태그 대기 중", bg="#10b981", activebackground="#059669")

    def set_inactive_style(self):
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
        if not (hasattr(self, 'expire_unit_var') and hasattr(self, 'expire_val_var') and hasattr(self, 'entry_val')):
            return
        
        unit = self.expire_unit_var.get()
        if unit == "unlimited":
            self.expire_val_var.set("0")
            if self.entry_val: self.entry_val.state(["disabled"])
        else:
            self.expire_val_var.set("1")
            if self.entry_val: self.entry_val.state(["!disabled"])

    def refresh_card_data(self):
        threading.Thread(target=self._bg_refresh, daemon=True).start()

    def _bg_refresh(self):
        self.fetch_attendance_data()
        self.fetch_missing_data()

    def fetch_attendance_data(self):
        def task():
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
        if not self.winfo_exists(): return
       
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
            fmt_as = format_att_status(att.get("status"))
            
            raw_check_time = att.get("check_time")
            fmt_ct = parse_iso_time(raw_check_time) if raw_check_time else "-"

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