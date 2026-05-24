#nfc_tag_obsever.py
import time
from smartcard.CardMonitoring import  CardObserver
from smartcard.util import toHexString

# PC/SC 표준 NFC 태그 UID(UUID) 요청 APDU 명령어
GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]
# 1. 카드의 삽입/제거 이벤트를 처리할 Observer 클래스 정의
class NFCTagObserver(CardObserver):

    def __init__(self, on_uuid_detected=None, on_error_detected=None):
        super().__init__()
        self.last_uuid = None
        self.on_uuid_detected = on_uuid_detected  # 메인 프로그램으로 값을 보낼 채널
        self.on_error_detected = on_error_detected  # 추가: 통신 에러 발생 시 콜백 채널
        self.last_touch_time = 0  # 마지막으로 카드가 태그된 시간 저장
    def update(self, observable, actions):
        """카드가 연결되거나 해제될 때 자동으로 호출되는 콜백 메서드"""
        added_cards, removed_cards = actions

        # [CASE 1] 새로운 카드가 리더기에 접촉되었을 때
        for card in added_cards:
            try:
                # 카드와 연결 생성
                connection = card.createConnection()
                connection.connect()

                # UID 요청 APDU 송신
                data, sw1, sw2 = connection.transmit(GET_UID_APDU)

                # 상태 코드가 정상(0x90 0x00)인 경우
                if sw1 == 0x90 and sw2 == 0x00:
                    # pyscard의 util.toHexString을 사용하면 간결하게 16진수 문자열 변환 가능
                    current_uuid = toHexString(data).replace(" ", "")
                    # 현재 시간 측정
                    current_time = time.time()
                    
                    # 카드가 기존 것과 같더라도, 마지막 인식 후 3초가 지나지 않았다면 무시합니다.
                    if current_uuid == self.last_uuid and (current_time - self.last_touch_time) < 3.0:
                        # 3초 이내 연타 방지
                        connection.disconnect()
                        return

                    if current_uuid != self.last_uuid:
                        #print(f"[인식 완료] 태그 UUID: {current_uuid}")
                        self.last_uuid = current_uuid
                        # 추가: 콜백 함수가 등록되어 있다면, 찾은 UUID를 담아 호출합니다.
                        if self.on_uuid_detected:
                            self.on_uuid_detected(current_uuid)
                

                connection.disconnect()

            except Exception as e:
                error_msg = str(e)
                #print(f"[통신 에러] 카드 인식 중 오류 발생: {error_msg}")
                # 중요: 에러가 발생했음을 서비스 및 메인 UI 리스너 채널로 응답을 던져줍니다.
                if self.on_error_detected:
                    self.on_error_detected(error_msg)

        # [CASE 2] 카드가 리더기에서 떨어졌을 때
        for card in removed_cards:
            if self.last_uuid is not None:
                #print("[알림] 태그가 리더기에서 떨어졌습니다.")
                self.last_uuid = None
