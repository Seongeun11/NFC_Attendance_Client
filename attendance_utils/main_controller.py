#main_controller.py
#from tabulate import tabulate
import threading
# 수정된 프레임들 가져오기
from attendance_utils.main_ui import MainFrame
from attendance_utils.user_service import AuthService, UserSearchService, NfcCardService
from attendance_utils.dashboard_controller import AttendanceController
from attendance_utils.auth_config import SupabaseGlobalContext
from attendance_utils.update_checker import check_for_updates_async

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

        self.refresh_services_context()
        # 첫 화면인 로그인 화면 띄우기

        self.show_main_frame()
    def refresh_services_context(self):
        """ Vercel 로그인이 완료된 최신 싱글톤 클라이언트를 가져와서 모든 서비스 레이어에 동적으로 강제 동기화합니다. """
        # 실시간으로 가장 최신의 Vercel 세션 검증 완료된 클라이언트를 수신
        current_valid_client = SupabaseGlobalContext.get_client()
        
        self.client = current_valid_client
        
        # 컨트롤러 및 모든 비즈니스 서비스 인스턴스를 최신 자격 증명 기반으로 재동기화/격리 생성
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
            
        # show_main_frame 메서드 하단부 수정 
        # 인자 개수 확장에 맞춰 초기 기본 소속 인자 "전체"를 넘겨주도록 변경합니다. 
        self.root.after(100, lambda: self.search_user("", only_registered=False, only_active=True, selected_dept="전체"))

        # 💡 [업데이트 확인 연동] 
        # 화면 진입 처리가 끝난 후 약 0.5초(500ms) 뒤에 백그라운드 스레드로 업데이트 체크를 시작합니다.
        # 이렇게 하면 사용자가 메인 대시보드를 보는 순간 팝업창이 부모 창 정중앙에 깔끔하게 배치됩니다.
        self.root.after(500, lambda: check_for_updates_async(self.root))
    ############################################
    # 기능 구현 (컨트롤러 로직)
    ############################################

    # 💡 파라미터 맨 뒤에 selected_dept="전체" 기본값 추가 
    def search_user(self, keyword, only_registered=False, only_active=False, selected_dept="전체"):
        if self.current_frame is None: return

        self.current_frame.status_log.config(text=f"'{keyword}' 검색 중...")
        try:
            if not hasattr(self, 'search_service') or self.search_service is None:
                self.refresh_services_context()

            # 비즈니스 로직 서비스 호출
            users = self.search_service.execute_search(keyword, only_registered, only_active)
            
            # 💡 [중요 동적 바인딩]: DB 전체 원본 결과에서 존재하는 모든 소속 목록을 추출하여 UI 콤보박스 목록 갱신
            all_depts = set()
            for u in users:
                if isinstance(u, dict) and u.get("affiliations"):
                    dept_name = u.get("affiliations", {}).get("name")
                    if dept_name:
                        all_depts.add(dept_name)
            
            # 가나다순 정렬 후 '전체' 항목을 맨 앞에 추가하여 콤보박스 값 갱신
            dept_list = ["전체"] + sorted(list(all_depts))
            
            # 현재 선택된 값을 유지하면서 목록만 실시간 리프레시
            current_sel = self.current_frame.dept_combobox.get()
            self.current_frame.dept_combobox['values'] = dept_list
            if current_sel in dept_list:
                self.current_frame.dept_combobox.set(current_sel)
            else:
                self.current_frame.dept_combobox.set("전체")

            self.db_users = []
            self.current_frame.listbox.delete(0, "end")

            if not users:
                self.root.after(0, lambda: self.current_frame.status_log.config(text="[검색 결과가 없습니다.]") if self.current_frame else None)
                return

            for u in users:
                if not isinstance(u, dict): continue
                
                # 💡 [소속 필터링 분기]: '전체'가 아니고 선택된 소속과 사용자의 소속이 다르면 리스트 추가 제외
                user_dept = u.get("affiliations", {}).get("name") if u.get("affiliations") else None
                if selected_dept != "전체" and user_dept != selected_dept:
                    continue

                nfc_data = u.get("nfc_cards")
                nfc_id, nfc_status, has_card = "없음", "없음", False

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

                if only_registered and not has_card:
                    continue

                self.db_users.append(u)

                # UI 리스트박스 출력 텍스트 포맷 구성 (가독성을 위해 소속명 정보도 함께 표기하도록 변경)
                status_text = "[등록됨]" if has_card else "[미등록]"
                enroll_text = "" if u.get('enrollment_status') == 'active' else f"({u.get('enrollment_status')})"
                
                # 소속 텍스트 포맷팅 생성
                dept_display = f" [{user_dept}]" if user_dept else " [소속없음]"
                item_text = f"[{u.get('student_id', '-')}] {u.get('full_name', '-')}{dept_display} {enroll_text} {status_text}"
                
                self.current_frame.listbox.insert("end", item_text)
                
            self.current_frame.status_log.config(text=f"'{keyword}' 검색 및 필터링 완료...")
            
            if not self.db_users:
                self.current_frame.status_log.config(text="[조건에 맞는 검색 결과가 없습니다.]")
                return

        except Exception as e:
            self.current_frame.status_log.config(text=f"[에러 발생]: {str(e)}")

    def delete_user(self):
        # Pylance 타입 검증용 상단 방어 코드 추가
        if self.current_frame is None: return

        selected = self.current_frame.listbox.curselection()
        try:
            selected = self.current_frame.listbox.curselection()
            if not selected:
                self.current_frame.status.config(text="[경고] 선택된 사용자가 없습니다.", fg="blue")
                return
                
            index = selected[0]
            if not self.db_users: return
            
            target = self.db_users[index]
            profiles_id = target.get("id")
            user_name = target.get("full_name", "이름 없음")

            self.current_frame.status.config(text=f"{user_name}의 NFC 카드 삭제 중...", fg="blue")
            
            # 서비스 레이어 호출 (삭제 실행)
            success = self.card_service.delete_nfc_card(profiles_id)

            # 4. UI 및 리스트박스 상태 업데이트
            def update_ui_delete_success():
                if self.current_frame is None: return
                self.current_frame.status.config(text=f"{user_name} 카드 삭제 완료", fg="blue")
                
                # 기존 텍스트 가져와서 '[등록됨]'을 '[미등록]'으로 변경
                current_text = self.current_frame.listbox.get(index)
                if "[등록됨]" in current_text:
                    new_text = current_text.replace("[등록됨]", "[미등록]")
                    
                    # 리스트박스 항목 교체 (삭제 후 재삽입)
                    self.current_frame.listbox.delete(index)
                    self.current_frame.listbox.insert(index, new_text)
                    
            # 안전하게 메인 UI 스레드에서 실행
            self.root.after(0, update_ui_delete_success)
            #print(f"{user_name} 카드 데이터 삭제 완료", flush=True)

        except Exception as e:
            #print(f"[delete_user 함수 에러 발생]: {str(e)}", flush=True)
            self.root.after(0, lambda: self.current_frame.status.config(text="카드 삭제 중 오류가 발생했습니다.", fg="blue") if self.current_frame else None)
        

    def register(self):
        if self.current_frame is None: return
        try:
            selected = self.current_frame.listbox.curselection()
            if not selected:
                self.current_frame.status.config(text="[경고] 선택된 사용자가 없습니다.", fg="blue")
                return
                
            index = selected[0]
            if not self.db_users: return
            target = self.db_users[index]
            
            self.current_frame.status.config(text=f"{target.get('full_name', '')} 카드 태그 대기 중...", fg="blue")
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
        if self.current_frame is None: return False
        # --- [안전장치] 현재 선택해서 대기 중인 사용자가 아니면 이전 스레드의 응답이므로 무시합니다 ---
        if self.current_target is None or self.current_target.get("id") != target.get("id"):
            return False
        
        #print(f"[NFC 감지됨] 값 = {uid} / 대상자 = {target['full_name']}", flush=True)
        try:
            # 로컬 캐시 유실 대비를 위해 실시간으로 싱글톤 컨텍스트 재확인 후 최신 클라이언트로 통신
            active_client = SupabaseGlobalContext.get_client()
            
            # [Pylance 에러 치유] active_client와 self.client가 None인지 명시적으로 방어 체크
            if active_client is None or self.client is None:
                self.root.after(0, lambda: self.current_frame.status.config(text="서버 연결 세션이 유효하지 않습니다.", fg="blue") if self.current_frame else None)
                return False
            
            check = active_client.table("nfc_cards").select("profiles_id").eq("nfc_id", uid).execute()
            #check = self.client.table("nfc_cards").select("profiles_id").eq("nfc_id", uid).execute()

            if check.data:
                self.root.after(0, lambda: self.current_frame.status.config(text="태그한 카드는 이미 등록되었습니다.", fg="blue") if self.current_frame else None)
                #print("중복 이미 등록된 카드입니다.", flush=True)
                return False

            self.client.table("nfc_cards").insert({
                "profiles_id": target["id"],
                "nfc_id": uid,
                "nfc_status": "ACTIVE"
            }).execute()

            # 1. UI 텍스트 및 상태 업데이트
            def update_ui_success():
                if self.current_frame is None: return
                self.current_frame.status.config(text=f"{target['full_name']} 등록 완료", fg="blue")
                
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
            return True  # 등록 성공 시 True 반환하여 모니터링 종료 유도
        except Exception as e:
            self.root.after(0, lambda: self.current_frame.status.config(text="이미 등록된 계정은 다시 등록할 수 없습니다.", fg="blue") if self.current_frame else None)
            #print(f"오류 발생: {str(e)}", flush=True)
            return False

    def _nfc_hardware_status_listener(self, status, target, uid_or_error):
        """ 하드웨어 비동기 상태 피드백 리스너
        수정사항: 오류 발생 시 uid_or_error 매개변수로 에러 메시지를 전달받아 UI에 바인딩합니다.
        """
        if self.current_frame is None: return

        selected = self.current_frame.listbox.curselection()
        index = selected[0] if selected else None
        
        if status == 'SUCCESS':
            #print(f"[NFC 감지됨] 값 = {uid_or_error} / 대상자 = {target['full_name']} 등록 완료", flush=True)
            def update_ui_success():
                if self.current_frame is None: return
                self.current_frame.status.config(text=f"{target['full_name']} 등록 완료", fg="blue")
                if index is not None:
                    current_text = self.current_frame.listbox.get(index)
                    if "[미등록]" in current_text:
                        new_text = current_text.replace("[미등록]", "[등록됨]")
                        self.current_frame.listbox.delete(index)
                        self.current_frame.listbox.insert(index, new_text)
            self.root.after(0, update_ui_success)
        elif status == 'DUPLICATE':
            self.root.after(0, lambda: self.current_frame.status.config(text="태그한 카드는 이미 등록되었습니다.", fg="blue") if self.current_frame else None)
        elif status == 'FAILED':
            self.root.after(0, lambda: self.current_frame.status.config(text="이미 등록된 계정은 다시 등록할 수 없습니다.", fg="blue") if self.current_frame else None)
        elif status == 'TERMINATED':
            self.root.after(0, lambda: self.current_frame.status_log.config(text="NFC 서비스가 정지되었습니다.") if self.current_frame else None)
        #[오류 메시지 대시보드 출력 보완 및 버그 수정]
        elif status == 'ERROR':
            error_msg = str(uid_or_error)
            #print(f"[통신 에러 조치] UI 출력 및 대시보드 로그 전송: {error_msg}", flush=True)
            
            def update_ui_error():
                notified = False
                if hasattr(self, 'root'):
                    widgets_to_check = [self.root]
                    while widgets_to_check:
                        current_widget = widgets_to_check.pop(0)
                        
                        # 컨텍스트 트리 내의 특정 타겟을 동적 조사하여 메시지 주입
                        if hasattr(current_widget, 'controller') and current_widget.controller == self.controller:
                            if hasattr(current_widget, 'summary_labels'):
                                try:
                                    # 명시적 config 바인딩
                                    pass
                                except:
                                    pass
                            elif hasattr(current_widget, 'config'):
                                try:
                                    current_widget.config(text=f"🛑 오류: {error_msg}", fg="#b91c1c")
                                    notified = True
                                except:
                                    pass
                        try:
                            widgets_to_check.extend(current_widget.winfo_children())
                        except:
                            pass

                if not notified and self.current_frame and self.current_frame.winfo_exists():
                    if hasattr(self.current_frame, 'status') and self.current_frame.status.winfo_exists():
                        self.current_frame.status.config(text=f"[리더기 오류] {error_msg}", fg="#b91c1c")
                    if hasattr(self.current_frame, 'status_log') and self.current_frame.status_log.winfo_exists():
                        self.current_frame.status_log.config(text=f"오류: {error_msg}", fg="#b91c1c")
                
            self.root.after(0, update_ui_error)