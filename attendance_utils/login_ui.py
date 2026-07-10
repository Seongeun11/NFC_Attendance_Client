#NFC_Attendance_Client\attendance_utils\login_ui.py
import tkinter as tk
import threading


class LoginFrame(tk.Frame):

    def __init__(self, parent, on_login_click):
        super().__init__(parent)

        self.parent = parent
        self.on_login_click = on_login_click

        self.parent.title("NFC 아이디카드 등록")
        self.parent.geometry("420x500")

        tk.Label(self, text="관리자 ID").pack(pady=(40, 0))

        self.id_entry = tk.Entry(self)
        self.id_entry.pack(fill="x", padx=40)

        tk.Label(self, text="비밀번호").pack(pady=(10, 0))

        self.pw_entry = tk.Entry(self, show="*")
        self.pw_entry.pack(fill="x", padx=40)

        # 엔터키 바인딩 (ID, PW 모두 동일한 함수 사용)
        self.id_entry.bind("<Return>", self._on_enter_login)
        self.pw_entry.bind("<Return>", self._on_enter_login)

        # 로그인 버튼
        self.login_btn = tk.Button(
            self,
            text="로그인",
            command=self.start_login
        )
        self.login_btn.pack(pady=20)

        self.status = tk.Label(
            self,
            text="로그인 필요\n엔터 또는 로그인 버튼을 눌러주세요."
        )
        self.status.pack(pady=10)

    def _on_enter_login(self, event):
        """엔터키 이벤트"""
        self.start_login()

    def start_login(self):
        """
        로그인 시작
        버튼과 엔터가 모두 이 함수만 호출한다.
        """

        # 중복 클릭 방지
        self.login_btn.config(state="disabled")

        self.status.config(
            text="웹 서버에 로그인을 시도합니다...",
            fg="blue"
        )

        # 화면 즉시 갱신
        self.update_idletasks()

        threading.Thread(
            target=self.on_login_click,
            args=(
                self.id_entry.get(),
                self.pw_entry.get()
            ),
            daemon=True
        ).start()