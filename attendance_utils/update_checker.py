import requests
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox

# 💡 [설정] 현재 실행 중인 프로그램의 버전을 정의합니다. (릴리즈 배포 시 이 값을 올림)
CURRENT_VERSION = "v1.3.0"

# 💡 [설정] 자신의 깃허브 사용자명과 레포지토리 이름을 적어주세요.
GITHUB_OWNER = "Seongeun11 "
GITHUB_REPO = "NFC_Attendance_Client"


def parse_version(version_str: str) -> tuple:
    """
    'v1.2.3' 또는 '1.2.3-beta' 형태의 버전 문자열을 
    비교 가능한 숫자형 튜플 (1, 2, 3)로 안전하게 정제합니다.
    """
    # 소문자 변환 후 맨 앞의 'v' 제거, 하이픈(-) 뒤의 프리릴리즈 텍스트 분리
    clean_str = version_str.lower().lstrip('v').split('-')[0]
    try:
        return tuple(map(int, clean_str.split('.')))
    except (ValueError, IndexError):
        return (0, 0, 0)


def _execute_update_check(root: tk.Tk):
    """[백그라운드 스레드 작동] 깃허브 최신 릴리즈 API를 호출하고 버전을 검증합니다."""
    # 깃허브 공식 최신 릴리즈 조회 엔드포인트
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    
    # 깃허브 API 호출 시 제한을 피하기 위한 표준 헤더 세팅
    headers = {
        "User-Agent": "NfcApp-Update-Checker/1.0",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # 타임아웃을 3초로 짧게 주어 네트워크 지연 시 프로그램 구동에 지장을 주지 않도록 함
        response = requests.get(url, headers=headers, timeout=3)
        
        # 릴리즈가 등록되지 않았거나(404), 레포지토리가 비공개인 경우 예외 없이 조용히 종료
        if response.status_code != 200:
            return

        data = response.json()
        latest_version_tag = data.get("tag_name", "v0.0.0")
        release_url = data.get("html_url", f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases")

        # 튜플 비교 논리를 통해 새 버전 여부 검증 (예: (1, 2, 0) > (1, 0, 0))
        if parse_version(latest_version_tag) > parse_version(CURRENT_VERSION):
            # 💡 중요: UI 작업(팝업 띄우기)은 메인 스레드에서 안전하게 실행되도록 구조화
            root.after(0, lambda: _show_update_popup(latest_version_tag, release_url))

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        # 오프라인 상태이거나 인터넷이 끊겨 있으면 사용자 방해 없이 조용히 넘어감
        print("[업데이트 확인 실패]: 인터넷에 연결되어 있지 않거나 깃허브 서버에 연결할 수 없습니다.")
    except Exception as e:
        print(f"[업데이트 확인 오류]: {str(e)}")


def _show_update_popup(latest_version: str, release_url: str):
    """[메인 UI 스레드 작동] 사용자에게 업데이트 선택 창(팝업)을 보여줍니다."""
    # askyesno는 '예(True)', '아니오(False)'를 반환하는 Tkinter 표준 메시지박스입니다.
    user_choice = messagebox.askyesno(
        "새로운 업데이트 발견",
        f"새로운 버전 [{latest_version}]이 릴리즈되었습니다.\n"
        f"현재 버전: {CURRENT_VERSION}\n\n"
        f"지금 다운로드 페이지(GitHub)로 이동하시겠습니까?\n"
        f"('아니오'를 누르면 현재 버전을 계속 사용합니다.)"
    )
    
    if user_choice:
        # 사용자가 '예'를 누르면 기본 웹 브라우저를 통해 깃허브 최신 다운로드 페이지를 열어줌
        webbrowser.open(release_url)


def check_for_updates_async(root: tk.Tk):
    """
    외부에서 호출하는 퍼블릭 함수입니다.
    메인 UI가 멈추지 않도록 비동기 스레드로 업데이트 체크를 시작합니다.
    """
    update_thread = threading.Thread(
        target=lambda: _execute_update_check(root),
        daemon=True  # 프로그램 종료 시 스레드도 함께 즉시 종료되도록 데몬 설정
    )
    update_thread.start()