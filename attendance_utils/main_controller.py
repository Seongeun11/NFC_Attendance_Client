#main_controller.py
from tabulate import tabulate


import threading

# 수정된 프레임들 가져오기
from attendance_utils.main_ui import MainFrame
from attendance_utils.auth_config import SUPABASEAUTH
from attendance_utils.user_service import AuthService, UserSearchService, NfcCardService
from attendance_utils.dashboard_controller import AttendanceController
from attendance_utils.auth_config import SupabaseGlobalContext

class NfcApp:
    def __init__(self, root,supabase_client=None):
        self.root = root
        self.current_frame = None
        self.db_users = []
        self.current_target = None  # 안전장치 타겟 변수 명시적 초기화
        #[해결 단계 1] 생성 시점에 실시간 싱글톤 컨텍스트 확인
        
        # [핵심 추가] 외부에서 발급된 정식 세션 클라이언트가 있다면 전역 싱글톤에 최우선 등록
        if supabase_client is not None:
            SupabaseGlobalContext.set_client(supabase_client)
        #self.client =SupabaseGlobalContext.get_client() 
        # --- [추가] 현재 활성화된 NFC 모니터링 자원을 저장할 변수 ---
        #self.active_monitor = None
        #self.active_observer = None
        #self.current_target = None  # 현재 진짜 등록 대기 중인 사용자
        # 이전 답변에서 수정한 대로 현재 유효한 로그인 세션(self.client)을 주입합니다.
        #self.controller = AttendanceController(SupabaseGlobalContext.get_client())
        #  비즈니스 및 하드웨어 서비스 인스턴스 격리 생성
       # self.auth_service = AuthService(SupabaseGlobalContext.get_client())
        #self.search_service = UserSearchService(SupabaseGlobalContext.get_client())
        #self.card_service = NfcCardService(SupabaseGlobalContext.get_client())
        self.refresh_services_context()
        # 첫 화면인 로그인 화면 띄우기
        #self.show_login_frame()
        self.show_main_frame()
    def refresh_services_context(self):
        """ Vercel 로그인이 완료된 최신 싱글톤 클라이언트를 가져와서 모든 서비스 레이어에 동적으로 강제 동기화합니다. """
        # 실시간으로 가장 최신의 Vercel 세션 검증 완료된 클라이언트를 수신
        current_valid_client = SupabaseGlobalContext.get_client()
        
        self.client = current_valid_client
        
        # [핵심 치유] 컨트롤러 및 모든 비즈니스 서비스 인스턴스를 최신 자격 증명 기반으로 재동기화/격리 생성
        self.controller = AttendanceController(current_valid_client)
        self.auth_service = AuthService(current_valid_client)
        self.search_service = UserSearchService(current_valid_client)
        self.card_service = NfcCardService(current_valid_client)
        #print("[시스템] Vercel 원본 세션 기반으로 NfcApp 서비스 레이어 전역 바인딩 동기화 완료.", flush=True)

    def show_main_frame(self):
        if self.current_frame:
            self.current_frame.destroy()
        # [해결 단계 2] 메인 화면이 구성되기 직전, 다시 한번 최신 컨텍스트가 주입되었는지 리프레시 검증
        self.refresh_services_context()
        
        
        # MainFrame 생성 시 각각 검색과 등록 함수를 바인딩합니다.
        self.current_frame = MainFrame(
            self.root, 
            on_search_click=self.search_user, 
            on_register_click=self.register,
            on_delete_click=self.delete_user,
            
        )
        self.current_frame.pack(fill="both", expand=True)
        # 전역에서 관리 중인 controller(AttendanceController) 인스턴스를 주입하여 탭2 화면을 갱신합니다.
        if hasattr(self, "controller") and self.controller:
            self.current_frame.link_controller(self.controller)
            
        # [핵심 치유] UI가 완전히 배치된 후(after 100ms), 세션이 바인딩된 상태에서 안전하게 첫 초기 검색을 수행하도록 유도
        self.root.after(100, lambda: self.search_user("", only_registered=False, only_active=True))
    ############################################
    # 기능 구현 (컨트롤러 로직)
    ############################################
  
    

    def search_user(self, keyword, only_registered=False, only_active=False):
        #print(f"\n[시작] '{keyword}' 검색 중... (등록된 사용자만: {only_registered}, 재학생만: {only_active})", flush=True)
        self.current_frame.status_log.config(text=f"'{keyword}' 검색 중...")
        try:
            # [방어 코드] 실행 직전 싱글톤 및 서비스 레이어 재확인
            if not hasattr(self, 'search_service') or self.search_service is None:
                self.refresh_services_context()

            # 비즈니스 로직 클래스(UserSearchService) 호출
            users = self.search_service.execute_search(keyword, only_registered, only_active)
            self.db_users = []
            #elf.db_users = users # 인덱스 동기화용 변수 저장

           # 리스트박스 초기화 (즉시 실행)
            self.current_frame.listbox.delete(0, "end")

            if not users:
                #print("\n[검색 결과가 없습니다.]\n")
                self.root.after(0, lambda: self.current_frame.status_log.config(text="[검색 결과가 없습니다.]"))
                return

            # 터미널 출력용 데이터 설정
            headers = ["ID", "이름", "학번", "상태", "NFC ID", "NFC 상태"] # '상태' 컬럼 표기 추가 가능
            table_data = []

            for u in users:
                if not isinstance(u, dict): continue
                nfc_data = u.get("nfc_cards")
                nfc_id, nfc_status, has_card = "없음", "없음", False

                # NFC 카드 데이터 파싱 및 등록 여부 체크
                if isinstance(nfc_data, dict):
                    nfc_id = str(nfc_data.get("nfc_id", "-"))
                    nfc_status = str(nfc_data.get("nfc_status", "-"))
                    has_card = True
                elif isinstance(nfc_data, list) and nfc_data:
                    nfc_text = [str(card.get("nfc_id", "-")) for card in nfc_data if isinstance(card, dict)]
                    statuses = [str(card.get("nfc_status", "-")) for card in nfc_data if isinstance(card, dict)]
                    if nfc_text:
                        nfc_id = "\n".join(nfc_text)
                        nfc_status = "\n".join(statuses)
                        has_card = True

                # [추가] '등록된 사용자만 보기'가 활성화되었는데 카드가 없다면 패스(제외)
                if only_registered and not has_card:
                    continue

                # 필터링을 통과한 유저만 클래스 변수(self.db_users)에 저장
                self.db_users.append(u)

                # 터미널 출력용 데이터 누적
                #table_data.append([
                #    u.get("id", "-"), 
                #    u.get("full_name", "-"), 
                #    u.get("student_id", "-"), 
                #    u.get("enrollment_status", "-"),  # 여기에 함께 리스트 요소로 포함시킵니다.
                #    nfc_id, 
                #    nfc_status
                #])
                # UI 리스트박스에 추가 (상태가 휴학/수료 등 active가 아닐 때 시각적 구분용 표시 추가)
                status_text = "[등록됨]" if has_card else "[미등록]"
                enroll_text = "" if u.get('enrollment_status') == 'active' else f"({u.get('enrollment_status')})"
                
                item_text = f"[{u.get('student_id', '-')}] {u.get('full_name', '-')} {enroll_text} {status_text}"
                
                # [무한루프 해결] 무의미한 after(0) 람다 스케줄러를 제거하고 즉시 화면에 삽입합니다.
                self.current_frame.listbox.insert("end", item_text)
                
            #print(f"\n'{keyword}' 검색 완료... (등록된 사용자만: {only_registered}, 재학생만: {only_active})", flush=True)
            self.current_frame.status_log.config(text=f"'{keyword}' 검색 완료...")
            # 최종 필터링된 결과가 없을 때 처리
            if not self.db_users:
               #print("\n[조건에 맞는 검색 결과가 없습니다.]\n")
                self.current_frame.status_log.config(text="[조건에 맞는 검색 결과가 없습니다.]")
                return

            #if table_data:
                #print("\n" + tabulate(table_data, headers=headers, tablefmt="grid") + "\n", flush=True)

        except Exception as e:
            #print(f"\n[에러 발생]: {str(e)}\n", flush=True)
            self.current_frame.status_log.config(text=f"[에러 발생]: {str(e)}")

    def delete_user(self):
        selected = self.current_frame.listbox.curselection()
        try:
            selected = self.current_frame.listbox.curselection()
            if not selected:
                self.current_frame.status.config(text="[경고] 선택된 사용자가 없습니다.")
                return
                
            index = selected[0]
            if not self.db_users: return
            
            target = self.db_users[index]
            profiles_id = target.get("id")
            user_name = target.get("full_name", "이름 없음")

            self.current_frame.status.config(text=f"{user_name}의 NFC 카드 삭제 중...")
            
            # 서비스 레이어 호출 (삭제 실행)
            success = self.card_service.delete_nfc_card(profiles_id)

            # 4. UI 및 리스트박스 상태 업데이트
            def update_ui_delete_success():
                self.current_frame.status.config(text=f"{user_name} 카드 삭제 완료")
                
                # 기존 텍스트 가져와서 '[등록됨]'을 '[미등록]'으로 변경
                current_text = self.current_frame.listbox.get(index)
                if "[등록됨]" in current_text:
                    new_text = current_text.replace("[등록됨]", "[미등록]")
                    
                    # 리스트박스 항목 교체 (삭제 후 재삽입)
                    self.current_frame.listbox.delete(index)
                    self.current_frame.listbox.insert(index, new_text)
                    
                    # 삭제 후에도 해당 항목이 선택된 상태를 유지하고 싶다면 아래 주석 해제
                    # self.current_frame.listbox.selection_set(index)

            # 안전하게 메인 UI 스레드에서 실행
            self.root.after(0, update_ui_delete_success)
            print(f"{user_name} 카드 데이터 삭제 완료", flush=True)

        except Exception as e:
            #print(f"[delete_user 함수 에러 발생]: {str(e)}", flush=True)
            self.root.after(0, lambda: self.current_frame.status.config(text="카드 삭제 중 오류가 발생했습니다."))
        

    def register(self):
        try:
            selected = self.current_frame.listbox.curselection()
            if not selected:
                self.current_frame.status.config(text="[경고] 선택된 사용자가 없습니다.")
                return
                
            index = selected[0]
            if not self.db_users: return
            target = self.db_users[index]
            
            self.current_frame.status.config(text=f"{target.get('full_name', '')} 카드 태그 대기 중...")
            self.current_frame.status_log.config(text=f"NFC CardMonitor 서비스를 시작합니다.")

            # 백그라운드 리더기 가동 서비스 실행 (비동기 데몬 스레드로 시작)
            # 중요: 하드웨어 스레드 안에서 발생한 결과를 UI에 안전하게 반영하기 위해 콜백 함수를 같이 넘깁니다.
            threading.Thread(
                target=self.card_service.start_hardware_monitor, 
                args=(target, self._nfc_hardware_status_listener), 
                daemon=True
            ).start()

        except Exception as e:
            print(f"[register 함수 에러 발생]: {str(e)}", flush=True)


    def process_card(self, target, uid):
        # --- [안전장치] 현재 선택해서 대기 중인 사용자가 아니면 이전 스레드의 응답이므로 무시합니다 ---
        if self.current_target is None or self.current_target.get("id") != target.get("id"):
            return False
        
        #print(f"[NFC 감지됨] 값 = {uid} / 대상자 = {target['full_name']}", flush=True)
        try:
            # 💡 로컬 캐시 유실 대비를 위해 실시간으로 싱글톤 컨텍스트 재확인 후 최신 클라이언트로 통신
            active_client = SupabaseGlobalContext.get_client()
            check = active_client.table("nfc_cards").select("profiles_id").eq("nfc_id", uid).execute()
            #check = self.client.table("nfc_cards").select("profiles_id").eq("nfc_id", uid).execute()

            if check.data:
                self.root.after(0, lambda: self.current_frame.status.config(text="태그한 카드는 이미 등록되었습니다."))
                #print("중복 이미 등록된 카드입니다.", flush=True)
                return

            self.client.table("nfc_cards").insert({
                "profiles_id": target["id"],
                "nfc_id": uid,
                "nfc_status": "ACTIVE"
            }).execute()

            #self.root.after(0, lambda: self.current_frame.status.config(text=f"{target['full_name']} 등록 완료"))
            # 1. UI 텍스트 및 상태 업데이트
            def update_ui_success():
                self.current_frame.status.config(text=f"{target['full_name']} 등록 완료")
                
                # 현재 선택된 리스트박스 인덱스 가져오기
                selected = self.current_frame.listbox.curselection()
                if selected:
                    index = selected[0]
                    # 기존 텍스트 가져와서 '[미등록]'을 '[등록됨]'으로 변경
                    current_text = self.current_frame.listbox.get(index)
                    if "[미등록]" in current_text:
                        new_text = current_text.replace("[미등록]", "[등록됨]")
                        # 리스트박스 항목 교체 (삭제 후 재삽입)
                        self.current_frame.listbox.delete(index)
                        self.current_frame.listbox.insert(index, new_text)
                        # 시각적으로 계속 선택된 상태를 유지하고 싶다면 아래 주석 해제
                        #self.current_frame.listbox.selection_set(index)

            self.root.after(0, update_ui_success)
            #print(f"{target['full_name']} 등록 완료", flush=True)

            # 등록이 성공했으므로 현재 대기 중인 타겟을 비웁니다.
            self.current_target = None
            return True # 등록 성공 시 True 반환하여 모니터링 종료 유도
                
        except Exception as e:
            self.root.after(0, lambda: self.current_frame.status.config(text="이미 등록된 계정은 다시 등록할 수 없습니다."))
            #print(f"오류 발생: {str(e)}", flush=True)

    def _nfc_hardware_status_listener(self, status, target, uid_or_error):
        """
        하드웨어 비동기 상태 피드백 리스너
        수정사항: 오류 발생 시 uid_or_error 매개변수로 에러 메시지를 전달받아 UI에 바인딩합니다.
        """
        selected = self.current_frame.listbox.curselection()
        index = selected[0] if selected else None

        if status == 'SUCCESS':
            print(f"[NFC 감지됨] 값 = {uid_or_error} / 대상자 = {target['full_name']} 등록 완료", flush=True)
            def update_ui_success():
                self.current_frame.status.config(text=f"{target['full_name']} 등록 완료")
                if index is not None:
                    current_text = self.current_frame.listbox.get(index)
                    if "[미등록]" in current_text:
                        new_text = current_text.replace("[미등록]", "[등록됨]")
                        self.current_frame.listbox.delete(index)
                        self.current_frame.listbox.insert(index, new_text)
            self.root.after(0, update_ui_success)

        elif status == 'DUPLICATE':
            self.root.after(0, lambda: self.current_frame.status.config(text="태그한 카드는 이미 등록되었습니다."))

        elif status == 'FAILED':
            self.root.after(0, lambda: self.current_frame.status.config(text="이미 등록된 계정은 다시 등록할 수 없습니다."))

        elif status == 'TERMINATED':
            self.root.after(0, lambda: self.current_frame.status_log.config(text="NFC 서비스가 정지되었습니다."))

        #[오류 메시지 대시보드 출력 보완 및 버그 수정]
        elif status == 'ERROR':
            error_msg = str(uid_or_error)
            print(f"[통신 에러 조치] UI 출력 및 대시보드 로그 전송: {error_msg}", flush=True)
            
            def update_ui_error():
                # [해결안] 전역 Window 또는 렌더링된 자식 위젯 중에서 dashboard_ui 관련 알림 채널을 서칭합니다.
                notified = False
                
                # 1단계: 현재 메인 프레임 내부나 하위 컨트롤러에서 팝업/알림 채널이 있는지 검색
                if hasattr(self, 'root'):
                    # 버그 수정: 전체 트리를 안전하게 완전 탐색하기 위한 큐(Queue) 또는 리스트 기반 탐색
                    widgets_to_check = [self.root]
                    while widgets_to_check:
                        current_widget = widgets_to_check.pop(0)
                        
                        # 검사 1: 'set_global_noti' 또는 'set_global_notification' 둘 다 대응하도록 수정
                        for attr_name in ['set_global_noti', 'set_global_notification', 'lbl_noti']:
                            if hasattr(current_widget, attr_name):
                                attr = getattr(current_widget, attr_name)
                                # 메서드/함수인 경우 호출
                                if callable(attr):
                                    try:
                                        attr(f"🛑 카드 인식 중 오류 발생: {error_msg}", "error")
                                        notified = True
                                    except:
                                        pass
                                # Tkinter Label 위젯인 경우 config 호출
                                elif hasattr(attr, 'config'):
                                    try:
                                        attr.config(text=f"🛑 오류: {error_msg}", fg="#b91c1c")
                                        notified = True
                                    except:
                                        pass
                        
                        # 모든 자식 위젯을 유실 없이 탐색 리스트에 추가
                        try:
                            widgets_to_check.extend(current_widget.winfo_children())
                        except:
                            pass

                # 2단계: 대시보드 카드 뷰(OccurrenceCardUi)들이 열려 있다면 활성화된 카드에 에러 전달
                # 대시보드 위젯 탐색에 실패했을 때의 기존 백업 레이아웃 처리 (MainFrame용)
                if not notified and hasattr(self, 'current_frame') and self.current_frame.winfo_exists():
                    if hasattr(self.current_frame, 'status') and self.current_frame.status.winfo_exists():
                        self.current_frame.status.config(text=f"[리더기 오류] {error_msg}", fg="#b91c1c")
                    if hasattr(self.current_frame, 'status_log') and self.current_frame.status_log.winfo_exists():
                        self.current_frame.status_log.config(text=f"오류: {error_msg}", fg="#b91c1c")
                
            self.root.after(0, update_ui_error)