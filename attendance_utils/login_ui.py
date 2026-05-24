#login_ui.py
import tkinter as tk

import threading


class LoginFrame(tk.Frame):
    
    def __init__(self, parent, on_login_click):
        super().__init__(parent)
        self.parent = parent
        self.on_login_click = on_login_click  # 로그인 버튼 클릭 시 실행할 컨트롤러의 함수
        
        self.parent.title("NFC 아이디카드 등록")
        self.parent.geometry("420x500")

        tk.Label(self, text="관리자 ID").pack(pady=(40, 0))
        self.id_entry = tk.Entry(self)
        self.id_entry.pack(fill="x", padx=40)

        tk.Label(self, text="비밀번호").pack(pady=(10, 0))
        self.pw_entry = tk.Entry(self, show="*")
        self.pw_entry.pack(fill="x", padx=40)

        # 로그인 버튼 클릭 시 entries의 값을 가져와 컨트롤러의 login 메서드로 전달
        # 버튼 연타 방지를 위해 인스턴스 변수(self.login_btn)로 지정
        self.login_btn = tk.Button(
            self,
            text="로그인",
            command=lambda: threading.Thread(
                target=self.on_login_click, 
                args=(self.id_entry.get(), self.pw_entry.get()), 
                daemon=True
            ).start()
        )
        self.login_btn.pack(pady=20) # 따로 pack을 해주어야 None 값이 안 들어갑니다.
        
        self.status = tk.Label(self, text="로그인 필요")
        self.status.pack(pady=10)

