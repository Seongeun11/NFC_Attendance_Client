#run.py
from tkinter import Tk

from attendance_utils.login_controller import LoginApp
from attendance_utils.main_controller import NfcApp


def mainapp():
    try:
        root = Tk()
        root.title("NFC 출석 관리 시스템 - 로그인")
        
        # 1. 로그인 창 크기로 초기화
        root.geometry("400x300") 
        root.resizable(False, False)

        # 🚀 LoginApp 인스턴스를 변수에 할당하여 참조할 수 있도록 설정
        login_app = LoginApp(root, on_success=None)

        # 🛠️ 로그인 성공 시 실행할 콜백 함수 정의
        def succeeded():
            #messagebox.showinfo("성공", "로그인에 성공했습니다!\n메인 대시보드로 전환합니다.")
            
            # [단계 1] 로그인 프레임 화면에서 완전히 제거 및 삭제
            if login_app.current_frame:
                login_app.current_frame.destroy()
            
            # [단계 2] 메인 화면 레이아웃에 맞게 창 크기 잠금 해제 및 확장
            root.resizable(True, True)
            root.geometry("650x850") 
            root.title("NFC 출석 관리 시스템 - 대시보드")

            # [단계 3] 비어있는 root 자리에 NfcApp(메인 대시보드)을 생성하여 채움
            global app
            app = NfcApp(root)

        # 정의한 콜백 함수를 LoginApp에 바인딩
        login_app.on_success = succeeded

        # Tkinter 메인 루프 실행
        root.mainloop()

    except Exception as e:
        print(f"[치명적 구동 에러] 시스템 초기화 실패: {e}")

if __name__ == "__main__":
    mainapp()