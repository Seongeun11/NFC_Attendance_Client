import threading
import time
import logging
from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

class MultiNfcReaderManager:
    def __init__(self, attendance_controller, occurrence_id: str, ui_callback=None):
        """
        :param attendance_controller: 이전에 만든 Supabase RPC 기반 AttendanceController 인스턴스
        :param occurrence_id: 현재 활성화된 출석 회차 ID (UUID)
        :param ui_callback: UI 화면에 실시간 로그나 성공 알림을 전송할 콜백 함수 (옵션)
        """
        self.controller = attendance_controller
        self.occurrence_id = occurrence_id
        self.ui_callback = ui_callback
        self.is_running = False
        self.threads = []
        self.active_readers = []

    def log_message(self, message: str):
        """UI 콜백 및 표준 로그 전송"""
        if self.ui_callback:
            self.ui_callback(message)
        print(f"[MultiNFC] {message}")

    def _reader_worker(self, reader_object, reader_index: int):
        """
        각 ACR122U 리더기마다 1:1로 매핑되어 독립적으로 실행되는 핵심 작업 스레드
        """
        reader_name = f"ACR122U [장치 #{reader_index}]"
        self.log_message(f"{reader_name} 모니터링 스레드가 시작되었습니다.")
        
        last_uid = None
        last_tag_time = 0

        while self.is_running:
            try:
                # 1. 리더기 연결 검사 및 카드 대기
                connection = reader_object.createConnection()
                connection.connect()

                # 2. ACR122U 표준 APDU 명령어를 송신하여 카드 UID 추출 (Get Data Command)
                # GET_DATA_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]
                GET_DATA = [0xFF, 0xCA, 0x00, 0x00, 0x00]
                data, sw1, sw2 = connection.transmit(GET_DATA)

                # 명령어 성공 플래그 (0x90 0x00) 검증
                if sw1 == 0x90 and sw2 == 0x00:
                    nfc_uid = toHexString(data).replace(" ", "").lower()
                    current_time = time.time()

                    # 💡 동일 카드가 리더기에 계속 올려져 있어 연속 중복 출석 처리되는 현상 방지 (3초 가드타임)
                    if nfc_uid == last_uid and (current_time - last_tag_time) < 3.0:
                        time.sleep(0.5)
                        continue

                    last_uid = nfc_uid
                    last_tag_time = current_time

                    self.log_message(f"▶ {reader_name} 카드 감지! UID: {nfc_uid}")
                    
                    # 3. 비동기식 Supabase RPC 단일 트랜잭션 호출 (100명 동시성 대응)
                    # 별도의 워커 스레드에서 돌고 있으므로 다른 리더기의 센싱을 전혀 방해하지 않음
                    threading.Thread(
                        target=self._execute_attendance_rpc, 
                        args=(nfc_uid, reader_name), 
                        daemon=True
                    ).start()

            except NoCardException:
                # 카드가 리더기에 없는 일상적인 상태이므로 무시하고 루프 진행
                last_uid = None  # 카드를 떼면 중복 방지 리셋
                time.sleep(0.2)   # CPU 과점 방지를 위한 소량의 휴지기
            except CardConnectionException as e:
                # 리더기 통신 일시 오류 시 재연결 시도
                time.sleep(1.0)
            except Exception as e:
                logging.error(f"{reader_name} 치명적 오류: {str(e)}")
                time.sleep(1.0)

        self.log_message(f"■ {reader_name} 모니터링 스레드가 종료되었습니다.")

    def _execute_attendance_rpc(self, nfc_uid: str, reader_name: str):
        """Supabase와 통신하여 출석을 확정짓는 격리된 네트워크 워커"""
        result = self.controller.process_nfc_attendance(
            occurrence_id=self.occurrence_id, 
            nfc_uid=nfc_uid
        )
        # 처리 결과를 UI 혹은 로그에 출력
        status_prefix = "[성공]" if result["success"] else "[실패]"
        self.log_message(f"{status_prefix} {reader_name} -> {result['message']}")

    def start_monitoring(self):
        """PC에 연결된 모든 ACR122U 리더기를 탐지하여 일제히 작동시킵니다."""
        try:
            available_readers = readers()
        except Exception as e:
            self.log_message(f"리더기 드라이버 레이어 로드 실패: {str(e)}")
            return

        if not available_readers:
            self.log_message("❌ 연결된 ACR122U NFC 리더기를 찾을 수 없습니다. USB 선을 확인하세요.")
            return

        self.is_running = True
        self.active_readers = available_readers
        self.log_message(f"총 {len(available_readers)}개의 NFC 리더기를 감지했습니다. 시스템을 시작합니다.")

        # 탐지된 리더기 개수만큼 스레드를 생성하여 병렬 가속 구동
        for index, reader in enumerate(available_readers):
            t = threading.Thread(
                target=self._reader_worker, 
                args=(reader, index), 
                daemon=True # 프로그램 종료 시 함께 안전하게 소멸되도록 설정
            )
            self.threads.append(t)
            t.start()

    def stop_monitoring(self):
        """동작 중인 모든 다중 리더기 스레드를 안전하게 자원 해제하고 정지합니다."""
        self.log_message("다중 리더기 시스템 종료 절차를 시작합니다...")
        self.is_running = False
        self.threads.clear()
        self.active_readers.clear()