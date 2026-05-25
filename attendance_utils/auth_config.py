import requests
import threading
from typing import Optional  # Optional 타입 힌트 추가
#from dotenv import load_dotenv
from supabase import create_client, Client

#load_dotenv()

#SUPABASE_URL = os.getenv("SUPABASE_URL")
#SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
#SUPABASEAUTH = create_client(SUPABASE_URL, SUPABASE_ANON_KEY) 

# 🚀 [표준 변경] 기존 하드코딩 전역 변수를 가변형 전역 싱글톤 객체로 캡슐화
class SupabaseGlobalContext:
    _client: Optional[Client] = None  # [교정] None 대입이 가능하도록 Optional 선언
    _lock = threading.Lock()

    @classmethod
    def set_client(cls, client: Optional[Client]):  # [교정] None 대입 허용
        with cls._lock:
            cls._client = client

    @classmethod
    def get_client(cls) -> Optional[Client]:  # [교정] 반환 타입에 None 허용
        with cls._lock:
            # 만약 Vercel 인증 클라이언트가 아직 비어있다면, 로컬 .env 기반으로 자동 Fallback 초기화
            if cls._client is None: #and SUPABASE_URL and SUPABASE_ANON_KEY:
                #cls._client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
                #print("[인증이 없습니다].")
                pass
            return cls._client

# 기존 코드와의 하위 호환성을 위해 프로퍼티 형태로 바인딩
SUPABASEAUTH = SupabaseGlobalContext.get_client()

class SupabaseAuthManager:
    def __init__(self, base_url: str = "https://vercel-node-js-test-blush.vercel.app"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
        # [보안 기본 헤더 세트] Next.js 미들웨어 프리패스용 표준 구성
        self.headers_template = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Connection": "keep-alive"
        }
        self.session.headers.update(self.headers_template)
        
        self.client: Optional[Client] = None  # [교정] None 대입이 가능하도록 Optional 선언
        self.cached_email = None
        self.cached_password = None

    def login_to_web(self, student_id: str, password: str) -> bool:
        """Vercel 웹 서버 로그인 후 발급된 원본 세션 쿠키 문자열을 완벽히 포획하여 헤더에 고정합니다."""
        login_url = f"{self.base_url}/api/auth/login"
        
        processed_id = student_id.split('@')[0] if '@' in student_id else student_id
        payload = {"student_id": processed_id, "password": password}
        
        self.cached_email = student_id
        self.cached_password = password

        #print(f"로그인정보(보정완료):{payload}")
        
        try:
            #print("[인증] 웹 서버에 로그인을 시도합니다...")
            response = self.session.post(login_url, json=payload, timeout=5)
            response.raise_for_status()
            
            # [핵심 치유] requests 엔진의 내부 CookieJar 위임 방식을 폐기하고,
            # 서버가 보내준 원본 Set-Cookie 헤더 리스트를 직접 가공하여 브라우저의 Cookie 전송 형태를 100% 모방합니다.
            raw_headers = getattr(response.raw, 'headers', None)
            cookies = []
            if raw_headers and hasattr(raw_headers, 'getlist'):
                cookies = raw_headers.getlist("Set-Cookie")
            else:
                # [교정] response.headers는 getlist가 없으므로 raw.headers를 안전하게 검사하거나 딕셔너리 추출 방식으로 에러 우회
                if raw_headers and hasattr(raw_headers, 'getallmatchingheaders'):
                    cookies = response.raw.headers.getlist("Set-Cookie")
                else:
                    cookies = []
                
            # 만약 위 방법으로도 쿠키가 안 잡히면 fallback으로 response.cookies 활용
            if not cookies and response.cookies:
                cookies = [f"{k}={v}" for k, v in response.cookies.items()]

            if cookies:
                # 쿠키 옵션들(path, httponly, expires 등)을 깔끔하게 떼어내고 순수 'key=value'만 추출
                cookie_pairs = []
                for c in cookies:
                    if c:
                        # 첫 번째 세미콜론 앞이 실제 세션 쿠키 데이터 항목입니다.
                        actual_cookie = c.split(';')[0].strip()
                        if actual_cookie:
                            cookie_pairs.append(actual_cookie)
                
                # 추출한 복수 개의 세션 쿠키들을 하나의 문자열 체인으로 연결합니다. (예: "next-auth.session-token=...; csrf-token=...")
                combined_cookie = "; ".join(cookie_pairs)
                
                # 중요: 세션 컨텍스트 유실을 막기 위해 템플릿과 세션 헤더 전체에 강제로 Cookie를 주입 고정합니다.
                self.headers_template["Cookie"] = combined_cookie
                self.session.headers.update({"Cookie": combined_cookie})
                #print(f"[인증] 원본 멀티 세션 쿠키 동기화 강제 바인딩 완료")
            
            #print("[인증] 웹 로그인 성공 (세션 쿠키 확보 완료)")
            return True
        except Exception as e:
            #print(f"[인증 에러] 웹 로그인 실패: {e}")
            
            return False

    def fetch_supabase_client(self) -> Optional[Client]:  # [교정] 반환 타입에 None 허용
        """완벽하게 복제된 브라우저 세션 상태(헤더+쿠키)로 Supabase 키 엔드포인트를 완벽 우회 잠금 해제합니다."""
        api_url = f"{self.base_url}/api/auth/get-supabase-keys"
        
        try:
            #print("[인증] 관리자 세션 검증 및 인증 토큰 획득 시도 중...")
            response = self.session.get(api_url, headers=self.headers_template, timeout=5)
            
            # API가 401/403을 반환하는 경우 예외 발생
            response.raise_for_status()
            
            data = response.json()
            
            # 1. 에러 응답 처리 (ErrorResponse 타입 대응)
            if "error" in data:
                raise Exception("아이디 비밀번호가 올바르지 않습니다.")
                
            # 2. 성공 응답 데이터 추출 (SuccessResponse 타입 대응)
            supabase_info = data.get("supabase", {})
            access_token = data.get("accessToken")
            refresh_token = data.get("refreshToken")
            
            url = supabase_info.get("url")
            key = supabase_info.get("anonKey")
            
            if not url or not key:
                raise ValueError("서버 응답에 필수 Supabase 키가 누락되었습니다.")
                
            # 3. Supabase 클라이언트 초기화 및 세션 주입
            self.client = create_client(url, key)
            
            if access_token and refresh_token:
                self.client.auth.set_session(access_token, refresh_token)
                #print("[인증] 세션 토큰 주입 성공: 관리자 권한 활성화됨")
            else:
                #print("[경고] 토큰이 전달되지 않아 익명 모드로 연결됩니다.")
                pass
                
            SupabaseGlobalContext.set_client(self.client)
            return self.client
            
        except Exception as e:
            #print(f"[실패] 인증 정보 획득 실패: {e}")
            # 기존 백업 로직 유지
            #fallback_url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            #fallback_key = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            #if fallback_url and fallback_key:
            #    self.client = create_client(fallback_url, fallback_key)
                #print("[백업 완료] 로컬 .env 기반 클라이언트 초기화")
            #   return self.client
            return None

    def login_and_get_client(self, email: str, password: str) -> Optional[Client]:  # [교정] 반환 타입에 None 허용
        if self.login_to_web(email, password): 
            return self.fetch_supabase_client() 
        return None