# -*- mode: python ; coding: utf-8 -*-
#pyinstaller run.spec --clean
block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 만약 .env 파일이나 이미지 자산, 아이콘 등이 있다면 이곳에 명시합니다.
        # 예: ('attendance_utils/assets/*', 'attendance_utils/assets')
    ],
    hiddenimports=[
        # 1. 외부 통신 핵심 패키지 우회 등록 (Supabase 누락 방지 필수)
        'requests',
        'supabase',
        'postgrest',
        'gotrue',
        'storage3',
        'supafund',
        'httpx',
        
        # 2. NFC 하드웨어 모니터링 모듈 강제 연동
        'smartcard',
        'smartcard.CardMonitoring',
        'smartcard.pcsc',
        
        # 3. 프로젝트 내부 패키지 및 서브 모듈 구조 매핑
        'attendance_utils',
        'attendance_utils.auth_config',
        'attendance_utils.dashboard_controller',
        'attendance_utils.dashboard_ui',
        'attendance_utils.login_controller',
        'attendance_utils.login_ui',
        'attendance_utils.main_controller',
        'attendance_utils.main_ui',
        'attendance_utils.nfc_tag_observer',
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
    upx=True,  # UPX가 있으면 압축, 없으면 자동 무시됨
    console=False,  #  중요: 첫 빌드/테스트 시에는 에러 로그 확인을 위해 True를 권장합니다.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico' # 프로그램의 아이콘 확장자(.ico) 파일이 있다면 주석 제거 후 경로 설정
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