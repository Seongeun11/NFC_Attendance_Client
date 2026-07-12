# -*- mode: python ; coding: utf-8 -*-
# 빌드 명령어: pyinstaller run.spec --clean

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 만약 .env 파일이나 UI용 이미지, 아이콘 등이 있다면 이곳에 명시합니다.
        # 예: ('.env', '.')
    ],
    hiddenimports=[
        # 1. 외부 통신 및 DB 핵심 패키지 우회 등록 (Supabase 관련 누락 방지)
        'requests',
        'supabase',
        'postgrest',
        'gotrue',
        'storage3',
        'supafund',
        'httpx',
        
        # 2. NFC 하드웨어 모니터링 모듈 (pyscard) 강제 연동
        'smartcard',
        'smartcard.CardMonitoring',
        'smartcard.pcsc',
        'smartcard.scard',
        
        # 3. 프로젝트 내부 패키지 및 모든 서브 모듈 누락 없이 구조 매핑
        'attendance_utils',
        'attendance_utils.auth_config',
        'attendance_utils.dashboard_controller',
        'attendance_utils.dashboard_ui',
        'attendance_utils.login_controller',
        'attendance_utils.login_ui',
        'attendance_utils.main_controller',
        'attendance_utils.main_ui',
        'attendance_utils.nfc_reader_manager',  # 추가됨
        'attendance_utils.occurrence_card_ui',   # 추가됨
        'attendance_utils.today_operations_app', # 추가됨
        'attendance_utils.ui_utils',             # 추가됨
        'attendance_utils.update_checker',        # 추가됨
        'attendance_utils.user_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NFC_Attendance_System',  # 생성될 최종 exe 파일 이름
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # UPX가 설치되어 있으면 압축 적용
    console=True,  # 💡 중요: 첫 빌드 시 프로그램이 팅기는 에러 로그를 확인하기 위해 True로 변경했습니다. 잘 켜지면 False로 바꾸세요.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico' # 아이콘 파일이 프로젝트 루트에 생기면 주석 해제 후 설정
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NFC_Attendance_System',
)