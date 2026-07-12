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
       
        #print(f"[Worker 시작] 리더기 감시 작동 중: {self.reader_name}")
        
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
                        
                    #print(f"[{self.reader_name}] 카드 감지 성공 -> UID: {nfc_uid}")
                    
                    # 큐에 카드 정보와 함께 리더기 객체 주소(참조)를 함께 넘겨주어
                    # 소비자가 처리에 성공했을 때만 워커의 쿨다운을 갱신할 수 있도록 논리적 징검다리 마련
                    self.queue.put({
                        "uid": nfc_uid, 
                        "reader_name": self.reader_name,
                        "worker_ref": self  # 레퍼런스 전달
                    })
                    
                connection.disconnect()
                # 카드가 계속 붙어있을 때 발생하는 초고속 루핑 및 CPU 점유율 과열 방지
                time.sleep(2.0)

            except NoCardException:
                # 카드가 올려져 있지 않은 정상적인 유휴 상태이므로 패스
                if connection:
                    try: connection.disconnect()
                    except: pass
                time.sleep(0.5) # 연결 시도 주기 최적화로 드라이버 고장 방지
                
            except SmartcardException as cse:
                # 리더기 연결 선 유실 등 하드웨어 통신 장애 상황 예외 처리
                #print(f"⚠️ [{self.reader_name}] 하드웨어 통신 일시 오류: {str(cse)}")
                time.sleep(2.0) # 장애 발생 시 대기 시간을 늘려 시스템 안정 도모
                
            except Exception as e:
                #print(f"🛑 [{self.reader_name}] 예기치 못한 스레드 오류: {str(e)}")
                time.sleep(1.0)

        #print(f"[Worker 종료] 리더기 감시 중단: {self.reader_name}")


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

        # [교정]: 현재 활성화된 UI 탭 모드 플래그 (기본값은 출석 관리)
        self.current_mode = "ATTENDANCE" 
        
    def set_active_mode(self, mode_string):
        """현재 활성화된 UI 탭 모드를 설정 ('REGISTRATION' 또는 'ATTENDANCE')"""
        self.current_mode = mode_string
        print(f"[ReaderManager] 동작 모드가 변경되었습니다: {self.current_mode}")

    def _safe_ui_callback(self, message, status_type="info"):
        """NoneType 'object is not callable' 에러를 완벽히 차단하는 안전 콜백 래퍼 메서드"""
        if self.ui_callback and callable(self.ui_callback):
            try:
                self.ui_callback(message, status_type)
            except Exception as e:
                print(f"[UI 콜백 내부 오류]: {str(e)} | 메시지: {message}")
        else:
            # UI 콜백 함수가 유실(None)되거나 호출 불가능할 때 콘솔 출력으로 대체
            print(f"[{status_type.upper()}] {message}")

    def set_occurrence_id(self, occurrence_id):
        self.occurrence_id = occurrence_id
        self._safe_ui_callback(f"[ReaderManager] 타겟 출석 회차 변경 설정 완료 -> ID: {self.occurrence_id}")
        
        

        # [자가 치유 논리 2단계 보강]: ui_callback의 바인딩된 객체(App)를 추적하여 상위 계층의 controller를 강제 동기화
        if self.controller is None and self.ui_callback and hasattr(self.ui_callback, '__self__'):
            try:
                app_ref = self.ui_callback.__self__
                if hasattr(app_ref, 'controller') and app_ref.controller:
                    self.controller = app_ref.controller
                    app_ref.controller = self.controller 
                elif hasattr(app_ref, 'parent') and app_ref.parent and hasattr(app_ref.parent, 'controller') and app_ref.parent.controller:
                    self.controller = app_ref.parent.controller
                    app_ref.controller = self.controller
                            
                if self.controller:
                     print("🎯 [ReaderManager] 런타임에 유실된 Controller를 완벽히 감지하여 자가 복구했습니다.")
            except Exception as bind_err:
                self._safe_ui_callback(f"컨트롤러 동적 바인딩 복구 실패: {str(bind_err)}", "error")

        # ======================================================================
        # 💡 [교정 단계 2]: 모드 판별 및 의존성 방어 코드 삽입
        # ======================================================================
        # 카드 등록 모드이거나 예약어 상태일 때는 무거운 출석 캐시 빌드를 건너뜁니다.
        if self.current_mode == "REGISTRATION" or self.occurrence_id == "CARD_REGISTRATION_MODE":
            print("[ReaderManager] 카드 등록 모드이므로 출석 로컬 캐시 빌드를 건너뜁니다.")
            return

        # 복구 시도 후에도 컨트롤러가 없거나, 캐시 빌드 메서드가 없는 Mock 컨트롤러인 경우 방어
        if self.controller is None or not hasattr(self.controller, 'initialize_local_cache'):
            print("⚠️ [경고] 유효한 출석 Controller가 지정되지 않아 실시간 DB 모드로 작동합니다.")
            return

        # ======================================================================
        # 💡 [교정 단계 3]: 모든 방어막을 통과한 뒤 안전하게 캐시 빌드 호출
        # ======================================================================
        print("🔄 출석 체크를 위한 로컬 캐시를 빌드 중입니다...")
        try:
            cache_success = self.controller.initialize_local_cache(self.occurrence_id)
            if not cache_success:
                print("⚠️ 캐시 초기화 실패: 실시간 서버 조회 모드로 동작합니다. (태그 속도가 느려질 수 있음)")
            else:
                print("✅ 로컬 캐시 로드 완료! 고속 NFC 출석 준비가 되었습니다.")
        except Exception as cache_err:
            print(f"🛑 캐시 실행 중 예외 발생 (실시간 모드 전환): {str(cache_err)}")

    def start_all_readers(self):
        self.running = True
        
        # 1. PC에 연결된 모든 물리 NFC 스마트카드 리더기 자동 스캔
        try:
            all_readers = readers()
        except Exception as e:
            self._safe_ui_callback(f"리더기 드라이버 초기화 실패: {str(e)}", "error")
            return

        if not all_readers:
            self._safe_ui_callback("💡 PC에 연결된 NFC 리더기를 찾을 수 없습니다. 연결을 확인하세요.", "error")
            return

        # 2. 발견된 리더기마다 독립적인 1:1 전담 마크 워커 스레드 생성 및 기동
        for r in all_readers:
            worker = ReaderWorker(r, self.shared_queue)
            worker.start()
            self.workers.append(worker)

        # 3. 큐에 쌓이는 데이터를 비동기로 소비해 줄 단일 전담 백그라운드 스레드 기동
        # [주의]: 모드 판별 플래그 논리가 포함된 실제 가동 루프를 연결합니다.
        self.consumer_thread = threading.Thread(target=self._consume_queue_loop, daemon=True)
        self.consumer_thread.start()
        
        self._safe_ui_callback(f"총 {len(all_readers)}대의 NFC 리더기 관제 스레드가 가동되었습니다.", "success")

    def _consume_queue_loop(self):
        """[교정 완료]: 현재 탭 모드(REGISTRATION / ATTENDANCE)를 실시간 판별하여 독립 처리하는 코어 루프"""
        while self.running:
            try:
                try: 
                    task_data = self.shared_queue.get(timeout=1.0)
                except queue.Empty: 
                    continue 
                
                nfc_uid = task_data.get("uid")
                reader_name = task_data.get("reader_name")
                worker_ref = task_data.get("worker_ref")

                # [자가 치유 논리 2단계]: 런타임 태깅 순간에도 컨트롤러를 재검사하여 최종 복구 시도
                if self.controller is None and hasattr(self.ui_callback, '__self__'):
                    app_ref = self.ui_callback.__self__
                    if hasattr(app_ref, 'controller') and app_ref.controller:
                        self.controller = app_ref.controller

                # ------------------------------------------------------------------
                # 💡 [교정 핵심]: 현재 UI 활성 탭 모드(current_mode)에 따른 조건부 독립 분기
                # ------------------------------------------------------------------
                
                # [CASE A] 등록 및 해지 탭 모드일 때
                if self.current_mode == "REGISTRATION":
                    if self.controller and hasattr(self.controller, 'process_registration'):
                        self._safe_ui_callback(f"⏳ [{reader_name}] 카드를 신규 등록 멤버 정보에 연동하는 중...", "info")
                        try:
                            # 등록 프로세스 실행 (task_data 통째로 혹은 nfc_uid 전달)
                            res = self.controller.process_registration(task_data)
                            server_msg = res.get("message", "카드 등록 처리 시도 완료")
                            
                            if worker_ref:
                                worker_ref.last_uid = nfc_uid
                                worker_ref.last_tag_time = time.time()
                                
                            self._safe_ui_callback(f"🔵 {server_msg} (장치: {reader_name})", "success")
                        except Exception as reg_err:
                            self._safe_ui_callback(f"🛑 카드 등록 처리 실패: {str(reg_err)}", "error")
                    else:
                        self._safe_ui_callback("🛑 [설계 오류] 등록용 Controller 혹은 process_registration 메서드가 바인딩되지 않았습니다.", "error")

                # [CASE B] 출석 현황 대시보드 탭 모드일 때
                elif self.current_mode == "ATTENDANCE":
                    # 출석 모드일 때만 회차 필수 검증 작동
                    if not self.occurrence_id or self.occurrence_id == "CARD_REGISTRATION_MODE":
                        msg = f"🔔 [{reader_name}] 카드 감지! 대시보드 탭에서 출석을 체크하려면 '출석 회차'를 먼저 대시보드에서 선택해야 합니다."
                        self._safe_ui_callback(msg, "error")
                        self.shared_queue.task_done()
                        continue

                    self._safe_ui_callback(f"⏳ [{reader_name}] 서버에 출석 정보를 적재하는 중...", "info")
                    
                    if self.controller and hasattr(self.controller, 'process_nfc_attendance'):
                        try:
                            res = self.controller.process_nfc_attendance(self.occurrence_id, nfc_uid)
                            server_msg = res.get("message", "출석 적재 성공")
                            
                            if worker_ref:
                                worker_ref.last_uid = nfc_uid
                                worker_ref.last_tag_time = time.time()
                                
                            self._safe_ui_callback(f"🟢 {server_msg} (인식 장치: {reader_name})", "success")
                            
                            # 부모 메인 앱의 UI 새로고침 비동기 유도
                            if hasattr(self.controller, 'main_app') and self.controller.main_app:
                                self.controller.main_app.after(0, self.controller.main_app.refresh_selected_card_data)
                        except Exception as db_err:
                            self._safe_ui_callback(f"🛑 Supabase DB 출석 통신 실패: {str(db_err)}", "error")
                            print(f"🛑 Supabase DB 출석 통신 실패: {str(db_err)}", "error")
                    else:
                        self._safe_ui_callback("🛑 [설계 오류] 출석용 Controller 혹은 process_nfc_attendance 메서드가 없습니다.", "error")
                
                # [CASE C] 그 외 차단 모드(NONE 등)일 때 카드가 태그된 경우
                else:
                    print(f"[NFC 태그 무시] 비활성화 상태이거나 모드 일치 안 함 (현재 모드: {self.current_mode})")

                self.shared_queue.task_done()

            except Exception as loop_critical_err:
                if self.ui_callback:
                    self.ui_callback(f"루프 내부 치명적 예외 복구 완료: {str(loop_critical_err)}")
                time.sleep(1.0)

    def stop_all_readers(self):
        """프로그램 종료 시 열려있는 모든 하드웨어 자원 및 스레드를 우아하게 자진 해제(Graceful Shutdown)"""
        if self.ui_callback and callable(self.ui_callback):
            self.ui_callback("[ReaderManager] NFC 관제 시스템 종료 절차 돌입")
        self.running = False
        
        for worker in self.workers:
            worker.running = False
            
        self.workers.clear()
        self._safe_ui_callback("모든 NFC 리더기 연결 스레드가 안전하게 닫혔습니다.", "info")