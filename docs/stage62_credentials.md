# 62단계 — 비밀정보 안전 저장 및 로컬 연결 관리

- 공식 100단계 로드맵: 62. API 키 안전 저장 및 연결 관리
- `docs/requirements.md`: **ANF-REQ-068**, "API 키·토큰을 원고 및 로그와 분리해 안전하게 관리한다."
- 소스 기준: `AI_Novel_Factory_stage61_local.zip`, `docs/stage61_test_results.json`, `docs/stage61_verification_log.txt`

## 구현

`src/ai_novel_factory/credential_store.py`

- `CredentialVault`: 이름 검증, 저장/조회/삭제별 명시적 허가, 원문을 저장하지 않고 암호화 바이트만 개별 파일로 저장, 이름은 SHA-256 파일명으로 치환, 파일 원자적 교체, 심볼릭 링크 탐지, 비밀키를 포함하지 않는 상태 표시.
- `WindowsDPAPI`: Windows의 CryptProtectData/CryptUnprotectData, CurrentUser 범위, UI 금지. **현재 Linux 환경에서는 실제 DPAPI 성공을 검증하지 못했으며**, 일반 Linux 실행에서는 기본 비밀 저장소 생성 자체를 거부함. 테스트는 **암호학적 보호 기능이 없는 모의 protector**로 저장 로직만 검증함. 이 대체 기능은 실사용 암호화 수단이 아님.
- `LocalConnectionSettings`: 'disabled' 기본값, 'mock' 또는 로컬 절대경로 실행 파일만 허용. 로컬 연결 설정은 비밀키/인증토큰/원격 엔드포인트/영구 실행 승인 필드를 포함하지 않음. 예상 가능한 비밀 플래그 명칭을 실행 인자에서 거부함.
- 설정 파일은 원자적으로 쓰며, 비밀정보와 구분된 JSON 파일로 저장. 실행 파일 어댑터 연결에 매번 `explicitly_allowed=True` 필요.
- 네트워크 클라이언트나 클라우드 API 연동을 추가하지 않음. 수동 승인 없이 실행 파일을 실행하지 않음.

## 사용 예

```python
from ai_novel_factory.credential_store import CredentialVault, LocalConnectionSettings, save_connection_settings
# Windows에서만 작동하며 해당 Windows 사용자 계정의 DPAPI로 암호화됨.
vault = CredentialVault(r'C:\Users\USERNAME\AppData\Local\AI Novel Factory\secrets')
vault.store('future_service_token', 'USER_PROVIDED_SECRET', explicitly_allowed=True)
# 로컬 전용 설정: 비밀은 이 설정 파일에 쓰지 않는다.
save_connection_settings('model_connection.json', LocalConnectionSettings(provider='mock'))
```

참고: `future_service_token`은 장래 승인된 기능을 위한 *보관 예시*이다. 현재 소스는 외부 서비스에 연결하거나 토큰을 사용하지 않는다. `model_connection.json`과 암호화된 비밀 저장 파일은 사용자 데이터이므로 누적 소스 ZIP에 포함하지 않는다.

## 보안과 검증 한계

- 환경 설정 중 레거시 `ANF_AI_API_KEY` 옵션은 이전 단계의 모의 모드 계약을 위해 남아 있으며 **이번 보호 저장소와 자동 연결되지는 않는다**. 실제 키를 `.env`에 두지 말고 새 저장소를 사용해야 한다.
- 파일 암호화는 Windows 사용자 계정/DPAPI에 의존하며 복구/다른 PC 이전 기능은 없다. Windows 사용자 권한과 OS 보호 조치가 필요하다.
- 경로 상위 디렉터리 전체에 대한 공격자에 의한 경합적 심볼릭 링크 변경 방지, 원격 실행 파일 자체의 네트워크 접근 차단, 프로세스 메모리 노출 방지, 임의 실행 인자의 비밀 여부 자동 식별까지 보장하지 않는다.
- Windows 실제 실행, PySide6 GUI, EXE 빌드, 실제 유료 API·서버 연결 또는 LLM 추론은 이 환경에서 수행하지 않음.
- 현재 Linux Python 3.13.x에서 전체 회귀 테스트 수행; 명세의 Python >=3.12,<3.13 대상 환경 검증은 별도로 필요. 기존 SQLite ResourceWarning 관찰됨.
