import queue
import threading
import time
from smartcard.System import readers
from smartcard.util import toHexString

# [교정]: smartcard의 최상위 예외 및 하드웨어 시스템 예외 클래스를 정확한 경로에서 임포트
from smartcard.Exceptions import NoCardException, SmartcardException
# ======================================================================
# [Producer] 개별 물리 NFC 리더기를 전담 마크하는 워커 스레드
# ======================================================================
class ReaderWorker(threading.Thread):
    def __init__(self, reader_obj, shared_queue):
        super().__init__()
        self.reader = reader_obj
        self.reader_name = reader_obj.name
        self.queue = shared_queue
        self.running = True
        self.daemon = True  
        
        self.last_uid = None
        self.last_tag_time = 0
        self.cooldown_seconds = 3.0  

    def run(self):
       
        print(f"[Worker 시작] 리더기 감시 작동 중: {self.reader_name}")
        
        while self.running:
            connection = None
            try:
                # 하드웨어 드라이버 과부하 방지를 위한 유휴 시간 확보
                time.sleep(0.3) 
                
                connection = self.reader.createConnection()
                connection.connect()
                
                # Mifare 카드 UID 획득 APDU 명령어
                GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]
                data, sw1, sw2 = connection.transmit(GET_UID_APDU)
                
                if sw1 == 0x90 and sw2 == 0x00:
                    nfc_uid = toHexString(data).replace(" ", "").upper()
                    current_time = time.time()
                    
                    # [논리 교정]: 동일 카드 중복 방지 체크
                    if nfc_uid == self.last_uid and (current_time - self.last_tag_time) < self.cooldown_seconds:
                        # 쿨다운 조건에 걸리면 가볍게 패스하되 연결은 정상 해제 유도
                        connection.disconnect()
                        continue
                        
                    print(f"[{self.reader_name}] 카드 감지 성공 -> UID: {nfc_uid}")
                    
                    # 큐에 카드 정보와 함께 리더기 객체 주소(참조)를 함께 넘겨주어
                    # 소비자가 처리에 성공했을 때만 워커의 쿨다운을 갱신할 수 있도록 논리적 징검다리 마련
                    self.queue.put({
                        "uid": nfc_uid, 
                        "reader_name": self.reader_name,
                        "worker_ref": self  # 레퍼런스 전달
                    })
                    
                connection.disconnect()
                # 카드가 계속 붙어있을 때 발생하는 초고속 루핑 및 CPU 점유율 과열 방지
                time.sleep(1.0)

            except NoCardException:
                # 카드가 올려져 있지 않은 정상적인 유휴 상태이므로 패스
                if connection:
                    try: connection.disconnect()
                    except: pass
                time.sleep(0.5) # 연결 시도 주기 최적화로 드라이버 고장 방지
                
            except SmartcardException as cse:
                # 리더기 연결 선 유실 등 하드웨어 통신 장애 상황 예외 처리
                print(f"⚠️ [{self.reader_name}] 하드웨어 통신 일시 오류: {str(cse)}")
                time.sleep(2.0) # 장애 발생 시 대기 시간을 늘려 시스템 안정 도모
                
            except Exception as e:
                print(f"🛑 [{self.reader_name}] 예기치 못한 스레드 오류: {str(e)}")
                time.sleep(1.0)

        print(f"[Worker 종료] 리더기 감시 중단: {self.reader_name}")


# ======================================================================
# [Manager & Consumer] 시스템 전체 리더기를 스캔/관리하고 큐를 소비하는 매니저
# ======================================================================
class ReaderManager:
    def __init__(self, controller, ui_callback):
        self.controller = controller
        self.ui_callback = ui_callback  # 대시보드 알림 연동 콜백
        self.shared_queue = queue.Queue()
        self.workers = []
        self.occurrence_id = None
        self.running = False
        self.consumer_thread = None
    def _safe_ui_callback(self, message, status_type="info"):
        """NoneType 'object is not callable' 에러를 완벽히 차단하는 안전 콜백 래퍼 메서드"""
        if self.ui_callback and callable(self.ui_callback):
            try:
                self.ui_callback(message, status_type)
            except Exception as e:
                self.ui_callback(f"[UI 콜백 실행 실패]: {str(e)} | 메시지: {message}")
        else:
            # UI 콜백 함수가 유실(None)되었을 때 프로그램이 죽지 않도록 콘솔 로그로 Fallback 처리
            print(f"[{status_type.upper()}] {message}")

    def set_occurrence_id(self, occurrence_id):
        self.occurrence_id = occurrence_id
        self.ui_callback(f"[ReaderManager] 타겟 출석 회차 변경 설정 완료 -> ID: {self.occurrence_id}")
        
        # [논리 보완]: 사용자가 회차를 선택하는 시점에 컨트롤러가 None 상태라면
        # [자가 치유 논리 2단계 보강]: ui_callback의 바인딩된 객체(App)를 추적하여 상위 계층의 controller를 강제 동기화
        if self.controller is None and self.ui_callback and hasattr(self.ui_callback, '__self__'):
            try:
                app_ref = self.ui_callback.__self__
                # 1안: App 자체의 컨트롤러 확인
                if hasattr(app_ref, 'controller') and app_ref.controller:
                    self.controller = app_ref.controller
                    app_ref.controller = self.controller # 부모 뷰도 동시 치료
                # 2안: App의 부모(Tk root 또는 Main 윈도우) 컴포넌트 구조 추적
                elif hasattr(app_ref, 'parent') and app_ref.parent and hasattr(app_ref.parent, 'controller') and app_ref.parent.controller:
                    self.controller = app_ref.parent.controller
                    app_ref.controller = self.controller
                            
                    if self.controller:
                       print("🎯 [ReaderManager] 런타임에 유실된 Controller를 완벽히 감지하여 자가 복구했습니다.")
            except Exception as bind_err:
                self.ui_callback(f"컨트롤러 동적 바인딩 복구 실패: {str(bind_err)}")

    def start_all_readers(self):
        self.running = True
        
        # 1. PC에 연결된 모든 물리 NFC 스마트카드 리더기 자동 스캔
        try:
            all_readers = readers()
        except Exception as e:
            self.ui_callback(f"리더기 드라이버 초기화 실패: {str(e)}", "error")
            return

        if not all_readers:
            self.ui_callback("💡 PC에 연결된 NFC 리더기를 찾을 수 없습니다. 연결을 확인하세요.", "error")
            return

        # 2. 발견된 리더기마다 독립적인 1:1 전담 마크 워커 스레드 생성 및 기동
        for r in all_readers:
            worker = ReaderWorker(r, self.shared_queue)
            worker.start()
            self.workers.append(worker)

        # 3. 큐에 쌓이는 데이터를 비동기로 소비해 줄 단일 전담 백그라운드 스레드 기동
        self.consumer_thread = threading.Thread(target=self._consume_queue_loop, daemon=True)
        self.consumer_thread.start()
        
        # [교정 완료]: 직접 호출 대신 안전 래퍼 메서드를 사용하여 'NoneType' object is not callable 원천 봉쇄
        self._safe_ui_callback(f"총 {len(all_readers)}대의 NFC 리더기 관제 스레드가 가동되었습니다.", "success")

    def _consume_queue_loop(self):
        #self.ui_callback("[Consumer 스레드] 큐 모니터링 루프 가동 시작")
        
        while self.running:
            try:
                try: task_data = self.shared_queue.get(timeout=1.0)
                except queue.Empty: continue 
                
                nfc_uid = task_data.get("uid")
                reader_name = task_data.get("reader_name")
                worker_ref = task_data.get("worker_ref")

                if not self.occurrence_id:
                    msg = f"🔔 [{reader_name}] 카드(UID: {nfc_uid}) 감지! 회차 카드를 먼저 선택하세요."
                    self._safe_ui_callback(msg, "error")
                    self.shared_queue.task_done()
                    continue

                # [자가 치유 논리 2단계]: 런타임 태깅 순간에도 컨트롤러를 재검사하여 최종 복구 시도
                if self.controller is None and hasattr(self.ui_callback, '__self__'):
                    app_ref = self.ui_callback.__self__
                    if hasattr(app_ref, 'controller') and app_ref.controller:
                        self.controller = app_ref.controller

                self._safe_ui_callback(f"⏳ [{reader_name}] 카드를 서버에 등록하는 중...", "info")

                # 주입 유효성 최종 정밀 검사
                if self.controller:
                    if hasattr(self.controller, 'process_nfc_attendance') and callable(getattr(self.controller, 'process_nfc_attendance')):
                        try:
                            res = self.controller.process_nfc_attendance(self.occurrence_id, nfc_uid)
                            server_msg = res.get("message", "출석 적재 성공")
                            
                            if worker_ref:
                                worker_ref.last_uid = nfc_uid
                                worker_ref.last_tag_time = time.time()
                                
                            self._safe_ui_callback(f"🟢 {server_msg} (인식 장치: {reader_name})", "success")
                            
                            if hasattr(self.controller, 'main_app') and self.controller.main_app:
                                self.controller.main_app.after(0, self.controller.main_app.refresh_selected_card_data)
                        except Exception as db_err:
                            self._safe_ui_callback(f"🛑 Supabase DB 통신 실패: {str(db_err)}", "error")
                    else:
                        fail_msg = f"🛑 시스템 설계 오류: 주입된 Controller에 'process_nfc_attendance' 메서드가 없습니다."
                        self._safe_ui_callback(fail_msg, "error")
                else:
                    # 복구 시도 후에도 실패한 경우에만 안전하게 에러 리포트 배출
                    self._safe_ui_callback("🛑 [연결 유실] 시스템 컨트롤러 바인딩이 유실되어 처리가 불가능합니다. 대시보드를 새로고침 해주세요.", "error")

                self.shared_queue.task_done()

            except Exception as loop_critical_err:
                self.ui_callback(f"루프 내부 치명적 예외 복구 완료: {str(loop_critical_err)}")
                time.sleep(1.0)

    def stop_all_readers(self):
        """프로그램 종료 시 열려있는 모든 하드웨어 자원 및 스레드를 우아하게 자진 해제(Graceful Shutdown)"""
        self.ui_callback("[ReaderManager] NFC 관제 시스템 종료 절차 돌입")
        self.running = False
        
        for worker in self.workers:
            worker.running = False
            
        self.workers.clear()
        self.ui_callback("모든 NFC 리더기 연결 스레드가 안전하게 닫혔습니다.", "info")