# auth_config.py
import os
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")

SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

SUPABASEAUTH = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) 

class SupabaseAuthManager:
    def __init__(self, base_url: str = "https://vercel-node-js-test-blush.vercel.app"):
        self.base_url = base_url.rstrip('/')
        # 💡 requests.Session을 사용하면 로그인 쿠키가 자동으로 유지됩니다.
        self.session = requests.Session()
        self.client: Client = None

    def login_to_web(self, email: str, password: str) -> bool:
        """
        Next.js 웹사이트 백엔드로 로그인을 시도하여 세션 쿠키를 획득합니다.
        (본인의 Next.js 로그인 API 엔드포인트 주소와 Payload 구조에 맞게 수정 필요)
        """
        login_url = f"{self.base_url}/api/auth/login" # 예시 로그인 주소
        payload = {"email": email, "password": password}
        
        try:
            print("[인증] 웹 서버에 로그인을 시도합니다...")
            response = self.session.post(login_url, json=payload, timeout=5)
            response.raise_for_status()
            print("[인증] 웹 로그인 성공 (세션 쿠키 확보 완료)")
            return True
        except Exception as e:
            print(f"[인증 에러] 웹 로그인 실패: {e}")
            return False

    def fetch_supabase_client(self) -> Client:
        """
        로그인된 세션을 기반으로 Next.js API에서 Supabase 키를 받아와 Client 객체를 생성합니다.
        """
        api_url = f"{self.base_url}/api/auth/get-supabase-keys"
        
        try:
            print("[인증] 관리자 세션을 검증하고 Supabase 키를 가져오는 중...")
            # 💡 위에서 login_to_web을 성공했다면 self.session 내부에 쿠키가 들어있어 세션이 통과됩니다.
            response = self.session.get(api_url, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            supabase_info = data.get("supabase", {})
            supabase_url = supabase_info.get("url")
            supabase_anon_key = supabase_info.get("anonKey")
            
            if not supabase_url or not supabase_anon_key:
                raise ValueError("서버 응답에 Supabase 접속 정보가 누락되었습니다.")
                
            # Supabase 클라이언트 생성 및 저장
            self.client = create_client(supabase_url, supabase_anon_key)
            print(f"[성공] 관리자 권한 확인 및 Supabase 연결 완료: {supabase_url}")
            return self.client
            
        except Exception as e:
            print(f"[실패] 권한이 없거나 세션이 만료되었습니다: {e}")
            print("[인증 백업] 로컬 .env 기반 백업 모드로 전환을 시도합니다.")
            
            # 실패 시 안전장치(Fallback): 로컬 .env 파일의 키 사용
            fallback_url = os.getenv("SUPABASE_URL")
            fallback_key = os.getenv("SUPABASE_ANON_KEY")
            
            if fallback_url and fallback_key:
                self.client = create_client(fallback_url, fallback_key)
                print("[백업 완료] 로컬 .env 기반으로 Supabase 클라이언트가 초기화되었습니다.")
                return self.client
            else:
                print("[치명적 에러] 로컬 .env 파일에도 Supabase 접속 정보가 없습니다.")
                return None
            
    # auth_config.py 내부 SupabaseAuthManager 클래스에 통합 호출 메서드 추가하면 편리합니다.
    def login_and_get_client(self, email: str, password: str) -> Client:
        """웹 로그인 후 Supabase 클라이언트 객체까지 한 번에 획득하는 통합 메서드"""
        if self.login_to_web(email, password): # 1. 세션 쿠키 확보
            return self.fetch_supabase_client() # 2. Vercel API에서 키 가져와 Client 반환
        return None